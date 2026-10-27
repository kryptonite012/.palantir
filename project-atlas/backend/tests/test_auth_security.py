"""Authentication, sessions, MFA, lockout, recovery and RBAC."""
from conftest import ADMIN_PW, Api

from project_atlas.security import totp


def test_setup_requires_token_and_only_once(client, app):
    assert client.get("/api/auth/setup-status").json()["needs_setup"] is True
    bad = client.post("/api/auth/setup", json={"setup_token": "wrong", "username": "admin", "display_name": "A",
                                              "password": ADMIN_PW})
    assert bad.status_code == 403
    token = app.state.ctx.ensure_setup_token()
    weak = client.post("/api/auth/setup", json={"setup_token": token, "username": "admin", "display_name": "A",
                                               "password": "short"})
    assert weak.status_code == 422
    ok = client.post("/api/auth/setup", json={"setup_token": token, "username": "admin", "display_name": "A",
                                             "password": ADMIN_PW})
    assert ok.status_code == 200
    again = client.post("/api/auth/setup", json={"setup_token": token, "username": "second", "display_name": "B",
                                                "password": ADMIN_PW})
    assert again.status_code == 409
    assert not app.state.ctx.setup_token_path.exists()


def test_unauthenticated_requests_rejected(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_login_lockout_and_audit(admin):
    admin.create_user("analyst1")
    for _ in range(5):
        r = admin.c.post("/api/auth/login", json={"username": "analyst1", "password": "wrong-password-1A!"})
        assert r.status_code == 401
    # locked now, even with the correct password
    r = admin.c.post("/api/auth/login", json={"username": "analyst1", "password": ADMIN_PW})
    assert r.status_code == 401
    events = admin.ok(admin.get("/api/admin/audit", params={"action": "auth.login", "outcome": "denied"}))
    assert events["total"] >= 6
    assert "wrong-password-1A!" not in str(events) and ADMIN_PW not in str(events)


def test_unknown_user_and_bad_password_same_response(admin):
    a = admin.c.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    b = admin.c.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_logout_revokes_session(admin):
    tok = admin.login("admin", ADMIN_PW)
    api = admin.as_user(tok)
    assert api.get("/api/auth/me").status_code == 200
    api.ok(api.post("/api/auth/logout"))
    assert api.get("/api/auth/me").status_code == 401


def test_password_change_revokes_other_sessions(admin):
    other = admin.as_user(admin.login("admin", ADMIN_PW))
    new_pw = "Another-Strong-Pw9!"
    admin.ok(admin.post("/api/auth/password", json={"current_password": ADMIN_PW, "new_password": new_pw}))
    assert other.get("/api/auth/me").status_code == 401
    assert admin.get("/api/auth/me").status_code == 200


def test_mfa_flow(admin):
    enroll = admin.ok(admin.post("/api/auth/mfa/enroll"))
    secret = enroll["secret"]
    assert admin.post("/api/auth/mfa/activate", json={"code": "000000"}).status_code == 422
    admin.ok(admin.post("/api/auth/mfa/activate", json={"code": totp.current_code(secret)}))
    step1 = admin.ok(admin.c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}))
    assert step1 == {"mfa_required": True}
    bad = admin.c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW, "totp": "123456"})
    assert bad.status_code == 401
    good = admin.c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW,
                                                 "totp": totp.current_code(secret)})
    assert good.status_code == 200 and "token" in good.json()


def test_reset_token_recovery(admin):
    u = admin.create_user("bob")
    tok = admin.ok(admin.post(f"/api/admin/users/{u['id']}/reset-token"))["token"]
    new_pw = "Recovered-Passw0rd#"
    admin.ok(admin.c.post("/api/auth/password-reset/redeem", json={"token": tok, "new_password": new_pw}))
    assert admin.c.post("/api/auth/password-reset/redeem", json={"token": tok, "new_password": new_pw}).status_code == 401
    assert admin.login("bob", new_pw)


def test_non_admin_cannot_administer(admin):
    admin.create_user("mallory")
    m = admin.as_user(admin.login("mallory", ADMIN_PW))
    assert m.get("/api/admin/users").status_code == 403
    assert m.post("/api/admin/users", json={"username": "evil", "display_name": "E", "password": ADMIN_PW,
                                            "global_role": "system_admin"}).status_code == 403
    assert m.post("/api/projects", json={"name": "x"}).status_code == 403
    assert m.get("/api/admin/audit").status_code == 403
    assert m.post("/api/admin/backups", json={}).status_code == 403
    # privilege escalation via self-patch is impossible
    me = m.ok(m.get("/api/auth/me"))
    assert m.patch(f"/api/admin/users/{me['id']}", json={"global_role": "system_admin"}).status_code == 403


def test_last_system_admin_cannot_be_removed(admin):
    me = admin.ok(admin.get("/api/auth/me"))
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": False}).status_code == 403
    sec = admin.create_user("sec", role="security_admin")
    s = admin.as_user(admin.login("sec", ADMIN_PW))
    assert s.patch(f"/api/admin/users/{me['id']}", json={"global_role": "none"}).status_code == 403


def test_disabled_user_sessions_revoked(admin):
    u = admin.create_user("carol")
    c = admin.as_user(admin.login("carol", ADMIN_PW))
    admin.ok(admin.patch(f"/api/admin/users/{u['id']}", json={"is_active": False}))
    assert c.get("/api/auth/me").status_code == 401


def test_security_headers(client):
    r = client.get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
