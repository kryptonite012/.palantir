"""Entity resolution, review, reversible merges, relationships and graph algorithms."""
import json

from conftest import ADMIN_PW, SAMPLE, load_demo


def _resolve(api, pid):
    job = api.ok(api.post(f"/api/projects/{pid}/entities/resolve", json={"entity_type": "person"}))
    assert job["status"] == "succeeded"
    return api.ok(api.get(f"/api/projects/{pid}/match-candidates"))["candidates"]


def _pair(c):
    return {c["entity_a"]["display_name"], c["entity_b"]["display_name"]}


def test_resolution_matches_ground_truth(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    truth = json.loads((SAMPLE / "expected_results.json").read_text())["entity_resolution"]
    cands = _resolve(admin, pid)
    strong = [_pair(c) for c in cands if c["band"] == "strong"]
    ambiguous = [_pair(c) for c in cands if c["band"] == "ambiguous"]
    for a, b in truth["expected_strong_matches"]:
        assert {a, b} in strong
    for a, b in truth["expected_ambiguous_matches"]:
        assert {a, b} in ambiguous
    assert not any("Gunnar Thorsen" in p for p in strong + ambiguous)
    assert not any(p == {"Rafael Ortiz"} for p in strong)
    c = next(c for c in cands if _pair(c) == {"Jon Mercer", "Jonathan Mercer"})
    ev = c["evidence"]
    assert "phone" in ev["matching_fields"] and "email" in ev["not_compared"]
    assert c["algorithm_version"] == "er-1.1" and ev["sources"]
    # running resolution again does not duplicate candidates
    assert admin.ok(admin.post(f"/api/projects/{pid}/entities/resolve", json={}))["result"]["candidates_created"] == 0


def test_merge_and_revert(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    cands = _resolve(admin, pid)
    c = next(c for c in cands if _pair(c) == {"Dr. Amelia Okafor", "Amelia Okafor"})
    survivor = next(e for e in (c["entity_a"], c["entity_b"]) if e["display_name"] == "Amelia Okafor")
    merged = next(e for e in (c["entity_a"], c["entity_b"]) if e["display_name"] != "Amelia Okafor")
    before = admin.ok(admin.get(f"/api/projects/{pid}/entities/{survivor['id']}"))
    res = admin.ok(admin.post(f"/api/projects/{pid}/match-candidates/{c['id']}/review",
                              json={"decision": "accept", "survivor_id": survivor["id"], "note": "same email"}))
    after = admin.ok(admin.get(f"/api/projects/{pid}/entities/{survivor['id']}"))
    assert len(after["source_records"]) == len(before["source_records"]) + 1
    assert "Dr. Amelia Okafor" in after["attributes"]["name"]
    m = admin.ok(admin.get(f"/api/projects/{pid}/entities/{merged['id']}"))
    assert m["status"] == "merged" and m["merged_into_id"] == survivor["id"]
    # reviewing twice is rejected
    assert admin.post(f"/api/projects/{pid}/match-candidates/{c['id']}/review", json={"decision": "accept"}).status_code == 409
    admin.ok(admin.post(f"/api/projects/{pid}/merges/{res['merge_id']}/revert"))
    restored = admin.ok(admin.get(f"/api/projects/{pid}/entities/{survivor['id']}"))
    assert restored["attributes"] == before["attributes"]
    assert len(restored["source_records"]) == len(before["source_records"])
    assert admin.ok(admin.get(f"/api/projects/{pid}/entities/{merged['id']}"))["status"] == "active"
    assert admin.post(f"/api/projects/{pid}/merges/{res['merge_id']}/revert").status_code == 409
    audit = admin.ok(admin.get("/api/admin/audit", params={"action": "entity."}))
    actions = {e["action"] for e in audit["events"]}
    assert {"entity.match_accepted", "entity.merge_reverted"} <= actions


def test_merge_reassigns_relationships(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    ents = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"q": "Mercer"}))["entities"]
    jon = next(e for e in ents if e["display_name"] == "Jon Mercer")
    jonathan = next(e for e in ents if e["display_name"] == "Jonathan Mercer")
    rels_before = len(admin.ok(admin.get(f"/api/projects/{pid}/entities/{jonathan['id']}"))["relationships"])
    # manual relationship on the duplicate
    org = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"q": "Saltmarsh"}))["entities"][0]
    admin.ok(admin.post(f"/api/projects/{pid}/relationships", json={
        "source_entity_id": jon["id"], "target_entity_id": org["id"], "rel_type": "associated_with",
        "justification": "visitor log shows meeting"}))
    assert admin.post(f"/api/projects/{pid}/entities/merge", json={"survivor_id": jonathan["id"], "merged_id": jon["id"]}).status_code == 422
    mg = admin.ok(admin.post(f"/api/projects/{pid}/entities/merge", json={"survivor_id": jonathan["id"], "merged_id": jon["id"],
                                                                        "note": "same phone number"}))
    det = admin.ok(admin.get(f"/api/projects/{pid}/entities/{jonathan['id']}"))
    assert len(det["relationships"]) == rels_before + 1
    manual = next(r for r in det["relationships"] if r["assertion"] == "manual")
    assert manual["assertion_label"] == "Manually asserted by analyst"
    admin.ok(admin.post(f"/api/projects/{pid}/merges/{mg['merge_id']}/revert"))
    assert len(admin.ok(admin.get(f"/api/projects/{pid}/entities/{jonathan['id']}"))["relationships"]) == rels_before


def test_reviewer_role_can_review_analyst_cannot(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    cands = _resolve(admin, pid)
    u = admin.create_user("viewer")
    admin.ok(admin.put(f"/api/projects/{pid}/members", json={"user_id": u["id"], "role": "analyst"}))
    an = admin.as_user(admin.login("viewer", ADMIN_PW))
    assert an.post(f"/api/projects/{pid}/match-candidates/{cands[0]['id']}/review", json={"decision": "reject"}).status_code == 403


def test_graph_neighborhood_and_algorithms(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    exp = json.loads((SAMPLE / "expected_results.json").read_text())["graph"]
    overview = admin.ok(admin.get(f"/api/projects/{pid}/graph", params={"limit": 10}))
    assert len(overview["nodes"]) == 10 and overview["truncated"] is True
    org = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"entity_type": "organization", "q": "Northwind"}))["entities"][0]
    nb = admin.ok(admin.get(f"/api/projects/{pid}/graph", params={"center": org["id"], "depth": 1, "rel_type": "works_for"}))
    assert len(nb["edges"]) == exp["works_for_relationships"] // exp["organizations"]
    assert all(e["assertion"] == "observed" for e in nb["edges"])
    comps = admin.ok(admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": "connected_components",
                                                                          "params": {"rel_types": ["works_for"]}}))
    # 8 org stars + 5 isolated contacts
    assert comps["result"]["count"] == 8 + 5
    pr = admin.ok(admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": "degree_centrality", "params": {"top": 3}}))
    assert len(pr["result"]["ranking"]) == 3 and pr["inputs"]["graph_state_sha256"]
    comm = admin.ok(admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": "communities"}))
    assert comm["result"]["count"] >= 1
    a = org["id"]
    b = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"entity_type": "organization", "q": "Bluefjord"}))["entities"][0]["id"]
    sp = admin.ok(admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": "shortest_path",
                                                                       "params": {"source": a, "target": b, "rel_types": ["works_for"]}}))
    assert sp["result"]["found"] is False  # orgs only connect through people via transactions, not works_for
    sp2 = admin.ok(admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": "shortest_path",
                                                                        "params": {"source": a, "target": b}}))
    assert sp2["result"]["found"] is True and sp2["result"]["length"] == 2
    # reproducible
    rep = admin.ok(admin.post(f"/api/projects/{pid}/analyses/{pr['id']}/reproduce"))
    assert rep["identical_result"] and rep["identical_inputs"]


def test_snapshot_and_export(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    nodes = [n["id"] for n in admin.ok(admin.get(f"/api/projects/{pid}/graph", params={"limit": 15}))["nodes"]]
    snap = admin.ok(admin.post(f"/api/projects/{pid}/graph/snapshots", json={"name": "core", "node_ids": nodes}))
    got = admin.ok(admin.get(f"/api/projects/{pid}/graph/snapshots/{snap['id']}"))
    assert len(got["nodes"]) == 15
    for fmt in ("graphml", "gexf", "json"):
        r = admin.post(f"/api/projects/{pid}/graph/export", params={"fmt": fmt}, json={"name": "x", "node_ids": nodes})
        assert r.status_code == 200 and len(r.content) > 100


def test_relationship_review_of_hypothesis(admin, project, app):
    pid = project["id"]
    load_demo(admin, pid)
    from project_atlas.database.models import Relationship

    ents = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"limit": 2}))["entities"]
    with app.state.ctx.sm() as db:
        r = Relationship(project_id=pid, source_entity_id=ents[0]["id"], target_entity_id=ents[1]["id"],
                         rel_type="associated_with", assertion="model_suggested", status="unverified", evidence={"quote": "x"},
                         created_by="model:test")
        db.add(r)
        db.commit()
        rid = r.id
    default = admin.ok(admin.get(f"/api/projects/{pid}/graph", params={"center": ents[0]["id"]}))
    assert rid not in {e["id"] for e in default["edges"]}
    incl = admin.ok(admin.get(f"/api/projects/{pid}/graph", params={"center": ents[0]["id"], "include_unverified": True}))
    edge = next(e for e in incl["edges"] if e["id"] == rid)
    assert edge["assertion_label"].startswith("Model-suggested")
    admin.ok(admin.patch(f"/api/projects/{pid}/relationships/{rid}", json={"status": "active", "note": "verified in doc"}))
    det = admin.ok(admin.get(f"/api/projects/{pid}/relationships/{rid}"))
    assert det["status"] == "active" and det["assertion"] == "model_suggested"  # provenance kept after verification


def test_all_graph_algorithms_run(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    for algo in ["degree_centrality", "betweenness_centrality", "pagerank", "connected_components", "communities"]:
        r = admin.ok(admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": algo}))
        assert r["result"]["sample_size"]["nodes"] > 0, algo
    bad = admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": "pagerank", "params": {"alpha": 2}})
    assert bad.status_code == 422
    assert admin.post(f"/api/projects/{pid}/graph/analyze", json={"algorithm": "nonsense"}).status_code == 422


def test_pagerank_matches_reference_values():
    import networkx as nx

    from project_atlas.graph.service import pagerank

    g = nx.DiGraph([("a", "b"), ("b", "c"), ("c", "a"), ("a", "c"), ("d", "c")])
    scores, _ = pagerank(g, 0.85)
    assert abs(sum(scores.values()) - 1) < 1e-9
    # reference values from networkx's pure-Python implementation (_pagerank_python, tol=1e-12)
    expected = {"a": 0.37252685, "b": 0.19582391, "c": 0.39414924, "d": 0.0375}
    for k, v in expected.items():
        assert abs(scores[k] - v) < 1e-6, (k, scores[k])
