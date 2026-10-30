"""Project isolation, roles, restricted datasets and field-level redaction."""
from conftest import ADMIN_PW, PEOPLE_CONFIG, SAMPLE, load_demo


def _member(admin, pid, username, role):
    u = admin.create_user(username)
    admin.ok(admin.put(f"/api/projects/{pid}/members", json={"user_id": u["id"], "role": role}))
    return admin.as_user(admin.login(username, ADMIN_PW))


def test_cross_project_access_denied(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    other = admin.ok(admin.post("/api/projects", json={"name": "Other"}))
    outsider = _member(admin, other["id"], "outsider", "project_admin")
    ds = admin.ok(admin.get(f"/api/projects/{pid}/datasets"))[0]
    # not a member: every project-scoped endpoint returns 404 (existence not revealed)
    for url in [f"/api/projects/{pid}", f"/api/projects/{pid}/datasets", f"/api/projects/{pid}/datasets/{ds['id']}/records",
                f"/api/projects/{pid}/entities", f"/api/projects/{pid}/graph", f"/api/projects/{pid}/timeline"]:
        assert outsider.get(url).status_code == 404, url
    # IDs from another project cannot be used through the outsider's own project either
    assert outsider.get(f"/api/projects/{other['id']}/datasets/{ds['id']}").status_code == 404
    # global search only covers own projects
    res = outsider.ok(outsider.get("/api/search", params={"q": "Okafor"}))
    assert res["total"] == 0
    denied = admin.ok(admin.get("/api/admin/audit", params={"action": "project.access", "outcome": "denied"}))
    assert denied["total"] >= 6


def test_read_only_role_limits(admin, project):
    pid = project["id"]
    ro = _member(admin, pid, "reader", "read_only")
    with open(SAMPLE / "synthetic_people.csv", "rb") as f:
        assert ro.post(f"/api/projects/{pid}/files", files={"file": ("p.csv", f)}).status_code == 403
    assert ro.post(f"/api/projects/{pid}/entities/resolve", json={}).status_code == 403
    assert ro.post(f"/api/projects/{pid}/sql", json={"sql": "select 1"}).status_code == 403
    assert ro.post(f"/api/projects/{pid}/investigations", json={"title": "x"}).status_code == 403
    assert ro.get(f"/api/projects/{pid}/datasets").status_code == 200


def test_sensitive_fields_redacted_for_analyst(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    an = _member(admin, pid, "analyst", "analyst")
    ds = next(d for d in admin.ok(admin.get(f"/api/projects/{pid}/datasets")) if d["name"] == "people")
    recs = an.ok(an.get(f"/api/projects/{pid}/datasets/{ds['id']}/records", params={"limit": 5}))
    assert set(recs["redacted_fields"]) == {"email", "phone", "date_of_birth"}
    assert all(r["normalized"]["email"] in ("[restricted]", None) for r in recs["records"])
    assert all(r["raw"]["email"] in ("[restricted]", None, "") for r in recs["records"])
    full = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{ds['id']}/records", params={"limit": 5}))
    assert "@" in full["records"][0]["normalized"]["email"]
    # entities: sensitive attribute values hidden
    ents = an.ok(an.get(f"/api/projects/{pid}/entities", params={"entity_type": "person", "q": "Okafor"}))
    e = ents["entities"][0]
    assert e["attributes"]["email"] == ["[restricted]"]
    # SQL cannot read sensitive columns either
    r = an.post(f"/api/projects/{pid}/sql", json={"sql": "select email from people"})
    assert r.status_code == 422
    # search index never contains sensitive values
    hits = an.ok(an.get("/api/search", params={"q": "example.invalid", "project_id": pid}))
    assert hits["total"] == 0


def test_restricted_dataset_hidden_from_analyst(admin, project):
    pid = project["id"]
    admin.import_file(pid, SAMPLE / "synthetic_people.csv", {**PEOPLE_CONFIG, "access_policy": "restricted"})
    an = _member(admin, pid, "analyst2", "analyst")
    de = _member(admin, pid, "engineer", "data_engineer")
    assert an.ok(an.get(f"/api/projects/{pid}/datasets")) == []
    assert len(de.ok(de.get(f"/api/projects/{pid}/datasets"))) == 1
    ds = admin.ok(admin.get(f"/api/projects/{pid}/datasets"))[0]
    assert an.get(f"/api/projects/{pid}/datasets/{ds['id']}").status_code == 404
    assert an.ok(an.get("/api/search", params={"q": "Okafor", "project_id": pid, "type": "dataset_record"}))["total"] == 0
    assert de.ok(de.get("/api/search", params={"q": "Okafor", "project_id": pid, "type": "dataset_record"}))["total"] >= 1


def test_member_management_rules(admin, project):
    pid = project["id"]
    analyst = _member(admin, pid, "ana", "analyst")
    me = admin.ok(admin.get("/api/auth/me"))
    # analyst cannot change roles
    assert analyst.put(f"/api/projects/{pid}/members", json={"user_id": me["id"], "role": "read_only"}).status_code == 403
    # last project admin cannot be demoted
    assert admin.put(f"/api/projects/{pid}/members", json={"user_id": me["id"], "role": "analyst"}).status_code == 409
