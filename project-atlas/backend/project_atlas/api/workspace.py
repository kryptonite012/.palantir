"""Personal workspace features and project lifecycle.

Saved views, entity watches, notifications, project activity feed, dashboard insights,
the one-click synthetic demo workspace, and project archive/delete.
"""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, union_all, update
from sqlalchemy.orm import Session

from project_atlas.api.common import audit
from project_atlas.api.deps import Principal, ProjectAccess, current_principal, get_ctx, get_db, project_access, resolve_project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Conflict, NotFound, ValidationFailed
from project_atlas.database.models import (
    AuditEvent, Dataset, DatasetVersion, Entity, Event, Notification, Project, ProjectMember, QualityIssue, Relationship,
    SavedView, Watch, utcnow,
)

router = APIRouter(prefix="/api", tags=["workspace"])

# Actions shown in the project activity feed (details are never exposed here — see the Audit Center).
ACTIVITY_PREFIXES = ("ingest.", "entity.", "relationship.", "dataset.", "document.process", "analysis.", "workflow.",
                     "export.report", "report.", "investigation.", "finding.", "evidence.", "graph.snapshot", "demo.",
                     "retention.", "permission.", "project.")


class ViewBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024, pattern=r"^/[^\s]*$")
    project_id: str | None = None


class DemoBody(BaseModel):
    name: str = Field(default="Northwind Harbor (synthetic demo)", min_length=1, max_length=128)


class ArchiveBody(BaseModel):
    archived: bool


# --------------------------------------------------------------------------- saved views


@router.get("/views")
def list_views(project_id: str | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = select(SavedView).where(SavedView.user_id == p.id)
    if project_id:
        q = q.where((SavedView.project_id == project_id) | SavedView.project_id.is_(None))
    return [{"id": v.id, "name": v.name, "path": v.path, "project_id": v.project_id, "created_at": v.created_at}
            for v in db.execute(q.order_by(SavedView.name)).scalars()]


@router.post("/views")
def save_view(body: ViewBody, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    if body.path.startswith("//") or "://" in body.path:
        raise ValidationFailed("Views must be paths inside Project Atlas")
    if body.project_id:
        resolve_project_access(db, p, body.project_id)
    v = SavedView(user_id=p.id, project_id=body.project_id, name=body.name, path=body.path)
    db.add(v)
    db.commit()
    return {"id": v.id}


@router.delete("/views/{view_id}")
def delete_view(view_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    v = db.get(SavedView, view_id)
    if v is None or v.user_id != p.id:
        raise NotFound("View not found")
    db.delete(v)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- watches & notifications


@router.get("/projects/{project_id}/watches")
def list_watches(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    rows = db.execute(select(Watch, Entity).join(Entity, Entity.id == Watch.entity_id)
                      .where(Watch.project_id == acc.project_id, Watch.user_id == acc.principal.id)).all()
    return [{"id": w.id, "entity_id": e.id, "display_name": e.display_name, "entity_type": e.entity_type,
             "status": e.status, "created_at": w.created_at} for w, e in rows]


@router.put("/projects/{project_id}/watches/{entity_id}")
def watch(entity_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
          ctx: AtlasContext = Depends(get_ctx)):
    acc.require("entity.read")
    e = db.get(Entity, entity_id)
    if e is None or e.project_id != acc.project_id:
        raise NotFound("Entity not found")
    if not db.execute(select(Watch).where(Watch.user_id == acc.principal.id, Watch.entity_id == entity_id)).scalar_one_or_none():
        db.add(Watch(project_id=acc.project_id, user_id=acc.principal.id, entity_id=entity_id))
        db.commit()
        audit(ctx, acc, "entity.watch", "entity", entity_id)
    return {"watching": True}


@router.delete("/projects/{project_id}/watches/{entity_id}")
def unwatch(entity_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    db.execute(delete(Watch).where(Watch.user_id == acc.principal.id, Watch.entity_id == entity_id,
                                   Watch.project_id == acc.project_id))
    db.commit()
    return {"watching": False}


@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = 30, p: Principal = Depends(current_principal),
                  db: Session = Depends(get_db)):
    member_of = set(db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == p.id)).scalars())
    q = select(Notification).where(Notification.user_id == p.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.order_by(Notification.created_at.desc()).limit(min(limit, 200))).scalars().all()
    unread = db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == p.id,
                                                                            Notification.read_at.is_(None))).scalar_one()
    return {"unread": unread, "items": [
        {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "project_id": n.project_id,
         "read": n.read_at is not None, "created_at": n.created_at}
        for n in rows if n.project_id is None or n.project_id in member_of]}


@router.post("/notifications/read")
def mark_read(ids: list[str] | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = update(Notification).where(Notification.user_id == p.id, Notification.read_at.is_(None))
    if ids:
        q = q.where(Notification.id.in_(ids))
    n = db.execute(q.values(read_at=utcnow())).rowcount
    db.commit()
    return {"marked": n}


# --------------------------------------------------------------------------- activity & insights


@router.get("/projects/{project_id}/activity")
def activity(limit: int = 30, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("project.read")
    rows = db.execute(select(AuditEvent).where(AuditEvent.project_id == acc.project_id, AuditEvent.outcome == "success")
                      .order_by(AuditEvent.seq.desc()).limit(400)).scalars()
    out = []
    for e in rows:
        if e.action.startswith(ACTIVITY_PREFIXES) and not e.actor_name.startswith("system:jobs"):
            out.append({"seq": e.seq, "ts": e.ts, "actor": e.actor_name, "action": e.action,
                        "resource_type": e.resource_type, "resource_id": e.resource_id})
            if len(out) >= min(limit, 100):
                break
    return out


@router.get("/projects/{project_id}/insights")
def insights(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    """Dashboard breakdowns, all computed from the project's current data (empty lists when there is none)."""
    pid = acc.project_id
    by_type = dict(db.execute(select(Entity.entity_type, func.count()).where(Entity.project_id == pid, Entity.status == "active")
                              .group_by(Entity.entity_type)).all())
    ds_where = [Dataset.project_id == pid, DatasetVersion.version == Dataset.current_version]
    if not acc.can("dataset.read_restricted"):
        ds_where.append(Dataset.access_policy != "restricted")
    quality = dict(db.execute(select(QualityIssue.check, func.count()).join(DatasetVersion, DatasetVersion.id == QualityIssue.dataset_version_id)
                              .join(Dataset, Dataset.id == DatasetVersion.dataset_id).where(*ds_where)
                              .group_by(QualityIssue.check)).all())
    rq = select(Relationship.source_entity_id.label("eid")).where(Relationship.project_id == pid, Relationship.status == "active")
    rq2 = select(Relationship.target_entity_id.label("eid")).where(Relationship.project_id == pid, Relationship.status == "active")
    ends = union_all(rq, rq2).subquery()
    top = db.execute(select(Entity.id, Entity.display_name, Entity.entity_type, func.count().label("d"))
                     .join(ends, ends.c.eid == Entity.id).where(Entity.status == "active")
                     .group_by(Entity.id, Entity.display_name, Entity.entity_type).order_by(text("d DESC")).limit(8)).all()
    month = func.strftime("%Y-%m", Event.event_time) if db.bind.dialect.name == "sqlite" else func.to_char(Event.event_time, "YYYY-MM")
    events = db.execute(select(month.label("m"), func.count()).where(Event.project_id == pid).group_by("m").order_by("m")).all()
    watched = db.execute(select(func.count()).select_from(Watch).where(Watch.project_id == pid, Watch.user_id == acc.principal.id)).scalar_one()
    return {"entities_by_type": by_type, "quality_by_check": quality,
            "top_connected": [{"id": i, "label": n, "entity_type": t, "degree": d} for i, n, t, d in top],
            "events_by_month": [{"month": m, "count": c} for m, c in events], "watched_entities": watched}


# --------------------------------------------------------------------------- demo & lifecycle


@router.post("/projects/demo")
def create_demo(body: DemoBody, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                ctx: AtlasContext = Depends(get_ctx)):
    """Create a project and load the SYNTHETIC Northwind Harbor dataset through the normal pipelines."""
    p.require_global("project.create")
    from project_atlas.ontology.service import seed_project_ontology

    if db.execute(select(Project).where(Project.name == body.name)).scalar_one_or_none():
        raise Conflict("A project with this name already exists")
    pr = Project(name=body.name, description="SYNTHETIC demonstration workspace — fictional people, organizations and documents.",
                 classification="internal", created_by=p.id)
    db.add(pr)
    db.flush()
    db.add(ProjectMember(project_id=pr.id, user_id=p.id, role="project_admin"))
    seed_project_ontology(db, pr.id)
    db.commit()
    ctx.audit.record("project.create", actor_id=p.id, actor_name=p.name, resource_type="project", resource_id=pr.id,
                     project_id=pr.id, details={"name": pr.name, "demo": True})
    job = ctx.jobs.create(kind="demo_load", project_id=pr.id, user_id=p.id, params={})
    from project_atlas.api.data import job_view

    return {"project": {"id": pr.id, "name": pr.name}, "job": job_view(job)}


@router.patch("/projects/{project_id}/archive")
def archive(body: ArchiveBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
            ctx: AtlasContext = Depends(get_ctx)):
    acc.require("project.manage")
    acc.project.archived = body.archived
    db.commit()
    audit(ctx, acc, "project.archived" if body.archived else "project.unarchived", "project", acc.project_id)
    return {"archived": body.archived}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, confirm_name: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                   ctx: AtlasContext = Depends(get_ctx)):
    """Permanently delete a project and all of its data. System administrators who are project admins only."""
    p.require_global("admin.projects")
    acc = resolve_project_access(db, p, project_id)
    acc.require("project.manage")
    pr = acc.project
    if confirm_name != pr.name:
        raise ValidationFailed("confirm_name must equal the project name")
    from project_atlas.ingestion.service import parquet_path

    version_ids = list(db.execute(select(DatasetVersion.id).join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                                  .where(Dataset.project_id == pr.id)).scalars())
    if db.bind.dialect.name == "sqlite":
        db.execute(text("DELETE FROM search_index WHERE project_id = :p"), {"p": pr.id})
        db.execute(text("DELETE FROM search_docs WHERE rowid NOT IN (SELECT rowid FROM search_index)"))
    else:
        db.execute(text("DELETE FROM search_index WHERE project_id = :p"), {"p": pr.id})
    db.delete(pr)  # ON DELETE CASCADE removes every project-scoped row
    db.commit()
    for vid in version_ids:
        parquet_path(ctx, vid).unlink(missing_ok=True)
    for d in (ctx.settings.files_dir / pr.id, ctx.settings.exports_dir / pr.id):
        shutil.rmtree(d, ignore_errors=True)
    ctx.audit.record("project.delete", actor_id=p.id, actor_name=p.name, resource_type="project", resource_id=project_id,
                     details={"name": pr.name, "dataset_versions": len(version_ids)})
    return {"ok": True}
