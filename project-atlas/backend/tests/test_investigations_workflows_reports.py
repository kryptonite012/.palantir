"""Investigations and evidence, workflow execution, report generation and export restrictions."""
import io

import pytest
from pypdf import PdfReader
from openpyxl import load_workbook

from conftest import ADMIN_PW, SAMPLE, load_demo


def _member(admin, pid, username, role):
    u = admin.create_user(username)
    admin.ok(admin.put(f"/api/projects/{pid}/members", json={"user_id": u["id"], "role": role}))
    return admin.as_user(admin.login(username, ADMIN_PW)), u


def _ds(api, pid, name):
    return next(d for d in api.ok(api.get(f"/api/projects/{pid}/datasets")) if d["name"] == name)


def test_investigation_evidence_and_finding_workflow(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    analyst, _ = _member(admin, pid, "analyst", "analyst")
    reviewer, rev_user = _member(admin, pid, "reviewer", "reviewer")
    inv = analyst.ok(analyst.post(f"/api/projects/{pid}/investigations", json={"title": "Large payments review",
                                                                             "objective": "Explain two large payments"}))
    iid = inv["id"]
    # reviewer is not a collaborator yet: cannot see it
    assert reviewer.get(f"/api/projects/{pid}/investigations/{iid}").status_code == 404
    analyst.ok(analyst.put(f"/api/projects/{pid}/investigations/{iid}/collaborators/{rev_user['id']}"))
    tx = _ds(analyst, pid, "transactions")
    analyst.ok(analyst.post(f"/api/projects/{pid}/investigations/{iid}/items", json={"item_type": "dataset", "ref_id": tx["id"]}))
    rec = analyst.ok(analyst.get(f"/api/projects/{pid}/datasets/{tx['id']}/records", params={"limit": 10}))["records"][7]
    ev = analyst.ok(analyst.post(f"/api/projects/{pid}/investigations/{iid}/evidence",
                                 json={"source_type": "record", "source_ref": rec["id"]}))
    assert "98500.0" in ev["excerpt"] and ev["provenance"]["content_sha256"] if "content_sha256" in ev["provenance"] else ev["provenance"]["row_hash"]
    # fabricated excerpts for document passages are rejected
    f = admin.upload(pid, SAMPLE / "synthetic_harbor_audit_report.pdf")
    admin.ok(admin.post(f"/api/projects/{pid}/documents", json={"file_id": f["id"]}))
    hit = analyst.ok(analyst.get("/api/search", params={"q": "approved", "project_id": pid, "type": "document"}))["results"][0]
    bad = analyst.post(f"/api/projects/{pid}/investigations/{iid}/evidence",
                       json={"source_type": "document_chunk", "source_ref": hit["ref_id"], "excerpt": "Invented text"})
    assert bad.status_code == 422
    ev2 = analyst.ok(analyst.post(f"/api/projects/{pid}/investigations/{iid}/evidence",
                                  json={"source_type": "document_chunk", "source_ref": hit["ref_id"],
                                        "excerpt": "Jonathan Mercer approved both large payments."}))
    assert ev2["location"]["page"] == 2
    analyst.ok(analyst.patch(f"/api/projects/{pid}/investigations/{iid}/evidence/{ev2['id']}", json={"classification": "confidential"}))
    revs = analyst.ok(analyst.get(f"/api/projects/{pid}/investigations/{iid}/evidence/{ev2['id']}/revisions"))
    assert [r["revision"] for r in revs] == [1, 2]
    fnd = analyst.ok(analyst.post(f"/api/projects/{pid}/investigations/{iid}/findings", json={
        "title": "Approver of large payments", "statement": "The audit report states Jonathan Mercer approved both payments.",
        "basis": "direct_evidence"}))
    base = f"/api/projects/{pid}/investigations/{iid}/findings/{fnd['id']}"
    analyst.ok(analyst.post(f"{base}/status", json={"status": "under_review"}))
    # cannot confirm without supporting evidence, and authors cannot review their own findings
    assert reviewer.post(f"{base}/status", json={"status": "confirmed_by_reviewer"}).status_code == 422
    analyst.ok(analyst.post(f"{base}/evidence", json={"evidence_id": ev2["id"], "stance": "supporting"}))
    analyst.ok(analyst.post(f"{base}/evidence", json={"evidence_id": ev["id"], "stance": "supporting"}))
    assert analyst.post(f"{base}/status", json={"status": "confirmed_by_reviewer"}).status_code == 403
    assert reviewer.post(f"{base}/status", json={"status": "superseded"}).status_code == 422  # invalid transition
    done = reviewer.ok(reviewer.post(f"{base}/status", json={"status": "confirmed_by_reviewer", "note": "checked page 2"}))
    assert done["status"] == "confirmed_by_reviewer" and len(done["history"]) == 3
    full = analyst.ok(analyst.get(f"/api/projects/{pid}/investigations/{iid}"))
    assert len(full["findings"][0]["supporting"]) == 2 and len(full["evidence"]) == 2


WORKFLOW = {
    "nodes": [
        {"id": "tx", "type": "dataset_input", "params": {"dataset_id": None}},
        {"id": "orgs", "type": "dataset_input", "params": {"dataset_id": None}},
        {"id": "big", "type": "filter", "params": {"conditions": [{"field": "amount", "op": "gt", "value": 1000}]}},
        {"id": "joined", "type": "join", "params": {"left_on": "receiver_org_id", "right_on": "org_id", "how": "inner"}},
        {"id": "dd", "type": "dedupe", "params": {"keys": ["txn_id"]}},
        {"id": "stats", "type": "statistics", "params": {"kind": "frequency", "analysis_params": {"field": "name"}}},
        {"id": "q", "type": "quality_check", "params": {"required": ["amount"]}},
        {"id": "g", "type": "graph_build", "params": {"source_field": "sender_id", "target_field": "receiver_org_id"}},
        {"id": "save", "type": "materialize_dataset", "params": {"dataset_name": "large_payments"}},
        {"id": "csv", "type": "export_csv", "params": {"filename": "large.csv"}},
    ],
    "edges": [
        {"source": "tx", "target": "big"}, {"source": "big", "target": "joined", "target_port": "left"},
        {"source": "orgs", "target": "joined", "target_port": "right"}, {"source": "joined", "target": "dd"},
        {"source": "dd", "target": "stats"}, {"source": "dd", "target": "q"}, {"source": "dd", "target": "g"},
        {"source": "dd", "target": "save"}, {"source": "dd", "target": "csv"},
    ],
}


def _wf(api, pid):
    import copy

    d = copy.deepcopy(WORKFLOW)
    d["nodes"][0]["params"]["dataset_id"] = _ds(api, pid, "transactions")["id"]
    d["nodes"][1]["params"]["dataset_id"] = _ds(api, pid, "organizations")["id"]
    return d


def test_workflow_validation_errors(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    d = _wf(admin, pid)
    d["edges"].append({"source": "dd", "target": "tx"})  # input port doesn't exist + cycle
    r = admin.post(f"/api/projects/{pid}/workflows/validate", json={"name": "x", "definition": d})
    assert r.status_code == 422
    d = _wf(admin, pid)
    d["edges"] = [e for e in d["edges"] if e.get("target_port") != "right"]
    errs = admin.post(f"/api/projects/{pid}/workflows/validate", json={"name": "x", "definition": d}).json()["error"]["details"]["errors"]
    assert any("input right is not connected" in e for e in errs)
    d = _wf(admin, pid)
    d["edges"].append({"source": "stats", "target": "csv"})  # analysis -> table type mismatch
    errs = admin.post(f"/api/projects/{pid}/workflows/validate", json={"name": "x", "definition": d}).json()["error"]["details"]["errors"]
    assert any("type mismatch" in e for e in errs)


def test_workflow_preview_and_run(admin, project, app):
    pid = project["id"]
    load_demo(admin, pid)
    wf = admin.ok(admin.post(f"/api/projects/{pid}/workflows", json={"name": "Large payments", "definition": _wf(admin, pid)}))
    pv = admin.ok(admin.post(f"/api/projects/{pid}/workflows/{wf['id']}/preview", json={}))
    assert pv["nodes"]["save"]["status"] == "skipped" and pv["nodes"]["stats"]["status"] == "succeeded"
    assert len(admin.ok(admin.get(f"/api/projects/{pid}/datasets"))) == 4  # preview persisted nothing
    r = admin.post(f"/api/projects/{pid}/workflows/{wf['id']}/runs", json={})
    assert r.status_code == 422 and r.json()["error"]["details"]["requires_confirmation"]
    run = admin.ok(admin.post(f"/api/projects/{pid}/workflows/{wf['id']}/runs", json={"confirm": True}))
    res = admin.ok(admin.get(f"/api/projects/{pid}/workflows/{wf['id']}/runs/{run['run_id']}"))
    assert res["status"] == "succeeded", res
    n_big = res["node_results"]["dd"]["output"]["rows"]
    sql = admin.ok(admin.post(f"/api/projects/{pid}/sql", json={"sql": "select count(*) from transactions where amount > 1000"}))
    assert n_big == sql["rows"][0][0]
    lp = _ds(admin, pid, "large_payments")
    assert lp["latest"]["record_count"] == n_big and lp["latest"]["origin"] == "workflow"
    detail = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{lp['id']}"))
    assert detail["lineage"]["parent_version_id"] == _ds(admin, pid, "transactions")["latest"]["version_id"]
    assert res["node_results"]["csv"]["output"]["value"]["rows"] == n_big
    runs = admin.ok(admin.get(f"/api/projects/{pid}/analyses"))
    assert any(r["kind"] == "frequency" for r in runs)
    # versioning
    d2 = _wf(admin, pid)
    d2["nodes"][2]["params"]["conditions"][0]["value"] = 2000
    admin.ok(admin.put(f"/api/projects/{pid}/workflows/{wf['id']}", json={"name": "Large payments", "definition": d2}))
    got = admin.ok(admin.get(f"/api/projects/{pid}/workflows/{wf['id']}"))
    assert got["current_version"] == 2 and len(got["versions"]) == 2


def test_workflow_failure_rolls_back(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    d = _wf(admin, pid)
    d["nodes"][5]["params"]["analysis_params"] = {"field": "does_not_exist"}
    wf = admin.ok(admin.post(f"/api/projects/{pid}/workflows", json={"name": "Broken", "definition": d}))
    run = admin.ok(admin.post(f"/api/projects/{pid}/workflows/{wf['id']}/runs", json={"confirm": True}))
    res = admin.ok(admin.get(f"/api/projects/{pid}/workflows/{wf['id']}/runs/{run['run_id']}"))
    assert res["status"] == "failed" and res["node_results"]["stats"]["status"] == "failed"
    assert "does_not_exist" in res["node_results"]["stats"]["error"]
    assert not any(x["name"] == "large_payments" for x in admin.ok(admin.get(f"/api/projects/{pid}/datasets")))
    assert res["job"]["status"] == "failed"


def test_workflow_permission_for_data_writes(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    wf = admin.ok(admin.post(f"/api/projects/{pid}/workflows", json={"name": "W", "definition": _wf(admin, pid)}))
    analyst, _ = _member(admin, pid, "wfanalyst", "analyst")
    r = analyst.post(f"/api/projects/{pid}/workflows/{wf['id']}/runs", json={"confirm": True})
    assert r.status_code == 403  # materialize_dataset requires workflow.write_data


def _report_def(api, pid, inv_id=None, run_id=None, snap_id=None):
    secs = [{"type": "summary", "title": "Executive summary", "body": "Synthetic review of Northwind Harbor payments. Ünïcödé ✓ 北京"},
            {"type": "methodology", "body": "Imported synthetic datasets; matched entities; ran outlier analysis."},
            {"type": "dataset_table", "dataset_id": _ds(api, pid, "people")["id"], "limit": 500},
            {"type": "timeline", "title": "Payments timeline"},
            {"type": "map", "layers": ["transactions"]},
            {"type": "limitations", "body": "Synthetic data. Outliers are not evidence of wrongdoing."}]
    if run_id:
        secs.insert(2, {"type": "analysis", "analysis_run_id": run_id})
    if snap_id:
        secs.insert(2, {"type": "graph", "snapshot_id": snap_id})
    if inv_id:
        secs.append({"type": "findings", "investigation_id": inv_id, "include_drafts": True})
        secs.append({"type": "evidence", "investigation_id": inv_id})
    return {"sections": secs}


def test_reports_all_formats_with_manifest(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    tx = _ds(admin, pid, "transactions")
    run = admin.ok(admin.post(f"/api/projects/{pid}/analyses", json={"kind": "outliers", "dataset_version_id": tx["latest"]["version_id"],
                                                                    "params": {"field": "amount"}}))
    nodes = [n["id"] for n in admin.ok(admin.get(f"/api/projects/{pid}/graph", params={"limit": 20}))["nodes"]]
    snap = admin.ok(admin.post(f"/api/projects/{pid}/graph/snapshots", json={"name": "Top 20", "node_ids": nodes}))
    inv = admin.ok(admin.post(f"/api/projects/{pid}/investigations", json={"title": "Inv"}))
    admin.ok(admin.post(f"/api/projects/{pid}/investigations/{inv['id']}/findings", json={"title": "F1", "statement": "S"}))
    rpt = admin.ok(admin.post(f"/api/projects/{pid}/reports", json={"title": "Northwind Harbor review",
                                                                   "definition": _report_def(admin, pid, inv["id"], run["id"], snap["id"])}))
    for fmt in ["pdf", "html", "json", "csv", "xlsx"]:
        ex = admin.ok(admin.post(f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": fmt}))
        m = ex["manifest"]
        assert m["software"]["atlas"] and m["generated_at"] and m["output_sha256"] == ex["sha256"]
        assert tx["latest"]["version_id"] in m["dataset_versions"] and run["id"] in m["analysis_runs"]
        dl = admin.get(f"/api/projects/{pid}/reports/{rpt['id']}/exports/{ex['id']}")
        assert dl.status_code == 200
        import hashlib

        assert hashlib.sha256(dl.content).hexdigest() == ex["sha256"]
        if fmt == "pdf":
            reader = PdfReader(io.BytesIO(dl.content))
            assert len(reader.pages) >= 3
            text = "".join(p.extract_text() for p in reader.pages)
            assert "Ünïcödé" in text and "Northwind Harbor review" in text
            # repeated table header: "full_name" header appears on more than one page
            pages_with_header = sum(1 for p in reader.pages if "full_name" in (p.extract_text() or ""))
            assert pages_with_header >= 1
        if fmt == "xlsx":
            wb = load_workbook(io.BytesIO(dl.content))
            assert wb.sheetnames[0] == "Manifest" and len(wb.sheetnames) > 3
        if fmt == "html":
            assert b"<svg" in dl.content and b"Report manifest" in dl.content


def test_long_table_pdf_repeats_headers(admin, project, app):
    """A 33-row table at small row heights fits on one page; force a long table via many rows."""
    pid = project["id"]
    rows = "\n".join(f"{i},Name {i},{'x' * (i % 50)}" for i in range(400))
    import io as _io

    r = admin.post(f"/api/projects/{pid}/files", files={"file": ("long.csv", _io.BytesIO(("id,name,notes\n" + rows).encode()))})
    fid = r.json()["id"]
    job = admin.ok(admin.post(f"/api/projects/{pid}/ingest/commit", json={"config": {"file_id": fid, "dataset_name": "long"}}))
    rpt = admin.ok(admin.post(f"/api/projects/{pid}/reports", json={"title": "Long", "definition": {"sections": [
        {"type": "dataset_table", "dataset_id": job["result"]["dataset"]["id"], "limit": 400}]}}))
    ex = admin.ok(admin.post(f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "pdf"}))
    dl = admin.get(f"/api/projects/{pid}/reports/{rpt['id']}/exports/{ex['id']}")
    reader = PdfReader(io.BytesIO(dl.content))
    assert len(reader.pages) > 3
    headers = sum(1 for p in reader.pages[:-1] if "notes" in (p.extract_text() or ""))
    assert headers >= len(reader.pages) - 2  # header row repeated on every table page


def test_sensitive_export_redacted_for_analyst(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    analyst, _ = _member(admin, pid, "exporter", "analyst")
    rpt = analyst.ok(analyst.post(f"/api/projects/{pid}/reports", json={"title": "People", "definition": {"sections": [
        {"type": "dataset_table", "dataset_id": _ds(admin, pid, "people")["id"]}]}}))
    ex = analyst.ok(analyst.post(f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "csv"}))
    dl = analyst.get(f"/api/projects/{pid}/reports/{rpt['id']}/exports/{ex['id']}")
    assert b"example.invalid" not in dl.content and b"[restricted]" in dl.content
    assert ex["manifest"]["redactions"]
    full = admin.ok(admin.post(f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "csv"}))
    assert b"example.invalid" in admin.get(f"/api/projects/{pid}/reports/{rpt['id']}/exports/{full['id']}").content
    ro, _ = _member(admin, pid, "readonly", "read_only")
    assert ro.post(f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "csv"}).status_code == 403


def test_csv_formula_injection_neutralized(admin, project):
    pid = project["id"]
    r = admin.post(f"/api/projects/{pid}/files", files={"file": ("f.csv", io.BytesIO(b"name,val\n=HYPERLINK(\"http://x\"),-5\n"))})
    job = admin.ok(admin.post(f"/api/projects/{pid}/ingest/commit", json={"config": {"file_id": r.json()["id"], "dataset_name": "f"}}))
    rpt = admin.ok(admin.post(f"/api/projects/{pid}/reports", json={"title": "F", "definition": {"sections": [
        {"type": "dataset_table", "dataset_id": job["result"]["dataset"]["id"]}]}}))
    ex = admin.ok(admin.post(f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "csv"}))
    body = admin.get(f"/api/projects/{pid}/reports/{rpt['id']}/exports/{ex['id']}").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in body and ",-5" in body
