"""Demo workspace, saved views, watches/notifications, activity, insights, explain, retention, lifecycle."""
import os
from datetime import timedelta

import pytest

from conftest import ADMIN_PW, PEOPLE_CONFIG, SAMPLE, load_demo


def _member(admin, pid, username, role):
    u = admin.create_user(username)
    admin.ok(admin.put(f"/api/projects/{pid}/members", json={"user_id": u["id"], "role": role}))
    return admin.as_user(admin.login(username, ADMIN_PW)), u


def test_one_click_demo_workspace(admin):
    r = admin.ok(admin.post("/api/projects/demo", json={}))
    assert r["job"]["status"] == "succeeded", r["job"]
    res = r["job"]["result"]
    assert res["datasets"] == {"organizations": 8, "people": 33, "contacts": 5, "transactions": 60}
    assert res["documents"] == 5 and res["geo_features"] == 4
    assert res["resolution"]["by_band"] == {"strong": 2, "ambiguous": 1}
    pid = r["project"]["id"]
    ov = admin.ok(admin.get(f"/api/projects/{pid}/overview"))
    assert ov["datasets"] == 4 and ov["documents"] == 5
    assert all(d["is_synthetic"] for d in admin.ok(admin.get(f"/api/projects/{pid}/datasets")))
    assert admin.post("/api/projects/demo", json={}).status_code == 409
    notes = admin.ok(admin.get("/api/notifications"))
    assert any(n["title"] == "Demo workspace finished" for n in notes["items"])


def test_demo_requires_project_create(admin):
    admin.create_user("plain")
    u = admin.as_user(admin.login("plain", ADMIN_PW))
    assert u.post("/api/projects/demo", json={}).status_code == 403


def test_saved_views(admin, project):
    pid = project["id"]
    vid = admin.ok(admin.post("/api/views", json={"name": "Big payments", "path": "/search?q=amount%3E50000", "project_id": pid}))["id"]
    assert admin.ok(admin.get("/api/views", params={"project_id": pid}))[0]["path"] == "/search?q=amount%3E50000"
    for bad in ["https://evil.example/x", "//evil.example", "javascript:alert(1)", "relative"]:
        assert admin.post("/api/views", json={"name": "x", "path": bad}).status_code == 422, bad
    other = admin.create_user("viewer2")
    o = admin.as_user(admin.login("viewer2", ADMIN_PW))
    assert o.ok(o.get("/api/views")) == []
    assert o.delete(f"/api/views/{vid}").status_code == 404
    assert o.post("/api/views", json={"name": "x", "path": "/", "project_id": pid}).status_code == 404
    admin.ok(admin.delete(f"/api/views/{vid}"))


def test_watch_notifies_on_new_data(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    analyst, _ = _member(admin, pid, "watcher", "analyst")
    ent = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"q": "Rafael Ortiz", "entity_type": "person"}))["entities"][0]
    analyst.ok(analyst.put(f"/api/projects/{pid}/watches/{ent['id']}"))
    assert analyst.ok(analyst.get(f"/api/projects/{pid}/watches"))[0]["entity_id"] == ent["id"]
    before = analyst.ok(analyst.get("/api/notifications"))["unread"]
    # a new version of the people dataset contains P-1003 (Rafael Ortiz) twice
    ds = next(d for d in admin.ok(admin.get(f"/api/projects/{pid}/datasets")) if d["name"] == "people")
    cfg = {k: v for k, v in PEOPLE_CONFIG.items() if k != "dataset_name"}
    admin.import_file(pid, SAMPLE / "synthetic_people.csv", {**cfg, "dataset_id": ds["id"]})
    notes = analyst.ok(analyst.get("/api/notifications"))
    assert notes["unread"] == before + 1
    n = notes["items"][0]
    assert n["kind"] == "watch" and "Rafael Ortiz" in n["title"] and n["link"] == f"/entities/{ent['id']}"
    assert analyst.ok(analyst.post("/api/notifications/read"))["marked"] >= 1
    assert analyst.ok(analyst.get("/api/notifications"))["unread"] == 0
    # admin (the importer) gets job notifications; the analyst does not see them
    assert not any(x["kind"] == "job" for x in notes["items"])
    assert any(x["kind"] == "job" for x in admin.ok(admin.get("/api/notifications"))["items"])
    analyst.ok(analyst.delete(f"/api/projects/{pid}/watches/{ent['id']}"))
    assert analyst.ok(analyst.get(f"/api/projects/{pid}/watches")) == []


def test_notifications_hidden_after_losing_project_access(admin, project):
    pid = project["id"]
    analyst, user = _member(admin, pid, "leaver", "data_engineer")
    analyst.import_file(pid, SAMPLE / "synthetic_organizations.csv", {"dataset_name": "orgs"})
    assert analyst.ok(analyst.get("/api/notifications"))["items"]
    admin.ok(admin.delete(f"/api/projects/{pid}/members/{user['id']}"))
    assert analyst.ok(analyst.get("/api/notifications"))["items"] == []


def test_activity_and_insights(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    ro, _ = _member(admin, pid, "reader", "read_only")
    act = ro.ok(ro.get(f"/api/projects/{pid}/activity"))
    assert act and all("details" not in a for a in act)
    assert {"ingest.completed", "project.create"} & {a["action"] for a in act}
    ins = ro.ok(ro.get(f"/api/projects/{pid}/insights"))
    assert ins["entities_by_type"] == {"person": 37, "organization": 8}
    assert ins["quality_by_check"]["timestamp_error"] == 1
    assert ins["top_connected"][0]["entity_type"] == "organization"
    assert sum(m["count"] for m in ins["events_by_month"]) == 59
    empty = admin.ok(admin.post("/api/projects", json={"name": "Empty"}))
    e = admin.ok(admin.get(f"/api/projects/{empty['id']}/insights"))
    assert e["entities_by_type"] == {} and e["top_connected"] == [] and e["events_by_month"] == []


def test_explain_connection_with_evidence(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    q = lambda name: admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"q": name}))["entities"][0]["id"]
    a, b = q("Northwind Harbor Logistics"), q("Bluefjord Freight")
    r = admin.ok(admin.get(f"/api/projects/{pid}/graph/explain", params={"source": a, "target": b}))
    assert r["found"] and r["paths"][0]["length"] == 2 and "does not establish" in r["note"]
    hop = r["paths"][0]["hops"][0]
    sample = hop["relationships"][0]["evidence_sample"]
    assert sample["kind"] == "record" and sample["dataset"] in {"people", "transactions"}
    # analysts see the evidence with sensitive fields redacted
    analyst, _ = _member(admin, pid, "explainer", "analyst")
    r2 = analyst.ok(analyst.get(f"/api/projects/{pid}/graph/explain", params={"source": a, "target": b, "max_paths": 10}))
    texts = " ".join(rel["evidence_sample"].get("text") or "" for p in r2["paths"] for h in p["hops"] for rel in h["relationships"])
    assert "example.invalid" not in texts
    iso = q("Gunnar Thorsen")
    assert admin.ok(admin.get(f"/api/projects/{pid}/graph/explain", params={"source": a, "target": iso}))["found"] is False


def test_quality_explanations_without_ai(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    ds = next(d for d in admin.ok(admin.get(f"/api/projects/{pid}/datasets")) if d["name"] == "transactions")
    r = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{ds['id']}/quality/explain"))
    checks = {e["check"]: e for e in r["explanations"]}
    assert checks["coordinate_error"]["count"] == 2 and "never infers" in checks["coordinate_error"]["action"]
    assert r["narrative"] is None and r["label"] == "deterministic_explanation"


def test_retention_purges_superseded_versions_and_flags_current(admin, project, app):
    pid = project["id"]
    first = admin.import_file(pid, SAMPLE / "synthetic_people.csv", {**PEOPLE_CONFIG, "retention_policy": "1y"})
    cfg = {k: v for k, v in PEOPLE_CONFIG.items() if k != "dataset_name"}
    admin.import_file(pid, SAMPLE / "synthetic_people.csv", {**cfg, "dataset_id": first["dataset"]["id"]})
    assert admin.ok(admin.get("/api/admin/retention"))["purge"] == []
    from project_atlas.database.models import DatasetVersion, utcnow

    with app.state.ctx.sm() as db:
        for v in db.query(DatasetVersion).all():
            v.imported_at = utcnow() - timedelta(days=400)
        db.commit()
    plan = admin.ok(admin.get("/api/admin/retention"))
    assert [p["version"] for p in plan["purge"]] == [1] and [p["version"] for p in plan["review_required"]] == [2]
    assert admin.post("/api/admin/retention/apply").status_code == 422  # confirmation required
    res = admin.ok(admin.post("/api/admin/retention/apply", params={"confirm": True}))
    assert res["purged_versions"] == 1 and res["purged_records"] == 33 and res["review_required"] == 1
    dsid = first["dataset"]["id"]
    v1 = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{dsid}/records", params={"version": 1}))
    assert v1["records"] == []
    assert len(admin.ok(admin.get(f"/api/projects/{pid}/datasets/{dsid}/records", params={"version": 2}))["records"]) == 33
    assert admin.ok(admin.post(f"/api/projects/{pid}/sql", json={"sql": "select count(*) from people"}))["rows"] == [[33]]
    n = [x for x in admin.ok(admin.get("/api/notifications"))["items"] if x["kind"] == "retention"]
    assert len(n) == 1 and n[0]["link"] == f"/catalog/{dsid}"
    admin.ok(admin.post("/api/admin/retention/apply", params={"confirm": True}))  # idempotent; no duplicate notice
    assert len([x for x in admin.ok(admin.get("/api/notifications"))["items"] if x["kind"] == "retention"]) == 1
    assert any(e["action"] == "retention.purge" for e in admin.ok(admin.get("/api/admin/audit"))["events"])
    assert admin.ok(admin.post("/api/admin/audit/verify"))["valid"]
    bad = admin.patch(f"/api/projects/{pid}/datasets/{dsid}", json={"retention_policy": "forever"})
    assert bad.status_code == 422


def test_project_archive_and_delete(admin, project, app):
    pid = project["id"]
    load_demo(admin, pid)
    pa, _ = _member(admin, pid, "padmin", "project_admin")
    pa.ok(pa.patch(f"/api/projects/{pid}/archive", json={"archived": True}))
    assert admin.ok(admin.get(f"/api/projects/{pid}"))["archived"] is True
    assert pa.delete(f"/api/projects/{pid}", params={"confirm_name": project["name"]}).status_code == 403  # not system admin
    assert admin.delete(f"/api/projects/{pid}", params={"confirm_name": "nope"}).status_code == 422
    files_dir = app.state.ctx.settings.files_dir / pid
    assert files_dir.exists()
    admin.ok(admin.delete(f"/api/projects/{pid}", params={"confirm_name": project["name"]}))
    assert admin.get(f"/api/projects/{pid}").status_code == 404
    assert not files_dir.exists()
    assert admin.ok(admin.get("/api/search", params={"q": "Okafor"}))["total"] == 0
    assert admin.ok(admin.post("/api/admin/audit/verify"))["valid"]


def test_scheduled_backup_passphrase_file(app, tmp_path):
    from project_atlas.backup.service import create_backup, scheduled_passphrase
    from project_atlas.core.errors import ValidationFailed

    ctx = app.state.ctx
    assert scheduled_passphrase(ctx) is None
    f = tmp_path / "pass.txt"
    f.write_text("a sufficiently long passphrase\n")
    os.chmod(f, 0o644)
    ctx.settings.backup_passphrase_file = f
    with pytest.raises(ValidationFailed, match="chmod 600"):
        scheduled_passphrase(ctx)
    os.chmod(f, 0o600)
    pw = scheduled_passphrase(ctx)
    res = create_backup(ctx, user_id=None, passphrase=pw, kind="scheduled")
    assert res["encrypted"] and res["filename"].endswith(".enc")
