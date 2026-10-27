"""Ingestion pipeline: formats, inspection, dry runs, quality checks, versions, malformed uploads."""
import io
import json
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
from openpyxl import Workbook

from conftest import PEOPLE_CONFIG, SAMPLE, TXN_CONFIG, load_demo


def _upload_bytes(api, pid, name, data, status=200):
    r = api.post(f"/api/projects/{pid}/files", files={"file": (name, io.BytesIO(data))})
    assert r.status_code == status, r.text
    return r.json()


def test_inspect_detects_schema(admin, project):
    pid = project["id"]
    f = admin.upload(pid, SAMPLE / "synthetic_transactions.csv")
    insp = admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))
    assert insp["delimiter"] == "," and insp["encoding"].startswith("utf-8")
    assert insp["inferred_types"]["amount"] == "float"
    assert insp["suggested_mapping"]["latitude"]["type"] == "latitude"
    assert len(insp["preview"]) == 20


def test_dry_run_writes_nothing_and_reports_quality(admin, project):
    pid = project["id"]
    f = admin.upload(pid, SAMPLE / "synthetic_transactions.csv")
    rep = admin.ok(admin.post(f"/api/projects/{pid}/ingest/preview", json={"config": {"file_id": f["id"], **TXN_CONFIG}}))
    q = rep["quality"]["issue_counts"]
    expected = json.loads((SAMPLE / "expected_results.json").read_text())["transactions"]
    assert q.get("timestamp_error") == expected["invalid_timestamps"]
    assert q.get("coordinate_error") == expected["latitude_out_of_range"] + expected["null_island"]
    assert rep["counts"]["records"] == expected["rows"]
    assert admin.ok(admin.get(f"/api/projects/{pid}/datasets")) == []
    # locale-formatted number normalized while the original value is kept
    row33 = next(p for p in rep["preview"] if p["row_index"] == 33) if any(p["row_index"] == 33 for p in rep["preview"]) else None
    assert row33 is None or row33["normalized"]["amount"] == 1250.5


def test_commit_people_quality_and_lineage(admin, project):
    pid = project["id"]
    res = admin.import_file(pid, SAMPLE / "synthetic_people.csv", PEOPLE_CONFIG)
    exp = json.loads((SAMPLE / "expected_results.json").read_text())["people"]
    q = res["quality"]["issue_counts"]
    assert q["duplicate_row"] == exp["exact_duplicate_rows"]
    assert q["duplicate_key"] == 1
    assert q["invalid_format"] == exp["invalid_email_rows"]
    ds = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{res['dataset']['id']}"))
    assert ds["latest"]["record_count"] == exp["rows"]
    assert ds["lineage"]["source_file"]["sha256"]
    assert ds["lineage"]["derived"]["entities"] == 32 + 8
    # original vs normalized kept separately
    recs = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{res['dataset']['id']}/records", params={"limit": 50}))
    r9 = next(r for r in recs["records"] if r["row_index"] == 9)
    assert r9["raw"]["phone"] == "N/A" and r9["normalized"]["phone"] is None
    issues = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{res['dataset']['id']}/quality", params={"check": "invalid_format"}))
    assert issues["issues"][0]["field"] == "email"


def test_new_version_and_schema_drift(admin, project):
    pid = project["id"]
    res = admin.import_file(pid, SAMPLE / "synthetic_people.csv", PEOPLE_CONFIG)
    cfg = {k: v for k, v in PEOPLE_CONFIG.items() if k not in {"dataset_name", "entities", "relationships"}}
    cfg["mapping"] = {k: v for k, v in cfg["mapping"].items() if k != "city"}
    res2 = admin.import_file(pid, SAMPLE / "synthetic_people.csv", {**cfg, "dataset_id": res["dataset"]["id"]})
    assert res2["dataset"]["version"] == 2
    assert res2["quality"]["schema_drift"]["removed"] == ["city"]
    detail = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{res['dataset']['id']}"))
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    # version 1 records still retrievable
    v1 = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{res['dataset']['id']}/records", params={"version": 1, "limit": 1}))
    assert "city" in v1["records"][0]["normalized"]


def test_other_formats(admin, project, tmp_path):
    pid = project["id"]
    # JSONL with nested objects
    jl = "\n".join(json.dumps({"id": i, "name": f"N{i}", "meta": {"score": i * 1.5}}) for i in range(5)).encode()
    f = _upload_bytes(admin, pid, "x.jsonl", jl)
    insp = admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))
    assert "meta.score" in insp["columns"]
    # JSON wrapped array
    j = json.dumps({"data": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]}).encode()
    f = _upload_bytes(admin, pid, "w.json", j)
    assert admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))["columns"] == ["a", "b"]
    # TSV
    f = _upload_bytes(admin, pid, "t.tsv", b"a\tb\n1\t2\n3\t4\n")
    assert admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))["delimiter"] == "\t"
    # XML
    xml = b"<rows><row id='1'><name>A</name></row><row id='2'><name>B</name></row></rows>"
    f = _upload_bytes(admin, pid, "r.xml", xml)
    insp = admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))
    assert insp["columns"] == ["@id", "name"] and len(insp["preview"]) == 2
    # XLSX
    wb = Workbook()
    ws = wb.active
    ws.append(["k", "v"])
    ws.append(["a", 1])
    buf = io.BytesIO()
    wb.save(buf)
    f = _upload_bytes(admin, pid, "s.xlsx", buf.getvalue())
    assert admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))["preview"] == [{"k": "a", "v": 1}]
    # SQLite
    dbp = tmp_path / "src.sqlite"
    con = sqlite3.connect(dbp)
    con.execute("create table t (x integer, y text)")
    con.executemany("insert into t values (?, ?)", [(1, "a"), (2, "b")])
    con.commit()
    con.close()
    f = _upload_bytes(admin, pid, "src.sqlite", dbp.read_bytes())
    insp = admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))
    assert insp["tables"] == ["t"] and insp["columns"] == ["x", "y"]
    # Parquet, committed end to end
    pqp = tmp_path / "p.parquet"
    pq.write_table(pa.table({"name": ["A", "B"], "value": [1.5, 2.5]}), pqp)
    res = admin.import_file(pid, pqp, {"dataset_name": "parquet_ds"})
    assert res["counts"]["records"] == 2


def test_cp1252_encoding_and_mojibake_check(admin, project):
    pid = project["id"]
    data = "name,city\nJosé,Tromsø\n".encode("cp1252")
    f = _upload_bytes(admin, pid, "enc.csv", data)
    insp = admin.ok(admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}))
    assert insp["encoding"] == "cp1252" and insp["preview"][0]["name"] == "José"
    moj = "name\nJosÃ© Ã˜stby\n".encode("utf-8")
    f2 = _upload_bytes(admin, pid, "moj.csv", moj)
    rep = admin.ok(admin.post(f"/api/projects/{pid}/ingest/preview", json={"config": {"file_id": f2["id"], "dataset_name": "m"}}))
    assert rep["quality"]["issue_counts"].get("encoding") == 1


def test_malformed_uploads_rejected(admin, project):
    pid = project["id"]
    _upload_bytes(admin, pid, "evil.exe", b"MZ....", status=422)
    _upload_bytes(admin, pid, "fake.pdf", b"not a pdf", status=422)
    _upload_bytes(admin, pid, "fake.xlsx", b"hello", status=422)
    _upload_bytes(admin, pid, "empty.csv", b"", status=422)
    _upload_bytes(admin, pid, "bin.csv", b"a,b\n\x00\x00\x00", status=422)
    # XML entity expansion (billion laughs) is refused
    bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><rows><row>&lol;</row></rows>'
    f = _upload_bytes(admin, pid, "bomb.xml", bomb)
    r = admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]})
    assert r.status_code == 422
    # invalid JSON
    f = _upload_bytes(admin, pid, "bad.json", b"{not json")
    assert admin.post(f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]}).status_code == 422


def test_path_traversal_filename_sanitized(admin, project, app):
    pid = project["id"]
    f = _upload_bytes(admin, pid, "../../../../etc/passwd.csv", b"a\n1\n")
    assert f["original_name"] == "passwd.csv"
    root = app.state.ctx.settings.storage_dir.resolve()
    stored = list((root / "files" / pid).iterdir())
    assert len(stored) == 1 and root in stored[0].resolve().parents


def test_invalid_mapping_rejected(admin, project):
    pid = project["id"]
    f = admin.upload(pid, SAMPLE / "synthetic_people.csv")
    for bad in [{"full_name": {"target": "Bad Name"}}, {"full_name": {"target": "x", "type": "nonsense"}},
                {"full_name": {"target": "x", "type": "datetime", "timezone": "Mars/Olympus"}}]:
        r = admin.post(f"/api/projects/{pid}/ingest/preview", json={"config": {"file_id": f["id"], "mapping": bad}})
        assert r.status_code == 422, bad
    r = admin.post(f"/api/projects/{pid}/ingest/preview", json={"config": {
        "file_id": f["id"], "mapping": PEOPLE_CONFIG["mapping"], "entities": [{"entity_type": "spaceship", "name_field": "full_name"}]}})
    assert r.status_code == 422


def test_referential_integrity_check(admin, project):
    pid = project["id"]
    orgs = admin.import_file(pid, SAMPLE / "synthetic_organizations.csv", {"dataset_name": "orgs"})
    data = b"person,org_id\nA,ORG-001\nB,ORG-999\n"
    f = _upload_bytes(admin, pid, "ref.csv", data)
    rep = admin.ok(admin.post(f"/api/projects/{pid}/ingest/preview", json={"config": {
        "file_id": f["id"], "dataset_name": "ref",
        "quality": {"references": {"org_id": {"dataset_id": orgs["dataset"]["id"], "field": "org_id"}}}}}))
    assert rep["quality"]["issue_counts"]["referential_integrity"] == 1


def test_timezone_handling(admin, project):
    pid = project["id"]
    data = b"t\n2025-03-01 12:00\n2025-07-01 12:00\n2025-03-01T12:00:00+05:30\n"
    f = _upload_bytes(admin, pid, "tz.csv", data)
    rep = admin.ok(admin.post(f"/api/projects/{pid}/ingest/preview", json={"config": {
        "file_id": f["id"], "dataset_name": "tz", "mapping": {"t": {"target": "t", "type": "datetime", "timezone": "Europe/Oslo"}}}}))
    vals = [p["normalized"]["t"] for p in rep["preview"]]
    assert vals == ["2025-03-01T11:00:00Z", "2025-07-01T10:00:00Z", "2025-03-01T06:30:00Z"]  # CET, CEST, explicit offset


def test_job_cancel_and_retry(admin, project, app):
    pid = project["id"]
    f = admin.upload(pid, SAMPLE / "synthetic_people.csv")
    # a job that fails (bad config caught at run time) can be retried after fixing nothing -> fails again
    job = admin.ok(admin.post(f"/api/projects/{pid}/ingest/commit", json={"config": {
        "file_id": f["id"], "dataset_name": "x", "quality": {"references": {"a": {"dataset_id": "dst_missing", "field": "a"}}}}}))
    assert job["status"] == "failed" and "not found" in job["error"]
    retried = admin.ok(admin.post(f"/api/jobs/{job['id']}/retry"))
    assert retried["status"] == "failed" and retried["attempts"] == 2
    assert admin.ok(admin.get(f"/api/projects/{pid}/datasets")) == []  # failed import left no partial data


def test_dataset_delete_requires_confirmation(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    ds = next(d for d in admin.ok(admin.get(f"/api/projects/{pid}/datasets")) if d["name"] == "contacts")
    assert admin.delete(f"/api/projects/{pid}/datasets/{ds['id']}", params={"confirm_name": "wrong"}).status_code == 422
    res = admin.ok(admin.delete(f"/api/projects/{pid}/datasets/{ds['id']}", params={"confirm_name": "contacts"}))
    assert res["orphan_entities_removed"] == 5
    assert admin.ok(admin.get("/api/search", params={"q": "Thorsen", "project_id": pid}))["total"] == 0
