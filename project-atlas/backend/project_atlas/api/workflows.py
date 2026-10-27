"""Visual workflows: catalog, versioned definitions, validation, preview and execution."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas.api.common import audit
from project_atlas.api.deps import ProjectAccess, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import NotFound
from project_atlas.database.models import Workflow, WorkflowRun, WorkflowVersion
from project_atlas.workflows import engine

router = APIRouter(prefix="/api/projects/{project_id}/workflows", tags=["workflows"])


class WorkflowBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    definition: dict


class RunBody(BaseModel):
    version: int | None = None
    confirm: bool = False


def _wf(db: Session, acc: ProjectAccess, wid: str) -> Workflow:
    w = db.get(Workflow, wid)
    if w is None or w.project_id != acc.project_id:
        raise NotFound("Workflow not found")
    return w


def _version(db: Session, w: Workflow, version: int | None) -> WorkflowVersion:
    v = db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == w.id,
                                                 WorkflowVersion.version == (version or w.current_version))).scalar_one_or_none()
    if v is None:
        raise NotFound("Workflow version not found")
    return v


@router.get("/catalog")
def node_catalog(acc: ProjectAccess = Depends(project_access)):
    return engine.catalog()


@router.get("")
def list_workflows(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("workflow.read")
    return [{"id": w.id, "name": w.name, "description": w.description, "current_version": w.current_version,
             "created_at": w.created_at} for w in db.execute(select(Workflow).where(Workflow.project_id == acc.project_id)
                                                             .order_by(Workflow.name)).scalars()]


@router.post("/validate")
def validate(body: WorkflowBody, acc: ProjectAccess = Depends(project_access)):
    acc.require("workflow.read")
    return {"valid": True, "order": engine.validate(body.definition)}


@router.post("")
def create(body: WorkflowBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
           ctx: AtlasContext = Depends(get_ctx)):
    acc.require("workflow.write")
    engine.validate(body.definition)
    w = Workflow(project_id=acc.project_id, name=body.name, description=body.description, created_by=acc.principal.id)
    db.add(w)
    db.flush()
    db.add(WorkflowVersion(workflow_id=w.id, version=1, definition=body.definition, created_by=acc.principal.id))
    db.commit()
    audit(ctx, acc, "workflow.create", "workflow", w.id)
    return {"id": w.id, "version": 1}


@router.get("/{workflow_id}")
def get(workflow_id: str, version: int | None = None, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("workflow.read")
    w = _wf(db, acc, workflow_id)
    v = _version(db, w, version)
    versions = db.execute(select(WorkflowVersion.version, WorkflowVersion.created_at).where(WorkflowVersion.workflow_id == w.id)
                          .order_by(WorkflowVersion.version)).all()
    runs = db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == w.id).order_by(WorkflowRun.created_at.desc()).limit(20)).scalars()
    return {"id": w.id, "name": w.name, "description": w.description, "current_version": w.current_version,
            "version": v.version, "definition": v.definition,
            "versions": [{"version": n, "created_at": t} for n, t in versions],
            "runs": [{"id": r.id, "status": r.status, "job_id": r.job_id, "created_at": r.created_at,
                      "version_id": r.workflow_version_id} for r in runs]}


@router.put("/{workflow_id}")
def save_version(workflow_id: str, body: WorkflowBody, acc: ProjectAccess = Depends(project_access),
                 db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("workflow.write")
    w = _wf(db, acc, workflow_id)
    engine.validate(body.definition)
    w.current_version += 1
    w.name, w.description = body.name, body.description
    db.add(WorkflowVersion(workflow_id=w.id, version=w.current_version, definition=body.definition, created_by=acc.principal.id))
    db.commit()
    audit(ctx, acc, "workflow.version_saved", "workflow", w.id, details={"version": w.current_version})
    return {"id": w.id, "version": w.current_version}


@router.post("/{workflow_id}/preview")
def preview(workflow_id: str, body: RunBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
            ctx: AtlasContext = Depends(get_ctx)):
    """Execute on at most 200 rows per input; side-effecting nodes are skipped; nothing is persisted."""
    acc.require("workflow.run")
    w = _wf(db, acc, workflow_id)
    v = _version(db, w, body.version)
    ex = engine.ExecContext(ctx=ctx, db=db, project_id=acc.project_id, user_id=acc.principal.id, perms=acc.perms,
                            preview=True, run_id=None)
    try:
        res = engine.run_definition(ex, v.definition)
    finally:
        db.rollback()
    return {**res, "logs": ex.logs, "preview": True}


@router.post("/{workflow_id}/runs")
def run(workflow_id: str, body: RunBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
        ctx: AtlasContext = Depends(get_ctx)):
    acc.require("workflow.run")
    w = _wf(db, acc, workflow_id)
    v = _version(db, w, body.version)
    # Check permissions and confirmation up front so the user gets an immediate error.
    for n in v.definition["nodes"]:
        spec = engine.NODE_TYPES[n["type"]]
        acc.require(spec.permission)
        if spec.side_effect and not body.confirm:
            from project_atlas.core.errors import ValidationFailed

            raise ValidationFailed(f"Node {n['id']} ({spec.label}) has side effects; set confirm=true",
                                   details={"requires_confirmation": True})
    from project_atlas.database.models import Job

    job = Job(kind="workflow_run", project_id=acc.project_id, created_by=acc.principal.id, params={})
    db.add(job)
    db.flush()
    r = WorkflowRun(workflow_id=w.id, workflow_version_id=v.id, job_id=job.id, created_by=acc.principal.id)
    db.add(r)
    db.flush()
    job.params = {"run_id": r.id, "confirm": body.confirm, "workflow_version": v.version}
    db.commit()
    ctx.jobs.submit(job.id)
    audit(ctx, acc, "workflow.run_started", "workflow", w.id, details={"run_id": r.id, "version": v.version, "confirm": body.confirm})
    return {"run_id": r.id, "job_id": job.id}


@router.get("/{workflow_id}/runs/{run_id}")
def get_run(workflow_id: str, run_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("workflow.read")
    _wf(db, acc, workflow_id)
    r = db.get(WorkflowRun, run_id)
    if r is None or r.workflow_id != workflow_id:
        raise NotFound("Run not found")
    from project_atlas.api.data import job_view
    from project_atlas.database.models import Job

    return {"id": r.id, "status": r.status, "node_results": r.node_results, "logs": r.logs, "created_at": r.created_at,
            "job": job_view(db.get(Job, r.job_id))}
