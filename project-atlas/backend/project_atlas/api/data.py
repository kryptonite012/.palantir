"""Files, ingestion pipeline, data catalog, dataset versions, quality and jobs."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from project_atlas.api.common import (
    audit, can_read_dataset, get_dataset, get_version, paginate, redact_record, sensitive_columns,
)
from project_atlas.api.deps import ProjectAccess, current_principal, get_ctx, get_db, project_access, resolve_project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from project_atlas.database.models import (
    DataSource, Dataset, DatasetVersion, Entity, EntitySource, Event, GeoFeature, Job, QualityIssue, Record,
    Relationship, StoredFile,
)
from project_atlas.ingestion import normalize, parsers
from project_atlas.ingestion import service as ingest
from project_atlas.search import service as search

router = APIRouter(prefix="/api/projects/{project_id}", tags=["data"])
jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class InspectBody(BaseModel):
    file_id: str
    parse: dict = {}


class ImportBody(BaseModel):
    config: dict


class DatasetPatch(BaseModel):
    description: str | None = None
    access_policy: str | None = None
    retention_policy: str | None = None


def file_view(f: StoredFile) -> dict:
    return {"id": f.id, "original_name": f.original_name, "sha256": f.sha256, "size_bytes": f.size_bytes,
            "detected_format": f.detected_format, "uploaded_at": f.uploaded_at, "source_id": f.source_id}


@router.post("/files")
def upload_file(file: UploadFile = File(...), source_id: str | None = Form(None),
                acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                ctx: AtlasContext = Depends(get_ctx)):
    if not (acc.can("ingest.run") or acc.can("document.write")):
        raise Forbidden("Uploading requires ingestion or document permissions")
    if source_id:
        src = db.get(DataSource, source_id)
        if src is None or src.project_id != acc.project_id:
            raise NotFound("Source not found")
        if not src.permitted:
            audit(ctx, acc, "file.upload", "data_source", source_id, outcome="denied", details={"reason": "source not permitted"})
            raise Forbidden("This data source is not permitted for import")
    try:
        f = ingest.store_upload(ctx, db, project_id=acc.project_id, user_id=acc.principal.id,
                                filename=file.filename or "upload", stream=file.file, source_id=source_id)
    except ValidationFailed as exc:
        audit(ctx, acc, "file.upload", "file", None, outcome="failure", details={"name": file.filename, "error": exc.message})
        raise
    audit(ctx, acc, "file.upload", "file", f.id, details={"name": f.original_name, "sha256": f.sha256, "size": f.size_bytes})
    return file_view(f)


@router.get("/files")
def list_files(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("dataset.read")
    rows = db.execute(select(StoredFile).where(StoredFile.project_id == acc.project_id)
                      .order_by(StoredFile.uploaded_at.desc())).scalars().all()
    return [file_view(f) for f in rows]


@router.post("/ingest/inspect")
def inspect_file(body: InspectBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ingest.run")
    f, path = ingest.get_file(ctx, db, acc.project_id, body.file_id)
    if f.detected_format not in parsers.TABULAR_FORMATS:
        raise ValidationFailed(f"{f.detected_format} is a document format; add it through Documents")
    opts = parsers.ParseOptions.from_dict(body.parse)
    insp = parsers.inspect(path, f.detected_format, opts, preview_rows=200)
    samples = {c: [r.get(c) for r in insp.preview] for c in insp.columns}
    return {
        "file": file_view(f), "format": insp.format, "encoding": insp.encoding, "encoding_errors": insp.encoding_errors,
        "delimiter": insp.delimiter, "columns": insp.columns,
        "inferred_types": {c: normalize.infer_type(samples[c]) for c in insp.columns},
        "suggested_mapping": normalize.suggest_mapping(insp.columns, samples),
        "preview": [{k: parsers.jsonable(v) for k, v in r.items()} for r in insp.preview[:20]],
        "sheets": insp.sheets, "tables": insp.tables, "notes": insp.notes,
    }


@router.post("/ingest/preview")
def preview_import(body: ImportBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                   ctx: AtlasContext = Depends(get_ctx)):
    """Dry run over the full file: validation, quality checks and transformed preview. Writes nothing."""
    acc.require("ingest.run")
    return ingest.run_import(ctx, db, project_id=acc.project_id, user_id=acc.principal.id, cfg=body.config, dry_run=True)


@router.post("/ingest/commit")
def commit_import(body: ImportBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ingest.run")
    if body.config.get("dataset_id"):
        get_dataset(db, acc, body.config["dataset_id"])
        acc.require("dataset.write")
    ingest.get_file(ctx, db, acc.project_id, body.config.get("file_id", ""))
    job = ctx.jobs.create(kind="ingest", project_id=acc.project_id, user_id=acc.principal.id, params={"config": body.config})
    audit(ctx, acc, "ingest.started", "job", job.id, details={"file_id": body.config.get("file_id")})
    return job_view(job)


@router.get("/datasets")
def list_datasets(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("dataset.read")
    rows = db.execute(select(Dataset).where(Dataset.project_id == acc.project_id).order_by(Dataset.name)).scalars().all()
    out = []
    for ds in rows:
        if not can_read_dataset(acc, ds):
            continue
        dv = db.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id,
                                                     DatasetVersion.version == ds.current_version)).scalar_one_or_none()
        out.append(dataset_view(ds, dv))
    return out


def dataset_view(ds: Dataset, dv: DatasetVersion | None) -> dict:
    return {"id": ds.id, "name": ds.name, "description": ds.description, "owner_id": ds.owner_id,
            "access_policy": ds.access_policy, "retention_policy": ds.retention_policy,
            "current_version": ds.current_version, "is_synthetic": ds.is_synthetic, "created_at": ds.created_at,
            "source_id": ds.source_id,
            "latest": None if dv is None else {
                "version_id": dv.id, "version": dv.version, "record_count": dv.record_count,
                "imported_at": dv.imported_at, "schema": dv.schema_json, "quality": dv.quality_summary,
                "content_sha256": dv.content_sha256, "origin": dv.origin}}


@router.get("/datasets/{dataset_id}")
def dataset_detail(dataset_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                   ctx: AtlasContext = Depends(get_ctx)):
    ds = get_dataset(db, acc, dataset_id, ctx)
    versions = db.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id)
                          .order_by(DatasetVersion.version.desc())).scalars().all()
    current = next((v for v in versions if v.version == ds.current_version), None)
    view = dataset_view(ds, current)
    view["versions"] = [{"id": v.id, "version": v.version, "record_count": v.record_count, "imported_at": v.imported_at,
                         "imported_by": v.imported_by, "file_id": v.file_id, "origin": v.origin,
                         "content_sha256": v.content_sha256, "quality": v.quality_summary} for v in versions]
    if current:
        view["ingestion_report"] = current.ingestion_report
        view["lineage"] = lineage_for(db, current)
    return view


def lineage_for(db: Session, dv: DatasetVersion) -> dict:
    f = db.get(StoredFile, dv.file_id) if dv.file_id else None
    ents = db.execute(select(func.count(func.distinct(EntitySource.entity_id))).join(Record, Record.id == EntitySource.record_id)
                      .where(Record.dataset_version_id == dv.id)).scalar_one()
    rels = db.execute(select(func.count()).select_from(Relationship).join(Record, Record.id == Relationship.record_id)
                      .where(Record.dataset_version_id == dv.id)).scalar_one()
    return {"source_file": None if f is None else {"id": f.id, "name": f.original_name, "sha256": f.sha256},
            "parent_version_id": dv.parent_version_id, "origin": dv.origin,
            "transformations": dv.import_config.get("mapping") if dv.origin == "import" else dv.import_config,
            "pipeline_version": dv.ingestion_report.get("pipeline_version"),
            "derived": {"entities": ents, "relationships": rels}}


@router.patch("/datasets/{dataset_id}")
def patch_dataset(dataset_id: str, body: DatasetPatch, acc: ProjectAccess = Depends(project_access),
                  db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("dataset.write")
    ds = get_dataset(db, acc, dataset_id, ctx)
    changes = body.model_dump(exclude_none=True)
    if "access_policy" in changes:
        if changes["access_policy"] not in {"project", "restricted"}:
            raise ValidationFailed("access_policy must be project or restricted")
        acc.require("project.manage")
        search.set_dataset_access(db, ds.id, changes["access_policy"])
    if "retention_policy" in changes:
        from project_atlas.retention import POLICIES

        if changes["retention_policy"] not in POLICIES:
            raise ValidationFailed(f"retention_policy must be one of {POLICIES}")
    for k, v in changes.items():
        setattr(ds, k, v)
    db.commit()
    audit(ctx, acc, "dataset.update", "dataset", ds.id, details=changes)
    return {"ok": True}


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, confirm_name: str, acc: ProjectAccess = Depends(project_access),
                   db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    """Explicit deletion: removes records, derived events/geo features and search entries.

    Entities remain (they may be supported by other datasets) but lose provenance links to these records;
    relationships observed only in this dataset are removed with their source records.
    """
    acc.require("dataset.delete")
    ds = get_dataset(db, acc, dataset_id, ctx)
    if confirm_name != ds.name:
        raise ValidationFailed("confirm_name must equal the dataset name")
    version_ids = list(db.execute(select(DatasetVersion.id).where(DatasetVersion.dataset_id == ds.id)).scalars())
    rec_ids = select(Record.id).where(Record.dataset_id == ds.id)
    db.execute(delete(Relationship).where(Relationship.record_id.in_(rec_ids), Relationship.assertion == "observed"))
    db.execute(delete(Event).where(Event.dataset_id == ds.id))
    db.execute(delete(GeoFeature).where(GeoFeature.record_id.in_(rec_ids)))
    db.execute(delete(EntitySource).where(EntitySource.record_id.in_(rec_ids)))
    search.remove_dataset(db, ds.id)
    db.execute(delete(QualityIssue).where(QualityIssue.dataset_version_id.in_(version_ids)))
    db.execute(delete(Record).where(Record.dataset_id == ds.id))
    db.execute(delete(DatasetVersion).where(DatasetVersion.dataset_id == ds.id))
    # Entities left without any source record are removed too.
    orphan = select(Entity.id).where(Entity.project_id == acc.project_id,
                                     ~Entity.id.in_(select(EntitySource.entity_id)), Entity.status == "active")
    orphan_ids = list(db.execute(orphan).scalars())
    for eid in orphan_ids:
        search.remove_item(db, eid)
    db.execute(delete(Relationship).where(Relationship.source_entity_id.in_(orphan_ids) | Relationship.target_entity_id.in_(orphan_ids)))
    db.execute(delete(Entity).where(Entity.id.in_(orphan_ids)))
    db.delete(ds)
    db.commit()
    for vid in version_ids:
        ingest.parquet_path(ctx, vid).unlink(missing_ok=True)
    audit(ctx, acc, "dataset.delete", "dataset", dataset_id, details={"name": ds.name, "versions": len(version_ids),
                                                                       "orphan_entities_removed": len(orphan_ids)})
    return {"ok": True, "orphan_entities_removed": len(orphan_ids)}


@router.get("/datasets/{dataset_id}/records")
def dataset_records(dataset_id: str, version: int | None = None, limit: int = 50, offset: int = 0,
                    acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                    ctx: AtlasContext = Depends(get_ctx)):
    ds = get_dataset(db, acc, dataset_id, ctx)
    dv = get_version(db, ds, version)
    limit, offset = paginate(limit, offset)
    hidden = sensitive_columns(acc, dv)
    hidden_src = {f["source"] for f in dv.schema_json["fields"] if f["name"] in hidden}
    rows = db.execute(select(Record).where(Record.dataset_version_id == dv.id).order_by(Record.row_index)
                      .limit(limit).offset(offset)).scalars().all()
    return {"total": dv.record_count, "version": dv.version, "redacted_fields": sorted(hidden),
            "records": [{"id": r.id, "row_index": r.row_index, "normalized": redact_record(r.normalized, hidden),
                         "raw": redact_record(r.raw, hidden_src)} for r in rows]}


@router.get("/records/{record_id}")
def record_detail(record_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    r = db.get(Record, record_id)
    if r is None or r.project_id != acc.project_id:
        raise NotFound("Record not found")
    ds = get_dataset(db, acc, r.dataset_id, ctx)
    dv = db.get(DatasetVersion, r.dataset_version_id)
    hidden = sensitive_columns(acc, dv)
    hidden_src = {f["source"] for f in dv.schema_json["fields"] if f["name"] in hidden}
    f = db.get(StoredFile, dv.file_id) if dv.file_id else None
    ents = db.execute(select(Entity).join(EntitySource, EntitySource.entity_id == Entity.id)
                      .where(EntitySource.record_id == r.id)).scalars().all()
    return {"id": r.id, "row_index": r.row_index, "normalized": redact_record(r.normalized, hidden),
            "raw": redact_record(r.raw, hidden_src), "row_hash": r.row_hash,
            "dataset": {"id": ds.id, "name": ds.name, "version": dv.version, "version_id": dv.id},
            "source_file": None if f is None else {"id": f.id, "name": f.original_name, "sha256": f.sha256},
            "entities": [{"id": e.id, "display_name": e.display_name, "entity_type": e.entity_type} for e in ents],
            "quality_issues": [{"check": q.check, "field": q.field, "severity": q.severity, "message": q.message}
                               for q in db.execute(select(QualityIssue).where(QualityIssue.dataset_version_id == dv.id,
                                                                               QualityIssue.row_index == r.row_index)).scalars()]}


@router.get("/datasets/{dataset_id}/quality")
def dataset_quality(dataset_id: str, version: int | None = None, check: str | None = None, severity: str | None = None,
                    limit: int = 100, offset: int = 0, acc: ProjectAccess = Depends(project_access),
                    db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    ds = get_dataset(db, acc, dataset_id, ctx)
    dv = get_version(db, ds, version)
    limit, offset = paginate(limit, offset)
    q = select(QualityIssue).where(QualityIssue.dataset_version_id == dv.id)
    if check:
        q = q.where(QualityIssue.check == check)
    if severity:
        q = q.where(QualityIssue.severity == severity)
    hidden = sensitive_columns(acc, dv)
    rows = db.execute(q.order_by(QualityIssue.row_index).limit(limit).offset(offset)).scalars().all()
    return {"summary": dv.quality_summary, "issues": [
        {"row_index": i.row_index, "field": i.field, "check": i.check, "severity": i.severity, "message": i.message,
         "value": "[restricted]" if i.field in hidden else i.value} for i in rows]}


# --------------------------------------------------------------------------- jobs


def job_view(j: Job) -> dict:
    from project_atlas.core.jobs import LIVE

    live = LIVE.get(j.id) if j.status == "running" else None
    return {"id": j.id, "project_id": j.project_id, "kind": j.kind, "status": j.status,
            "progress": live["progress"] if live else j.progress, "message": live["message"] if live else j.message, "result": j.result, "error": j.error, "attempts": j.attempts,
            "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
            "created_by": j.created_by}


def _job_for(db: Session, p, job_id: str) -> Job:
    j = db.get(Job, job_id)
    if j is None:
        raise NotFound("Job not found")
    if j.project_id:
        resolve_project_access(db, p, j.project_id)
    elif j.created_by != p.id:
        raise NotFound("Job not found")
    return j


@jobs_router.get("")
def list_jobs(project_id: str | None = None, status: str | None = None, limit: int = 50, p=Depends(current_principal),
              db: Session = Depends(get_db)):
    q = select(Job).order_by(Job.created_at.desc()).limit(min(limit, 200))
    if project_id:
        resolve_project_access(db, p, project_id)
        q = q.where(Job.project_id == project_id)
    else:
        q = q.where(Job.created_by == p.id)
    if status:
        q = q.where(Job.status == status)
    return [job_view(j) for j in db.execute(q).scalars()]


@jobs_router.get("/{job_id}")
def get_job(job_id: str, p=Depends(current_principal), db: Session = Depends(get_db)):
    return job_view(_job_for(db, p, job_id))


@jobs_router.post("/{job_id}/cancel")
def cancel_job(job_id: str, p=Depends(current_principal), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    _job_for(db, p, job_id)
    j = ctx.jobs.cancel(job_id)
    ctx.audit.record("job.cancel_requested", actor_id=p.id, actor_name=p.name, resource_type="job", resource_id=job_id,
                     project_id=j.project_id if j else None)
    return job_view(j)


@jobs_router.post("/{job_id}/retry")
def retry_job(job_id: str, p=Depends(current_principal), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    j = _job_for(db, p, job_id)
    if j.created_by != p.id:
        raise Forbidden("Only the job's creator can retry it")
    r = ctx.jobs.retry(job_id)
    if r is None:
        raise Conflict("Only failed or cancelled jobs can be retried")
    return job_view(r)


@jobs_router.get("/{job_id}/events")
async def job_events(job_id: str, request: Request, p=Depends(current_principal), ctx: AtlasContext = Depends(get_ctx)):
    """Server-sent events stream of job progress until the job finishes."""
    with ctx.sm() as db:
        _job_for(db, p, job_id)

    async def gen():
        last = None
        while True:
            if await request.is_disconnected():
                return
            with ctx.sm() as db:
                j = db.get(Job, job_id)
                view = job_view(j)
            payload = json.dumps(view, default=str)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if view["status"] in {"succeeded", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")
