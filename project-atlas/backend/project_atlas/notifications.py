"""In-app notifications: job outcomes, watched-entity activity, retention notices."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from project_atlas.database.models import Entity, EntitySource, Notification, Record, Watch

JOB_LABELS = {"ingest": "Import", "entity_resolution": "Entity resolution", "document_process": "Document processing",
              "workflow_run": "Workflow run", "embed_documents": "Embedding generation", "backup": "Backup",
              "demo_load": "Demo workspace", "retention_sweep": "Retention sweep"}


def notify(db: Session, *, user_id: str, kind: str, title: str, body: str = "", link: str | None = None,
           project_id: str | None = None, details: dict[str, Any] | None = None) -> Notification:
    n = Notification(user_id=user_id, project_id=project_id, kind=kind, title=title[:255], body=body, link=link,
                     details=details or {})
    db.add(n)
    return n


def job_finished(db: Session, job, status: str, result: dict[str, Any], error: str | None) -> None:
    label = JOB_LABELS.get(job.kind, job.kind)
    if status == "succeeded":
        title, body = f"{label} finished", _job_summary(job.kind, result)
    elif status == "failed":
        title, body = f"{label} failed", (error or "")[:500]
    else:
        title, body = f"{label} {status}", ""
    link = None
    if job.kind == "ingest" and result.get("dataset"):
        link = f"/catalog/{result['dataset']['id']}"
    elif job.kind == "entity_resolution":
        link = "/entities?tab=review"
    elif job.kind == "demo_load":
        link = "/"
    elif job.kind == "document_process" and result.get("document_id"):
        link = f"/documents?doc={result['document_id']}"
    notify(db, user_id=job.created_by, project_id=job.project_id, kind="job", title=title, body=body, link=link,
           details={"job_id": job.id, "status": status})


def _job_summary(kind: str, r: dict[str, Any]) -> str:
    if kind == "ingest":
        c = r.get("counts", {})
        return (f"{c.get('records', 0)} records into {r.get('dataset', {}).get('name')} v{r.get('dataset', {}).get('version')}; "
                f"{c.get('entities_created', 0)} new entities, {c.get('relationships', 0)} relationships")
    if kind == "entity_resolution":
        return f"{r.get('candidates_created', 0)} new match candidates ({r.get('by_band', {})})"
    if kind == "demo_load":
        return f"Loaded {sum(r.get('datasets', {}).values())} synthetic records and {r.get('documents', 0)} documents"
    if kind == "document_process":
        return f"{r.get('pages', 0)} pages, {r.get('chunks', 0)} passages"
    return ""


def watched_entities_updated(db: Session, *, project_id: str, dataset_version_id: str, dataset_name: str,
                             actor_id: str) -> int:
    """Notify watchers whose entities received new source records from a dataset version."""
    rows = db.execute(
        select(Watch.user_id, Watch.entity_id, Entity.display_name, func.count(EntitySource.id))
        .join(EntitySource, EntitySource.entity_id == Watch.entity_id)
        .join(Record, Record.id == EntitySource.record_id)
        .join(Entity, Entity.id == Watch.entity_id)
        .where(Watch.project_id == project_id, Record.dataset_version_id == dataset_version_id)
        .group_by(Watch.user_id, Watch.entity_id, Entity.display_name)
    ).all()
    for user_id, entity_id, name, n in rows:
        notify(db, user_id=user_id, project_id=project_id, kind="watch", title=f"New data about {name}",
               body=f"{n} new source record(s) in {dataset_name}", link=f"/entities/{entity_id}",
               details={"entity_id": entity_id, "records": n, "dataset_version_id": dataset_version_id,
                        "by": actor_id})
    return len(rows)
