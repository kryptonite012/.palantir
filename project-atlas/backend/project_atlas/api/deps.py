"""Request dependencies: context, database session, authentication, authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Forbidden, NotFound, RateLimited, Unauthorized
from project_atlas.database.models import Project, ProjectMember, User, UserSession, utcnow
from project_atlas.security.passwords import token_digest
from project_atlas.security.rbac import global_permissions, project_permissions


def get_ctx(request: Request) -> AtlasContext:
    return request.app.state.ctx


def get_db(ctx: AtlasContext = Depends(get_ctx)) -> Iterator[Session]:
    with ctx.sm() as s:
        yield s


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Principal:
    user: User
    session_id: str
    global_perms: set[str] = field(default_factory=set)
    ip: str = ""

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def name(self) -> str:
        return self.user.username

    def require_global(self, perm: str) -> None:
        if perm not in self.global_perms:
            raise Forbidden(f"Missing permission: {perm}")


def current_principal(request: Request, ctx: AtlasContext = Depends(get_ctx), db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.query_params.get("access_token", "")
    if not token:
        raise Unauthorized("Authentication required")
    sess = db.execute(select(UserSession).where(UserSession.token_hash == token_digest(token))).scalar_one_or_none()
    now = utcnow()
    if sess is None or sess.revoked_at is not None or aware(sess.expires_at) <= now:
        raise Unauthorized("Session expired or revoked")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account disabled")
    ip = request.client.host if request.client else "local"
    if not ctx.api_limiter.hit(f"api:{user.id}"):
        raise RateLimited("Too many requests")
    # Sliding expiration, capped at the configured TTL from last activity.
    if (now - aware(sess.last_seen_at)) > timedelta(minutes=1):
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(minutes=ctx.settings.session_ttl_minutes)
        db.commit()
    return Principal(user=user, session_id=sess.id, global_perms=global_permissions(user.global_role), ip=ip)


@dataclass
class ProjectAccess:
    principal: Principal
    project: Project
    role: str
    perms: set[str]

    @property
    def project_id(self) -> str:
        return self.project.id

    def can(self, perm: str) -> bool:
        return perm in self.perms

    def require(self, perm: str) -> None:
        if perm not in self.perms:
            raise Forbidden(f"Your project role ({self.role}) lacks permission: {perm}")


def resolve_project_access(db: Session, principal: Principal, project_id: str) -> ProjectAccess:
    project = db.get(Project, project_id)
    member = None
    if project is not None:
        member = db.execute(
            select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == principal.id)
        ).scalar_one_or_none()
    if project is None or member is None:
        # Same response for missing and unauthorized projects: do not reveal existence.
        raise NotFound("Project not found")
    return ProjectAccess(principal, project, member.role, project_permissions(member.role))


def project_access(project_id: str, request: Request, principal: Principal = Depends(current_principal),
                   db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)) -> ProjectAccess:
    try:
        return resolve_project_access(db, principal, project_id)
    except NotFound:
        ctx.audit.record("project.access", actor_id=principal.id, actor_name=principal.name, resource_type="project",
                         resource_id=project_id, outcome="denied", details={"path": request.url.path})
        raise
