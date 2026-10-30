"""Application context: settings, database, audit log, job runner, limiters."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from project_atlas.audit.service import AuditLog
from project_atlas.core.config import Settings
from project_atlas.core.jobs import JobRunner
from project_atlas.core.netguard import guard
from project_atlas.database.models import User
from project_atlas.database.session import make_engine, make_sessionmaker, upgrade_database
from project_atlas.security.ratelimit import RateLimiter

log = logging.getLogger("atlas")


@dataclass
class AtlasContext:
    settings: Settings
    engine: Engine
    sm: sessionmaker[Session]
    audit: AuditLog
    jobs: JobRunner = field(init=False)
    login_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(10, 60))
    api_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(600, 60))

    def __post_init__(self) -> None:
        self.jobs = JobRunner(self)

    @property
    def setup_token_path(self) -> Path:
        return self.settings.storage_dir / "setup-token.txt"

    def ensure_setup_token(self) -> str | None:
        """Create a one-time setup token when no users exist; return it (or None)."""
        with self.sm() as s:
            if s.execute(select(func.count()).select_from(User)).scalar_one() > 0:
                if self.setup_token_path.exists():
                    self.setup_token_path.unlink()
                return None
        if not self.setup_token_path.exists():
            self.setup_token_path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
            os.chmod(self.setup_token_path, 0o600)
        return self.setup_token_path.read_text(encoding="utf-8").strip()

    def dispose(self) -> None:
        self.jobs.shutdown()
        self.engine.dispose()


def build_context(settings: Settings) -> AtlasContext:
    settings.ensure_dirs()
    if settings.offline_mode:
        guard.install(allow_private=True)
    engine = make_engine(settings.resolved_database_url)
    upgrade_database(engine)
    sm = make_sessionmaker(engine)
    ctx = AtlasContext(settings=settings, engine=engine, sm=sm, audit=AuditLog(sm, settings.storage_dir))
    recovered = ctx.jobs.recover_interrupted()
    if recovered:
        log.warning("Marked %d interrupted job(s) as failed", recovered)
    # Importing registers job handlers.
    from project_atlas import handlers  # noqa: F401

    return ctx
