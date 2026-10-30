"""Search syntax and injection safety; documents, evidence retrieval and the grounded assistant."""
import pytest

from conftest import SAMPLE, load_demo
from project_atlas.core.errors import ValidationFailed
from project_atlas.search.service import parse_query


def test_query_parser():
    assert parse_query("alpha beta").fts == '"alpha" AND "beta"'
    assert parse_query('"exact phrase" OR x').fts == '"exact phrase" OR "x"'
    assert parse_query("(a OR b) NOT c").fts == '( "a" OR "b" ) NOT "c"'
    assert parse_query("pref*").fts == '"pref"*'
    pq = parse_query("type:entity amount>100 Oslo")
    assert pq.types == {"entity"} and pq.field_filters == [("amount", ">", "100")] and pq.fts == '"Oslo"'
    for bad in ["(a", "a)", "OR a", "()", "type:bogus"]:
        with pytest.raises(ValidationFailed):
            parse_query(bad)


def test_fts_injection_is_neutralized(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    for q in ['Okafor" OR project_id:*', "Okafor'; DROP TABLE users; --", "NEAR(a b)", "title:x*", "^^^", '"" OR ""']:
        r = admin.get("/api/search", params={"q": q, "project_id": pid})
        assert r.status_code in (200, 422), (q, r.text)
    assert admin.get("/api/auth/me").status_code == 200  # nothing broke


def test_search_types_filters_history_saved(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    r = admin.ok(admin.get("/api/search", params={"q": "Okafor", "project_id": pid}))
    types = {x["doc_type"] for x in r["results"]}
    assert {"entity", "dataset_record"} <= types
    ents = admin.ok(admin.get("/api/search", params={"q": "type:entity Okafor", "project_id": pid}))
    assert {x["doc_type"] for x in ents["results"]} == {"entity"}
    big = admin.ok(admin.get("/api/search", params={"q": "amount>50000", "project_id": pid}))
    assert big["total"] == 2
    phrase = admin.ok(admin.get("/api/search", params={"q": '"Bluefjord Freight"', "project_id": pid}))
    assert phrase["total"] >= 1
    prefix = admin.ok(admin.get("/api/search", params={"q": "Okaf*", "project_id": pid}))
    assert prefix["total"] >= 1
    future = admin.ok(admin.get("/api/search", params={"q": "Okafor", "project_id": pid, "date_from": "2999-01-01"}))
    assert future["total"] == 0
    hist = admin.ok(admin.get("/api/search/history", params={"project_id": pid}))
    assert hist["items"][0]["query"] == "Okafor" and hist["retention_days"] == 90
    sid = admin.ok(admin.post("/api/search/saved", json={"project_id": pid, "name": "big", "query": "amount>50000"}))["id"]
    assert admin.ok(admin.get("/api/search/saved", params={"project_id": pid}))[0]["id"] == sid
    assert admin.post("/api/search/saved", json={"project_id": pid, "name": "bad", "query": "(oops"}).status_code == 422


def _process(api, pid, name):
    f = api.upload(pid, SAMPLE / name)
    job = api.ok(api.post(f"/api/projects/{pid}/documents", json={"file_id": f["id"], "is_synthetic": True}))
    assert job["status"] == "succeeded", job
    return job["result"]


def test_document_processing_all_formats(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    pdf = _process(admin, pid, "synthetic_harbor_audit_report.pdf")
    assert pdf["pages"] == 2 and pdf["language"] == "en"
    docx = _process(admin, pid, "synthetic_meeting_minutes.docx")
    assert docx["classification"] == "meeting_notes"
    eml = _process(admin, pid, "synthetic_shipment_email.eml")
    memo = _process(admin, pid, "synthetic_memo_cold_storage.txt")
    d = admin.ok(admin.get(f"/api/projects/{pid}/documents/{memo['document_id']}"))
    kinds = {c["kind"] for c in d["entity_candidates"]}
    assert {"email", "known_entity"} <= kinds
    assert all(c["status"] == "candidate" for c in d["entity_candidates"])
    known = {c["text"] for c in d["entity_candidates"] if c["kind"] == "known_entity"}
    assert {"Tomas Berg", "Bluefjord Freight AS"} <= known
    em = admin.ok(admin.get(f"/api/projects/{pid}/documents/{eml['document_id']}"))
    assert em["metadata"]["Subject"].startswith("Shipment schedule") and em["page_label"] == "message"
    # duplicate detection
    dup = _process(admin, pid, "synthetic_memo_cold_storage.txt")
    assert dup["duplicate_of"] == memo["document_id"]
    page = admin.ok(admin.get(f"/api/projects/{pid}/documents/{pdf['document_id']}/pages/2"))
    assert "Jonathan Mercer" in page["chunks"][0]["text"]
    sim = admin.ok(admin.get(f"/api/projects/{pid}/documents/{memo['document_id']}/similar"))
    assert sim[0]["document_id"] == dup["document_id"] and sim[0]["cosine"] > 0.99
    # entity detail links documents mentioning the entity
    ent = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"q": "Jonathan Mercer"}))["entities"][0]
    det = admin.ok(admin.get(f"/api/projects/{pid}/entities/{ent['id']}"))
    assert any(ld["document_id"] == pdf["document_id"] and ld["first_page"] == 2 for ld in det["linked_documents"])
    # original download is an attachment (never rendered inline)
    r = admin.get(f"/api/projects/{pid}/documents/{pdf['document_id']}/original")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")


def test_assistant_grounded_extractive(admin, project):
    pid = project["id"]
    pdf = _process(admin, pid, "synthetic_harbor_audit_report.pdf")
    res = admin.ok(admin.post(f"/api/projects/{pid}/documents/ask", json={"question": "Who approved the large payments?"}))
    assert res["mode"] == "extractive" and res["label"] == "direct_evidence"
    assert "Jonathan Mercer approved" in res["answer"]
    cited = res["citations"][res["cited"][0] - 1]
    assert cited["document_id"] == pdf["document_id"] and cited["page"] == 2
    none = admin.ok(admin.post(f"/api/projects/{pid}/documents/ask", json={"question": "zebra quantum volcano"}))
    assert none["answer"] is None and none["label"] == "no_evidence"


def test_prompt_injection_document_is_flagged_not_followed(admin, project):
    pid = project["id"]
    res = _process(admin, pid, "synthetic_suspicious_note.txt")
    d = admin.ok(admin.get(f"/api/projects/{pid}/documents/{res['document_id']}"))
    assert d["metadata"]["injection_patterns_detected"] is True
    ans = admin.ok(admin.post(f"/api/projects/{pid}/documents/ask", json={"question": "What was the shipment content?"}))
    assert ans["warnings"] and "untrusted" in ans["warnings"][0]
    assert "dried fish" in ans["answer"]
    # the platform state is unchanged: users still exist, admin still works
    assert len(admin.ok(admin.get("/api/admin/users"))) == 1
