"""Audit chain integrity, backup/restore, persistence across restarts, offline guard, configuration."""
import socket
import sqlite3

import pytest
from fastapi.testclient import TestClient

from conftest import ADMIN_PW, Api, load_demo, make_settings
from project_atlas.core.config import ConfigError, load_settings
from project_atlas.core.netguard import OfflineViolation, guard
from project_atlas.main import create_app


def test_audit_chain_verifies_and_detects_tampering(admin, project, app):
    load_demo(admin, project["id"])
    res = admin.ok(admin.post("/api/admin/audit/verify"))
    assert res["valid"] and res["events_checked"] > 5
    cp = admin.ok(admin.post("/api/admin/audit/checkpoint"))
    assert cp["created"]
    db_path = app.state.ctx.settings.resolved_database_url[len("sqlite:///"):]
    con = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE audit_events SET actor_name='mallory' WHERE seq=2")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM audit_events WHERE seq=2")
    # a privileged attacker drops the trigger and edits a row: the chain detects it
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("UPDATE audit_events SET actor_name='mallory' WHERE seq=2")
    con.commit()
    con.close()
    bad = admin.ok(admin.post("/api/admin/audit/verify"))
    assert bad["valid"] is False and bad["broken_at_seq"] == 2


def test_audit_covers_key_operations(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    actions = {e["action"] for e in admin.ok(admin.get("/api/admin/audit", params={"limit": 500}))["events"]}
    for a in ["auth.setup", "project.create", "file.upload", "ingest.started", "ingest.completed", "job.succeeded"]:
        assert a in actions, a
    csv_ = admin.get("/api/admin/audit/export")
    assert csv_.status_code == 200 and b"ingest.completed" in csv_.content


def test_backup_verify_restore(admin, project, app):
    pid = project["id"]
    load_demo(admin, pid)
    before = admin.ok(admin.get(f"/api/projects/{pid}/overview"))
    b = admin.ok(admin.post("/api/admin/backups", json={}))
    assert b["counts"]["records"] == before["records"]
    v = admin.ok(admin.post("/api/admin/backups/verify", json={"filename": b["filename"]}))
    assert v["valid"] and v["database_integrity"] == "ok"
    # change state after the backup
    ds = next(d for d in admin.ok(admin.get(f"/api/projects/{pid}/datasets")) if d["name"] == "contacts")
    admin.ok(admin.delete(f"/api/projects/{pid}/datasets/{ds['id']}", params={"confirm_name": "contacts"}))
    assert admin.ok(admin.get(f"/api/projects/{pid}/overview"))["datasets"] == 3
    preview = admin.ok(admin.post("/api/admin/backups/restore", json={"filename": b["filename"]}))
    assert preview["preview"] and preview["valid"]
    res = admin.ok(admin.post("/api/admin/backups/restore", json={"filename": b["filename"], "confirm": True}))
    assert res["count_mismatches"] == {}
    after = admin.ok(admin.get(f"/api/projects/{pid}/overview"))
    assert after["datasets"] == 4 and after["records"] == before["records"] and after["entities"] == before["entities"]
    # essential functions after restore: search, SQL over restored parquet, audit chain
    assert admin.ok(admin.get("/api/search", params={"q": "Thorsen", "project_id": pid}))["total"] >= 1
    assert admin.ok(admin.post(f"/api/projects/{pid}/sql", json={"sql": "select count(*) from contacts"}))["rows"] == [[5]]
    assert admin.ok(admin.post("/api/admin/audit/verify"))["valid"]
    assert any(e["action"] == "backup.restore" for e in admin.ok(admin.get("/api/admin/audit"))["events"])


def test_encrypted_backup_and_corruption(admin, project, app):
    load_demo(admin, project["id"])
    b = admin.ok(admin.post("/api/admin/backups", json={"passphrase": "correct horse battery staple"}))
    assert b["filename"].endswith(".enc")
    assert admin.post("/api/admin/backups/verify", json={"filename": b["filename"]}).status_code == 422
    assert admin.post("/api/admin/backups/verify", json={"filename": b["filename"], "passphrase": "wrong passphrase!!"}).status_code == 422
    ok = admin.ok(admin.post("/api/admin/backups/verify", json={"filename": b["filename"], "passphrase": "correct horse battery staple"}))
    assert ok["valid"]
    path = app.state.ctx.settings.backup_dir / b["filename"]
    data = bytearray(path.read_bytes())
    data[-20] ^= 0xFF
    path.write_bytes(bytes(data))
    assert admin.post("/api/admin/backups/verify", json={"filename": b["filename"], "passphrase": "correct horse battery staple"}).status_code == 422
    assert admin.post("/api/admin/backups/verify", json={"filename": "../etc/passwd"}).status_code == 422


def test_persistence_across_restart(tmp_path):
    settings = make_settings(tmp_path)
    app1 = create_app(settings)
    with TestClient(app1) as c:
        tok = app1.state.ctx.ensure_setup_token()
        t = c.post("/api/auth/setup", json={"setup_token": tok, "username": "admin", "display_name": "A", "password": ADMIN_PW}).json()["token"]
        api = Api(c, t)
        pid = api.ok(api.post("/api/projects", json={"name": "Persist"}))["id"]
        load_demo(api, pid)
        before = api.ok(api.get(f"/api/projects/{pid}/overview"))
        n_audit = api.ok(api.get("/api/admin/audit"))["total"]
    app1.state.ctx.dispose()
    app2 = create_app(make_settings(tmp_path))
    with TestClient(app2) as c:
        api = Api(c, None)
        api.token = api.login("admin", ADMIN_PW)
        assert api.ok(api.get(f"/api/projects/{pid}/overview")) == before
        assert api.ok(api.get("/api/admin/audit"))["total"] > n_audit
        assert api.ok(api.post("/api/admin/audit/verify"))["valid"]
        assert c.get("/api/auth/setup-status").json()["needs_setup"] is False
    app2.state.ctx.dispose()


def test_network_guard_blocks_external(admin):
    assert guard.installed
    with pytest.raises(OfflineViolation):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
    with pytest.raises(OfflineViolation):
        socket.getaddrinfo("example.com", 443)
    # loopback stays allowed
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    cli = socket.create_connection(srv.getsockname(), timeout=1)
    cli.close()
    srv.close()
    rep = admin.ok(admin.get("/api/system/offline-check"))
    by = {c["check"]: c for c in rep["checks"]}
    assert by["guard_live_probe"]["ok"] and by["telemetry_disabled"]["ok"] and by["ai_endpoint_local"]["ok"]


@pytest.mark.parametrize("env, msg", [
    ({"ATLAS_TELEMETRY_ENABLED": "true"}, "Telemetry"),
    ({"ATLAS_HOST": "0.0.0.0"}, "ATLAS_ALLOW_LAN"),
    ({"ATLAS_HOST": "8.8.8.8"}, "loopback or a private"),
    ({"ATLAS_AI_ENABLED": "true"}, "requires ATLAS_AI_BASE_URL"),
    ({"ATLAS_AI_BASE_URL": "https://api.example.com"}, "Offline mode only permits"),
    ({"ATLAS_HOST": "0.0.0.0", "ATLAS_ALLOW_LAN": "true", "ATLAS_ENV": "production"}, "TLS"),
    ({"ATLAS_PORT": "notanumber"}, "Invalid integer"),
])
def test_config_validation(env, msg):
    with pytest.raises(ConfigError, match=msg):
        load_settings(env)


def test_config_lan_profile_ok():
    s = load_settings({"ATLAS_HOST": "0.0.0.0", "ATLAS_ALLOW_LAN": "true", "ATLAS_ENV": "production", "ATLAS_TLS_TERMINATED": "true",
                       "ATLAS_DATABASE_URL": "postgresql://atlas@db/atlas_prod"})
    assert not s.is_sqlite


def test_empty_dashboard_has_no_fabricated_numbers(admin, project):
    ov = admin.ok(admin.get(f"/api/projects/{project['id']}/overview"))
    assert ov["datasets"] == ov["records"] == ov["entities"] == ov["relationships"] == ov["documents"] == 0
    assert ov["storage_bytes"] == 0 and ov["ai"]["healthy_models"] == 0
