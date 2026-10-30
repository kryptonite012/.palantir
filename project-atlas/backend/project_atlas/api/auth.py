"""Authentication: initial setup, login, sessions, MFA, password changes and recovery."""

from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from project_atlas.api.deps import Principal, aware, current_principal, get_ctx, get_db
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Conflict, Forbidden, RateLimited, Unauthorized, ValidationFailed
from project_atlas.database.models import PasswordResetToken, ProjectMember, User, UserSession, utcnow
from project_atlas.security import totp
from project_atlas.security.passwords import (
    DUMMY_HASH, WeakPasswordError, check_policy, hash_password, needs_rehash, new_token, token_digest, verify_password,
)
from project_atlas.security.rbac import ROLE_LABELS, global_permissions

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15
USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]{3,64}$"


class SetupRequest(BaseModel):
    setup_token: str
    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    password: str


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    totp: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class ResetRedeem(BaseModel):
    token: str
    new_password: str


class TotpCode(BaseModel):
    code: str


def user_view(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "display_name": u.display_name, "global_role": u.global_role,
        "global_role_label": ROLE_LABELS.get(u.global_role or "", None), "is_active": u.is_active,
        "mfa_enabled": u.mfa_enabled, "created_at": u.created_at,
    }


def _issue_session(db: Session, ctx: AtlasContext, user: User, client: str) -> tuple[str, UserSession]:
    token = new_token()
    now = utcnow()
    sess = UserSession(user_id=user.id, token_hash=token_digest(token), created_at=now, last_seen_at=now,
                       expires_at=now + timedelta(minutes=ctx.settings.session_ttl_minutes), client=client[:255])
    db.add(sess)
    db.commit()
    return token, sess


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    users = db.execute(select(func.count()).select_from(User)).scalar_one()
    if users == 0:
        ctx.ensure_setup_token()
    return {"needs_setup": users == 0, "setup_token_location": str(ctx.setup_token_path) if users == 0 else None}


@router.post("/setup")
def initial_setup(body: SetupRequest, request: Request, db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    if db.execute(select(func.count()).select_from(User)).scalar_one() > 0:
        raise Conflict("Initial administrator already exists")
    expected = ctx.ensure_setup_token() or ""
    if not hmac.compare_digest(expected, body.setup_token.strip()):
        ctx.audit.record("auth.setup", actor_id=None, actor_name=body.username, resource_type="user",
                         outcome="denied", details={"reason": "bad setup token"})
        raise Forbidden("Invalid setup token")
    try:
        check_policy(body.password, body.username)
    except WeakPasswordError as exc:
        raise ValidationFailed(str(exc)) from exc
    user = User(username=body.username, display_name=body.display_name, password_hash=hash_password(body.password),
                global_role="system_admin")
    db.add(user)
    db.commit()
    ctx.setup_token_path.unlink(missing_ok=True)
    ctx.audit.record("auth.setup", actor_id=user.id, actor_name=user.username, resource_type="user",
                     resource_id=user.id, details={"global_role": "system_admin"})
    token, sess = _issue_session(db, ctx, user, request.headers.get("user-agent", ""))
    return {"token": token, "expires_at": sess.expires_at, "user": user_view(user)}


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    ip = request.client.host if request.client else "local"
    if not ctx.login_limiter.hit(f"login:{ip}") or not ctx.login_limiter.hit(f"login-user:{body.username.lower()}"):
        ctx.audit.record("auth.login", actor_id=None, actor_name=body.username, resource_type="session",
                         outcome="denied", details={"reason": "rate_limited", "ip": ip})
        raise RateLimited("Too many login attempts; wait a minute and try again")
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    now = utcnow()

    def fail(reason: str):
        ctx.audit.record("auth.login", actor_id=user.id if user else None, actor_name=body.username,
                         resource_type="session", outcome="denied", details={"reason": reason, "ip": ip})
        raise Unauthorized("Invalid credentials")

    if user is None:
        verify_password(DUMMY_HASH, body.password)
        fail("unknown_user")
    assert user is not None
    if user.locked_until and aware(user.locked_until) > now:
        fail("locked")
    if not verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= LOCKOUT_THRESHOLD:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_logins = 0
        db.commit()
        fail("bad_password")
    if not user.is_active:
        fail("disabled")
    if user.mfa_enabled:
        if not body.totp:
            return {"mfa_required": True}
        if not totp.verify(user.mfa_secret or "", body.totp):
            fail("bad_totp")
    user.failed_logins = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    db.commit()
    token, sess = _issue_session(db, ctx, user, request.headers.get("user-agent", ""))
    ctx.audit.record("auth.login", actor_id=user.id, actor_name=user.username, resource_type="session",
                     resource_id=sess.id, details={"ip": ip})
    return {"token": token, "expires_at": sess.expires_at, "user": user_view(user)}


@router.post("/logout")
def logout(p: Principal = Depends(current_principal), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    sess = db.get(UserSession, p.session_id)
    if sess:
        sess.revoked_at = utcnow()
        db.commit()
    ctx.audit.record("auth.logout", actor_id=p.id, actor_name=p.name, resource_type="session", resource_id=p.session_id)
    return {"ok": True}


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    memberships = db.execute(select(ProjectMember).where(ProjectMember.user_id == p.id)).scalars().all()
    return {**user_view(p.user), "global_permissions": sorted(global_permissions(p.user.global_role)),
            "projects": [{"project_id": m.project_id, "role": m.role} for m in memberships]}


@router.post("/password")
def change_password(body: PasswordChange, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                    ctx: AtlasContext = Depends(get_ctx)):
    user = db.get(User, p.id)
    if not verify_password(user.password_hash, body.current_password):
        ctx.audit.record("auth.password_change", actor_id=p.id, actor_name=p.name, resource_type="user",
                         resource_id=p.id, outcome="denied")
        raise Unauthorized("Current password is incorrect")
    try:
        check_policy(body.new_password, user.username)
    except WeakPasswordError as exc:
        raise ValidationFailed(str(exc)) from exc
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.id != p.session_id,
                                         UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    db.commit()
    ctx.audit.record("auth.password_change", actor_id=p.id, actor_name=p.name, resource_type="user", resource_id=p.id)
    return {"ok": True, "other_sessions_revoked": True}


@router.post("/password-reset/redeem")
def redeem_reset(body: ResetRedeem, db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    """Account recovery: redeem a one-time token issued by a security/system administrator."""
    rec = db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_digest(body.token))).scalar_one_or_none()
    if rec is None or rec.used_at is not None or aware(rec.expires_at) <= utcnow():
        ctx.audit.record("auth.password_reset", actor_id=None, actor_name="anonymous", resource_type="user",
                         outcome="denied")
        raise Unauthorized("Reset token invalid or expired")
    user = db.get(User, rec.user_id)
    try:
        check_policy(body.new_password, user.username)
    except WeakPasswordError as exc:
        raise ValidationFailed(str(exc)) from exc
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    user.failed_logins = 0
    user.locked_until = None
    rec.used_at = utcnow()
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    db.commit()
    ctx.audit.record("auth.password_reset", actor_id=user.id, actor_name=user.username, resource_type="user",
                     resource_id=user.id)
    return {"ok": True}


@router.post("/mfa/enroll")
def mfa_enroll(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    user = db.get(User, p.id)
    if user.mfa_enabled:
        raise Conflict("MFA already enabled")
    user.mfa_secret = totp.new_secret()
    db.commit()
    return {"secret": user.mfa_secret, "provisioning_uri": totp.provisioning_uri(user.mfa_secret, user.username)}


@router.post("/mfa/activate")
def mfa_activate(body: TotpCode, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    user = db.get(User, p.id)
    if not user.mfa_secret or not totp.verify(user.mfa_secret, body.code):
        raise ValidationFailed("Invalid verification code")
    user.mfa_enabled = True
    db.commit()
    ctx.audit.record("auth.mfa_enabled", actor_id=p.id, actor_name=p.name, resource_type="user", resource_id=p.id)
    return {"mfa_enabled": True}


@router.post("/mfa/disable")
def mfa_disable(body: TotpCode, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                ctx: AtlasContext = Depends(get_ctx)):
    user = db.get(User, p.id)
    if not user.mfa_enabled or not totp.verify(user.mfa_secret or "", body.code):
        raise ValidationFailed("Invalid verification code")
    user.mfa_enabled = False
    user.mfa_secret = None
    db.commit()
    ctx.audit.record("auth.mfa_disabled", actor_id=p.id, actor_name=p.name, resource_type="user", resource_id=p.id)
    return {"mfa_enabled": False}


@router.get("/sessions")
def my_sessions(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.execute(select(UserSession).where(UserSession.user_id == p.id, UserSession.revoked_at.is_(None))
                      .order_by(UserSession.created_at.desc())).scalars().all()
    return [{"id": s.id, "created_at": s.created_at, "expires_at": s.expires_at, "client": s.client,
             "current": s.id == p.session_id} for s in rows if aware(s.expires_at) > utcnow()]


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                   ctx: AtlasContext = Depends(get_ctx)):
    sess = db.get(UserSession, session_id)
    if sess is None or (sess.user_id != p.id and "sessions.revoke" not in p.global_perms):
        raise Forbidden("Cannot revoke this session")
    sess.revoked_at = utcnow()
    db.commit()
    ctx.audit.record("auth.session_revoked", actor_id=p.id, actor_name=p.name, resource_type="session",
                     resource_id=session_id)
    return {"ok": True}
