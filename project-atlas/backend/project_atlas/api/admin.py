"""Administration: users, audit center, system status, offline verification, backups."""

from __future__ import annotations

import csv
import importlib.metadata
import io
import platform
import shutil
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from project_atlas import APP_NAME, __version__
from project_atlas.api.auth import USERNAME_PATTERN, user_view
from project_atlas.api.deps import Principal, current_principal, get_ctx, get_db
from project_atlas.backup import service as backup
from project_atlas.core.config import is_local_host
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from project_atlas.core.netguard import guard
from project_atlas.database.models import AuditEvent, Job, PasswordResetToken, ProjectMember, User, UserSession, utcnow
from project_atlas.database.session import current_revision
from project_atlas.security.passwords import WeakPasswordError, check_policy, hash_password, new_token, token_digest

router = APIRouter(prefix="/api/admin", tags=["administration"])
system_router = APIRouter(prefix="/api/system", tags=["system"])


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    password: str
    global_role: str | None = Field(default=None, pattern=r"^(system_admin|security_admin)$")


class UserPatch(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    reset_mfa: bool | None = None
    global_role: str | None = Field(default=None, pattern=r"^(system_admin|security_admin|none)$")


class BackupCreate(BaseModel):
    passphrase: str | None = None


class BackupAction(BaseModel):
    filename: str
    passphrase: str | None = None
    confirm: bool = False


def _can_manage_users(p: Principal) -> None:
    if "admin.users" not in p.global_perms and "admin.users.security" not in p.global_perms:
        raise Forbidden("User administration requires a system or security administrator")


@router.get("/users")
def list_users(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    _can_manage_users(p)
    users = db.execute(select(User).order_by(User.username)).scalars().all()
    counts = dict(db.execute(select(ProjectMember.user_id, func.count()).group_by(ProjectMember.user_id)).all())
    return [{**user_view(u), "projects": counts.get(u.id, 0), "locked": bool(u.locked_until and u.locked_until.replace(tzinfo=None) > utcnow().replace(tzinfo=None))}
            for u in users]


@router.get("/users/directory")
def directory(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    """Minimal user listing so project admins can add members."""
    return [{"id": u.id, "username": u.username, "display_name": u.display_name}
            for u in db.execute(select(User).where(User.is_active.is_(True)).order_by(User.username)).scalars()]


@router.post("/users")
def create_user(body: UserCreate, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("admin.users")
    if db.execute(select(User).where(User.username == body.username)).scalar_one_or_none():
        raise Conflict("Username already exists")
    try:
        check_policy(body.password, body.username)
    except WeakPasswordError as exc:
        raise ValidationFailed(str(exc)) from exc
    u = User(username=body.username, display_name=body.display_name, password_hash=hash_password(body.password),
             global_role=body.global_role)
    db.add(u)
    db.commit()
    ctx.audit.record("admin.user_created", actor_id=p.id, actor_name=p.name, resource_type="user", resource_id=u.id,
                     details={"username": u.username, "global_role": u.global_role})
    return user_view(u)


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
               ctx: AtlasContext = Depends(get_ctx)):
    _can_manage_users(p)
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("User not found")
    changes = body.model_dump(exclude_none=True)
    if "global_role" in changes:
        p.require_global("admin.users")
        if u.id == p.id:
            raise Forbidden("You cannot change your own global role")
        u.global_role = None if changes["global_role"] == "none" else changes["global_role"]
    if "is_active" in changes:
        if u.id == p.id and not changes["is_active"]:
            raise Forbidden("You cannot disable your own account")
        u.is_active = changes["is_active"]
        if not u.is_active:
            db.execute(update(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    if "display_name" in changes:
        u.display_name = changes["display_name"]
    if changes.get("reset_mfa"):
        # Recovery for a lost authenticator: the user must re-enrol; existing sessions are revoked.
        u.mfa_enabled = False
        u.mfa_secret = None
        db.execute(update(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    remaining_admins = db.execute(select(func.count()).select_from(User).where(User.global_role == "system_admin",
                                                                              User.is_active.is_(True))).scalar_one()
    if remaining_admins == 0:
        db.rollback()
        raise Conflict("At least one active system administrator is required")
    db.commit()
    ctx.audit.record("admin.user_updated", actor_id=p.id, actor_name=p.name, resource_type="user", resource_id=u.id, details=changes)
    return user_view(u)


@router.post("/users/{user_id}/reset-token")
def issue_reset(user_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                ctx: AtlasContext = Depends(get_ctx)):
    """Secure offline account recovery: an administrator issues a one-time, 1-hour token delivered out-of-band."""
    _can_manage_users(p)
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("User not found")
    token = new_token()
    db.add(PasswordResetToken(user_id=u.id, token_hash=token_digest(token), issued_by=p.id,
                              expires_at=utcnow() + timedelta(hours=1)))
    db.commit()
    ctx.audit.record("admin.reset_token_issued", actor_id=p.id, actor_name=p.name, resource_type="user", resource_id=u.id)
    return {"token": token, "expires_in_minutes": 60,
            "note": "Deliver this token to the user through a trusted channel. It is shown once and stored only as a hash."}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_all(user_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
               ctx: AtlasContext = Depends(get_ctx)):
    if "sessions.revoke" not in p.global_perms and "admin.users" not in p.global_perms:
        raise Forbidden("Missing permission: sessions.revoke")
    n = db.execute(update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
                   .values(revoked_at=utcnow())).rowcount
    db.commit()
    ctx.audit.record("admin.sessions_revoked", actor_id=p.id, actor_name=p.name, resource_type="user", resource_id=user_id,
                     details={"count": n})
    return {"revoked": n}


# --------------------------------------------------------------------------- audit


def _audit_query(action, actor, project_id, outcome, since, until):
    q = select(AuditEvent)
    if action:
        q = q.where(AuditEvent.action.like(f"{action.replace('%', '')}%"))
    if actor:
        q = q.where(AuditEvent.actor_name == actor)
    if project_id:
        q = q.where(AuditEvent.project_id == project_id)
    if outcome:
        q = q.where(AuditEvent.outcome == outcome)
    if since:
        q = q.where(AuditEvent.ts >= since)
    if until:
        q = q.where(AuditEvent.ts <= until)
    return q


def audit_view(e: AuditEvent) -> dict:
    return {"seq": e.seq, "event_id": e.event_id, "ts": e.ts, "actor_id": e.actor_id, "actor_name": e.actor_name,
            "action": e.action, "resource_type": e.resource_type, "resource_id": e.resource_id, "project_id": e.project_id,
            "outcome": e.outcome, "details": e.details, "hash": e.hash, "prev_hash": e.prev_hash}


def _audit_access(p: Principal, db: Session, project_id: str | None) -> None:
    if "audit.read" in p.global_perms:
        return
    if project_id:
        m = db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == p.id)).scalar_one_or_none()
        if m and m.role == "project_admin":
            return
    raise Forbidden("Audit access requires a system/security administrator or project administrator (project scope)")


@router.get("/audit")
def list_audit(action: str | None = None, actor: str | None = None, project_id: str | None = None, outcome: str | None = None,
               since: datetime | None = None, until: datetime | None = None, limit: int = 100, offset: int = 0,
               p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    _audit_access(p, db, project_id)
    q = _audit_query(action, actor, project_id, outcome, since, until)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(AuditEvent.seq.desc()).limit(min(limit, 500)).offset(offset)).scalars()
    return {"total": total, "events": [audit_view(e) for e in rows]}


@router.get("/audit/export")
def export_audit(project_id: str | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    _audit_access(p, db, project_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "event_id", "ts", "actor", "action", "resource_type", "resource_id", "project_id", "outcome", "hash", "prev_hash"])
    for e in db.execute(_audit_query(None, None, project_id, None, None, None).order_by(AuditEvent.seq)).scalars():
        w.writerow([e.seq, e.event_id, e.ts, e.actor_name, e.action, e.resource_type, e.resource_id, e.project_id, e.outcome, e.hash, e.prev_hash])
    ctx.audit.record("audit.export", actor_id=p.id, actor_name=p.name, resource_type="audit", project_id=project_id)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="atlas-audit.csv"'})


@router.post("/audit/verify")
def verify_audit(p: Principal = Depends(current_principal), ctx: AtlasContext = Depends(get_ctx)):
    if "audit.read" not in p.global_perms:
        raise Forbidden("Missing permission: audit.read")
    res = ctx.audit.verify()
    ctx.audit.record("audit.verify", actor_id=p.id, actor_name=p.name, resource_type="audit",
                     outcome="success" if res["valid"] else "failure", details={"valid": res["valid"], "events": res["events_checked"]})
    return res


@router.post("/audit/checkpoint")
def checkpoint(p: Principal = Depends(current_principal), ctx: AtlasContext = Depends(get_ctx)):
    if "audit.read" not in p.global_perms:
        raise Forbidden("Missing permission: audit.read")
    return ctx.audit.checkpoint()


# --------------------------------------------------------------------------- backups


@router.get("/backups")
def backups(p: Principal = Depends(current_principal), ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("admin.backup")
    return backup.list_backups(ctx)


@router.post("/backups")
def make_backup(body: BackupCreate, p: Principal = Depends(current_principal), ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("admin.backup")
    res = backup.create_backup(ctx, user_id=p.id, passphrase=body.passphrase, kind="manual")
    ctx.audit.record("backup.create", actor_id=p.id, actor_name=p.name, resource_type="backup", resource_id=res["filename"],
                     details={"encrypted": res["encrypted"], "sha256": res["sha256"]})
    return res


@router.post("/backups/verify")
def verify(body: BackupAction, p: Principal = Depends(current_principal), ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("admin.backup")
    res = backup.verify_backup(ctx, body.filename, body.passphrase)
    ctx.audit.record("backup.verify", actor_id=p.id, actor_name=p.name, resource_type="backup", resource_id=body.filename,
                     outcome="success" if res["valid"] else "failure")
    return res


@router.post("/backups/restore")
def restore(body: BackupAction, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
            ctx: AtlasContext = Depends(get_ctx)):
    """Preview (confirm=false) shows the manifest and verification; confirm=true performs the restore."""
    p.require_global("admin.restore")
    if not body.confirm:
        return {"preview": True, **backup.verify_backup(ctx, body.filename, body.passphrase)}
    running = db.execute(select(func.count()).select_from(Job).where(Job.status == "running")).scalar_one()
    if running:
        raise Conflict(f"{running} job(s) are running; wait for them to finish before restoring")
    actor = (p.id, p.name)
    db.close()
    res = backup.restore_backup(ctx, body.filename, body.passphrase)
    ctx.audit.record("backup.restore", actor_id=actor[0], actor_name=actor[1], resource_type="backup", resource_id=body.filename,
                     details={"count_mismatches": res["count_mismatches"]})
    return res


# --------------------------------------------------------------------------- system


def _pkg_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


@system_router.get("/status")
def status(p: Principal = Depends(current_principal), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    s = ctx.settings
    usage = shutil.disk_usage(s.storage_dir)
    jobs = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    try:
        import psutil  # optional

        mem = psutil.virtual_memory()._asdict()
    except ImportError:
        mem = None
    return {"app": APP_NAME, "version": __version__, "env": s.env, "offline_mode": s.offline_mode,
            "database": "sqlite" if s.is_sqlite else "postgresql", "schema_revision": current_revision(ctx.engine),
            "storage_dir": str(s.storage_dir.resolve()), "backup_dir": str(s.backup_dir.resolve()),
            "disk": {"total": usage.total, "used": usage.used, "free": usage.free}, "memory": mem, "jobs": jobs,
            "python": platform.python_version(), "platform": platform.platform(),
            "ai": {"enabled": s.ai_enabled, "base_url": s.ai_base_url or None}}


@system_router.get("/offline-check")
def offline_check(p: Principal = Depends(current_principal), ctx: AtlasContext = Depends(get_ctx)):
    """Verification mode: reports the configuration and runtime evidence relevant to offline operation."""
    from urllib.parse import urlparse

    s = ctx.settings
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("offline_mode_enabled", s.offline_mode, f"ATLAS_OFFLINE_MODE={s.offline_mode}")
    add("telemetry_disabled", not s.telemetry_enabled, "No telemetry is implemented; setting must remain false")
    add("bind_address_local", is_local_host(s.host) or s.allow_lan, f"ATLAS_HOST={s.host} (LAN allowed: {s.allow_lan})")
    ai_host = urlparse(s.ai_base_url).hostname if s.ai_base_url else None
    add("ai_endpoint_local", ai_host is None or is_local_host(ai_host), f"AI endpoint: {s.ai_base_url or 'not configured'}")
    rep = guard.report()
    add("network_guard_installed", rep["installed"], "Outbound connections from the Atlas process are restricted to loopback/private ranges")
    add("no_blocked_external_attempts", rep["blocked_count"] == 0,
        f"{rep['blocked_count']} blocked external connection attempt(s) since start")
    probe = guard.probe()
    add("guard_live_probe", probe.startswith("blocked"), probe)
    deps = {n: _pkg_version(n) for n in ["fastapi", "sqlalchemy", "alembic", "duckdb", "pyarrow", "pandas", "networkx",
                                         "rapidfuzz", "argon2-cffi", "reportlab", "openpyxl", "pypdf", "python-docx"]}
    add("dependencies_present", all(deps.values()), deps)
    from project_atlas.documents.text import ocr_available

    add("ocr_engine_available", ocr_available(), "tesseract + pdftoppm on PATH (optional)")
    frontend = s.frontend_dist or None
    return {"checks": checks, "all_required_ok": all(c["ok"] for c in checks if c["check"] != "ocr_engine_available"),
            "network_guard": guard.report(), "frontend_dist": str(frontend) if frontend else None,
            "limitations": ["The guard covers only the Atlas Python process; OS-level firewalling or a physical air gap is "
                            "required for air-gap assurance.",
                            "This check cannot detect connections made by other software on the machine."]}


# --------------------------------------------------------------------------- retention


@router.get("/retention")
def retention_review(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    p.require_global("admin.settings")
    from project_atlas.retention import POLICY_DAYS, review

    return {**review(db), "policies": POLICY_DAYS}


@router.post("/retention/apply")
def retention_apply(confirm: bool = False, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                    ctx: AtlasContext = Depends(get_ctx)):
    """Purge superseded dataset versions past retention and notify owners about expired current versions."""
    p.require_global("admin.settings")
    if not confirm:
        raise ValidationFailed("Retention purges data permanently; pass confirm=true", details={"requires_confirmation": True})
    from project_atlas.retention import apply_retention

    res = apply_retention(ctx, db, actor_id=p.id)
    ctx.audit.record("retention.apply", actor_id=p.id, actor_name=p.name, resource_type="retention",
                     details={k: res[k] for k in ("purged_versions", "purged_records", "review_required")})
    return res
