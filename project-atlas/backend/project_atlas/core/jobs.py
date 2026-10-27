"""Background job execution with progress, cancellation and retries.

Jobs are persisted in the ``jobs`` table. Handlers are registered by kind and
run on a small thread pool (or inline when ATLAS_JOBS_INLINE=true, used by
tests and constrained machines). Progress is written to the database and can
be streamed to clients via server-sent events.
"""

from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable

from project_atlas.database.models import Job, utcnow

if TYPE_CHECKING:
    from project_atlas.core.context import AtlasContext

log = logging.getLogger("atlas.jobs")


class JobCancelled(Exception):
    pass


# Live progress for running jobs is kept in memory: a long import holds SQLite's single write
# lock, so progress updates must not require their own write transaction. Final state is persisted.
LIVE: dict[str, dict[str, Any]] = {}


class JobReporter:
    def __init__(self, ctx: "AtlasContext", job_id: str):
        self.ctx = ctx
        self.job_id = job_id
        LIVE[job_id] = {"progress": 0.0, "message": "", "cancel": False}

    def progress(self, fraction: float, message: str = "") -> None:
        live = LIVE.setdefault(self.job_id, {"progress": 0.0, "message": "", "cancel": False})
        if live["cancel"]:
            raise JobCancelled()
        live["progress"] = max(0.0, min(1.0, fraction))
        if message:
            live["message"] = message

    def check_cancel(self) -> None:
        if LIVE.get(self.job_id, {}).get("cancel"):
            raise JobCancelled()


Handler = Callable[["AtlasContext", Job, JobReporter], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}


def register(kind: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


class JobRunner:
    def __init__(self, ctx: "AtlasContext", workers: int = 2):
        self.ctx = ctx
        self.inline = ctx.settings.jobs_inline
        self.pool = None if self.inline else ThreadPoolExecutor(max_workers=workers, thread_name_prefix="atlas-job")

    def create(self, *, kind: str, project_id: str | None, user_id: str, params: dict[str, Any]) -> Job:
        if kind not in HANDLERS:
            raise ValueError(f"Unknown job kind {kind}")
        with self.ctx.sm() as s:
            job = Job(kind=kind, project_id=project_id, created_by=user_id, params=params)
            s.add(job)
            s.commit()
            s.refresh(job)
        self.submit(job.id)
        with self.ctx.sm() as s:
            return s.get(Job, job.id)  # type: ignore[return-value]

    def submit(self, job_id: str) -> None:
        if self.pool is None:
            self._run(job_id)
        else:
            self.pool.submit(self._run, job_id)

    def _run(self, job_id: str) -> None:
        with self.ctx.sm() as s:
            job = s.get(Job, job_id)
            if job is None or job.status not in {"queued"}:
                return
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = utcnow()
                s.commit()
                return
            job.status = "running"
            job.started_at = utcnow()
            job.attempts += 1
            s.commit()
            s.refresh(job)
            s.expunge(job)
        reporter = JobReporter(self.ctx, job_id)
        try:
            result = HANDLERS[job.kind](self.ctx, job, reporter)
            status, error = "succeeded", None
        except JobCancelled:
            result, status, error = {}, "cancelled", None
        except Exception as exc:  # noqa: BLE001 - job boundary
            log.error("job %s (%s) failed: %s", job_id, job.kind, exc)
            result, status, error = {}, "failed", f"{type(exc).__name__}: {exc}"
            log.debug(traceback.format_exc())
        live = LIVE.pop(job_id, {})
        with self.ctx.sm() as s:
            j = s.get(Job, job_id)
            if j is None:
                return
            j.status = status
            j.message = live.get("message") or j.message
            j.result = result or {}
            j.error = error
            j.finished_at = utcnow()
            if status == "succeeded":
                j.progress = 1.0
                j.message = j.message or "Completed"
            s.commit()
        self.ctx.audit.record(
            f"job.{status}", actor_id=job.created_by, actor_name="system:jobs", resource_type="job",
            resource_id=job_id, project_id=job.project_id, outcome="success" if status == "succeeded" else "failure",
            details={"kind": job.kind, "error": error},
        )

    def cancel(self, job_id: str) -> Job | None:
        with self.ctx.sm() as s:
            job = s.get(Job, job_id)
            if job is None:
                return None
            if job.status in {"queued", "running"}:
                job.cancel_requested = True
                if job_id in LIVE:
                    LIVE[job_id]["cancel"] = True
                if job.status == "queued":
                    job.status = "cancelled"
                    job.finished_at = utcnow()
            s.commit()
            s.refresh(job)
            return job

    def retry(self, job_id: str) -> Job | None:
        with self.ctx.sm() as s:
            job = s.get(Job, job_id)
            if job is None or job.status not in {"failed", "cancelled"}:
                return None
            job.status = "queued"
            job.cancel_requested = False
            job.error = None
            job.progress = 0.0
            job.message = "Retry queued"
            s.commit()
        self.submit(job_id)
        with self.ctx.sm() as s:
            return s.get(Job, job_id)

    def recover_interrupted(self) -> int:
        """Mark jobs left 'running' by a previous process as failed so they can be retried."""
        from sqlalchemy import update

        with self.ctx.sm() as s:
            res = s.execute(
                update(Job).where(Job.status.in_(["running", "queued"]))
                .values(status="failed", error="Interrupted by application restart; retry to resume", finished_at=utcnow())
            )
            s.commit()
            return res.rowcount or 0

    def shutdown(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
