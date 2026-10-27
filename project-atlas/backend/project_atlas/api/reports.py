"""Report builder and exports."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas.api.common import audit
from project_atlas.api.deps import ProjectAccess, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import NotFound
from project_atlas.database.models import Report, ReportExport, utcnow
from project_atlas.ingestion.service import storage_path
from project_atlas.reporting import service as rs
from project_atlas.search import service as search

router = APIRouter(prefix="/api/projects/{project_id}/reports", tags=["reports"])

MEDIA = {"pdf": "application/pdf", "html": "text/html", "json": "application/json", "csv": "text/csv",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class ReportBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    investigation_id: str | None = None
    definition: dict


def _report(db: Session, acc: ProjectAccess, report_id: str) -> Report:
    r = db.get(Report, report_id)
    if r is None or r.project_id != acc.project_id:
        raise NotFound("Report not found")
    return r


def report_view(r: Report) -> dict:
    return {"id": r.id, "title": r.title, "investigation_id": r.investigation_id, "definition": r.definition,
            "created_by": r.created_by, "created_at": r.created_at, "updated_at": r.updated_at}


@router.get("")
def list_reports(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("report.read")
    return [report_view(r) for r in db.execute(select(Report).where(Report.project_id == acc.project_id)
                                               .order_by(Report.updated_at.desc())).scalars()]


@router.get("/section-types")
def section_types(acc: ProjectAccess = Depends(project_access)):
    return sorted(rs.SECTION_TYPES)


@router.post("")
def create_report(body: ReportBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("report.write")
    rs.validate_definition(body.definition)
    r = Report(project_id=acc.project_id, title=body.title, investigation_id=body.investigation_id,
               definition=body.definition, created_by=acc.principal.id)
    db.add(r)
    db.flush()
    search.index_item(db, doc_type="report", ref_id=r.id, project_id=acc.project_id, title=r.title,
                      body=" ".join(str(s.get("body", "")) for s in body.definition["sections"]))
    db.commit()
    audit(ctx, acc, "report.create", "report", r.id)
    return report_view(r)


@router.get("/{report_id}")
def get_report(report_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("report.read")
    r = _report(db, acc, report_id)
    exports = db.execute(select(ReportExport).where(ReportExport.report_id == r.id).order_by(ReportExport.created_at.desc())).scalars()
    return {**report_view(r), "exports": [{"id": e.id, "format": e.format, "sha256": e.sha256, "size_bytes": e.size_bytes,
                                           "created_at": e.created_at} for e in exports]}


@router.put("/{report_id}")
def update_report(report_id: str, body: ReportBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("report.write")
    r = _report(db, acc, report_id)
    rs.validate_definition(body.definition)
    r.title, r.definition, r.investigation_id, r.updated_at = body.title, body.definition, body.investigation_id, utcnow()
    search.remove_item(db, r.id)
    search.index_item(db, doc_type="report", ref_id=r.id, project_id=acc.project_id, title=r.title,
                      body=" ".join(str(s.get("body", "")) for s in body.definition["sections"]))
    db.commit()
    audit(ctx, acc, "report.update", "report", r.id)
    return report_view(r)


@router.post("/{report_id}/preview")
def preview(report_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("report.read")
    r = _report(db, acc, report_id)
    res = rs.Resolver(db, acc.project_id, acc.perms)
    return {"blocks": res.resolve(r.definition), "manifest": res.manifest}


@router.post("/{report_id}/export")
def export(report_id: str, fmt: str = "pdf", acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
           ctx: AtlasContext = Depends(get_ctx)):
    acc.require("report.export")
    rex = rs.export_report(ctx, db, project_id=acc.project_id, report_id=report_id, fmt=fmt, user_id=acc.principal.id,
                           perms=acc.perms)
    db.commit()
    audit(ctx, acc, "export.report", "report", report_id,
          details={"format": fmt, "export_id": rex.id, "sha256": rex.sha256, "redactions": rex.manifest.get("redactions")})
    return {"id": rex.id, "format": rex.format, "sha256": rex.sha256, "size_bytes": rex.size_bytes, "manifest": rex.manifest}


@router.get("/{report_id}/exports/{export_id}")
def download(report_id: str, export_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
             ctx: AtlasContext = Depends(get_ctx)):
    acc.require("report.export")
    _report(db, acc, report_id)
    e = db.get(ReportExport, export_id)
    if e is None or e.report_id != report_id:
        raise NotFound("Export not found")
    audit(ctx, acc, "export.download", "report_export", e.id, details={"format": e.format})
    return FileResponse(storage_path(ctx, e.stored_path), media_type=MEDIA[e.format],
                        filename=f"atlas-report-{report_id[-8:]}.{e.format}", content_disposition_type="attachment")
