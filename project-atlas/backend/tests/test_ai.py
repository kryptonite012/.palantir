"""Optional local AI with a mock Ollama-compatible runtime (no real model required)."""
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import ADMIN_PW, SAMPLE, Api, load_demo, make_settings
from project_atlas.ai import service as ai
from project_atlas.main import create_app

STATE = {"generate": None}


def _vec(text: str, dims: int = 32):
    v = [0.0] * dims
    for w in text.lower().split():
        v[int(hashlib.md5(w.strip(".,").encode()).hexdigest(), 16) % dims] += 1.0
    return v


def handler(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "127.0.0.1"  # never anything but the local runtime
    if request.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "atlas-chat:latest"}, {"name": "atlas-embed:latest"}]})
    body = json.loads(request.content)
    if request.url.path == "/api/embeddings":
        return httpx.Response(200, json={"embedding": _vec(body["prompt"])})
    if request.url.path == "/api/generate":
        fn = STATE["generate"]
        return httpx.Response(200, json={"response": fn(body) if fn else "INSUFFICIENT EVIDENCE"})
    return httpx.Response(404)


@pytest.fixture
def ai_api(tmp_path):
    ai.set_transport(httpx.MockTransport(handler))
    app = create_app(make_settings(tmp_path, ATLAS_AI_ENABLED="true", ATLAS_AI_BASE_URL="http://127.0.0.1:11434"))
    with TestClient(app) as c:
        tok = app.state.ctx.ensure_setup_token()
        t = c.post("/api/auth/setup", json={"setup_token": tok, "username": "admin", "display_name": "A", "password": ADMIN_PW}).json()["token"]
        api = Api(c, t)
        for name, kind in (("atlas-chat", "chat"), ("atlas-embed", "embedding")):
            m = api.ok(api.post("/api/ai/models", json={"name": name, "version": "1", "kind": kind, "runtime_model_name": name,
                                                        "license": "test-only", "quantization": "q4"}))
            assert api.ok(api.post(f"/api/ai/models/{m['id']}/check"))["health"] == "healthy"
        yield api
    ai.set_transport(None)
    app.state.ctx.dispose()


def test_status_and_registry(ai_api):
    st = ai_api.ok(ai_api.get("/api/ai/status"))
    assert st["available"] and len(st["models"]) == 2
    bad = ai_api.post("/api/ai/models", json={"name": "x", "version": "1", "kind": "chat", "runtime_model_name": "x",
                                              "file_path": "/etc/passwd"})
    assert bad.status_code == 422


def test_generative_answer_requires_valid_citations(ai_api):
    pid = ai_api.ok(ai_api.post("/api/projects", json={"name": "AI"}))["id"]
    f = ai_api.upload(pid, SAMPLE / "synthetic_harbor_audit_report.pdf")
    ai_api.ok(ai_api.post(f"/api/projects/{pid}/documents", json={"file_id": f["id"]}))
    STATE["generate"] = lambda b: "Jonathan Mercer approved both large payments [1]."
    r = ai_api.ok(ai_api.post(f"/api/projects/{pid}/documents/ask", json={"question": "Who approved the large payments?"}))
    assert r["mode"] == "generative" and r["label"] == "model_generated_grounded" and r["cited"] == [1]
    assert "Verify" in r["uncertainty"]
    STATE["generate"] = lambda b: "It was definitely the CEO."  # no citations -> withheld
    r2 = ai_api.ok(ai_api.post(f"/api/projects/{pid}/documents/ask", json={"question": "Who approved the large payments?"}))
    assert r2["answer"] is None and r2["label"] == "insufficient_evidence"
    STATE["generate"] = lambda b: "The answer is in passage [9]."  # citation to a passage that doesn't exist
    r3 = ai_api.ok(ai_api.post(f"/api/projects/{pid}/documents/ask", json={"question": "Who approved the large payments?"}))
    assert r3["answer"] is None
    # system prompt marks passages untrusted
    seen = {}
    STATE["generate"] = lambda b: seen.update(b) or "INSUFFICIENT EVIDENCE"
    ai_api.ok(ai_api.post(f"/api/projects/{pid}/documents/ask", json={"question": "payments approved"}))
    assert "untrusted" in seen["system"] and "<passage" in seen["prompt"]


def test_sql_draft_validated_not_executed(ai_api):
    pid = ai_api.ok(ai_api.post("/api/projects", json={"name": "AI2"}))["id"]
    load_demo(ai_api, pid)
    STATE["generate"] = lambda b: "SELECT city, count(*) FROM people GROUP BY city"
    d = ai_api.ok(ai_api.post(f"/api/projects/{pid}/ai/sql-draft", json={"question": "people per city"}))
    assert d["valid"] and d["executed"] is False and d["label"] == "model_suggestion_unverified"
    STATE["generate"] = lambda b: "DROP TABLE people"
    d2 = ai_api.ok(ai_api.post(f"/api/projects/{pid}/ai/sql-draft", json={"question": "remove everything"}))
    assert d2["valid"] is False and "SELECT" in d2["validation_error"]
    assert ai_api.ok(ai_api.post(f"/api/projects/{pid}/sql", json={"sql": "select count(*) from people"}))["rows"] == [[33]]


def test_relationship_hypotheses_are_unverified(ai_api):
    pid = ai_api.ok(ai_api.post("/api/projects", json={"name": "AI3"}))["id"]
    load_demo(ai_api, pid)
    f = ai_api.upload(pid, SAMPLE / "synthetic_memo_cold_storage.txt")
    doc = ai_api.ok(ai_api.post(f"/api/projects/{pid}/documents", json={"file_id": f["id"]}))["result"]["document_id"]
    STATE["generate"] = lambda b: json.dumps([{"source": "Tomas Berg", "target": "Bluefjord Freight AS", "rel_type": "associated_with",
                                               "quote": "Ingrid Halvorsen of Bluefjord Freight AS met Tomas Berg"}])
    res = ai_api.ok(ai_api.post(f"/api/projects/{pid}/ai/documents/{doc}/relationship-hypotheses"))
    assert len(res["created"]) == 1
    rel = ai_api.ok(ai_api.get(f"/api/projects/{pid}/relationships/{res['created'][0]}"))
    assert rel["assertion"] == "model_suggested" and rel["status"] == "unverified"
    assert rel["evidence"]["quote_found_in_document"] is True


def test_embeddings_and_semantic_search(ai_api):
    pid = ai_api.ok(ai_api.post("/api/projects", json={"name": "AI4"}))["id"]
    for name in ("synthetic_memo_cold_storage.txt", "synthetic_shipment_email.eml"):
        f = ai_api.upload(pid, SAMPLE / name)
        ai_api.ok(ai_api.post(f"/api/projects/{pid}/documents", json={"file_id": f["id"]}))
    job = ai_api.ok(ai_api.post(f"/api/projects/{pid}/ai/embeddings"))
    assert job["status"] == "succeeded" and job["result"]["embedded"] >= 2
    res = ai_api.ok(ai_api.get(f"/api/projects/{pid}/ai/semantic-search", params={"q": "temperature logs containers inspection"}))
    assert res["results"][0]["title"].startswith("synthetic_memo")


def test_ai_disabled_everything_else_works(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    st = admin.ok(admin.get("/api/ai/status"))
    assert st["enabled"] is False and st["available"] is False
    r = admin.post(f"/api/projects/{pid}/ai/sql-draft", json={"question": "count people"})
    assert r.status_code == 503
    f = admin.upload(pid, SAMPLE / "synthetic_harbor_audit_report.pdf")
    admin.ok(admin.post(f"/api/projects/{pid}/documents", json={"file_id": f["id"]}))
    ans = admin.ok(admin.post(f"/api/projects/{pid}/documents/ask", json={"question": "Who approved payments?"}))
    assert ans["mode"] == "extractive"
