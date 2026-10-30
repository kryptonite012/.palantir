"""Global search, saved queries and query history."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from project_atlas.api.deps import Principal, current_principal, get_ctx, get_db, resolve_project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import NotFound
from project_atlas.database.models import ProjectMember, QueryHistory, SavedQuery, utcnow
from project_atlas.search import service as search
from project_atlas.security.rbac import project_permissions

router = APIRouter(prefix="/api/search", tags=["search"])

HISTORY_RETENTION_DAYS = 90


class SavedQueryBody(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=1000)
    kind: str = Field(default="search", pattern=r"^(search|sql)$")
    filters: dict = {}


def _scopes(db: Session, p: Principal, project_id: str | None) -> list[tuple[str, bool]]:
    if project_id:
        acc = resolve_project_access(db, p, project_id)
        acc.require("search.run")
        return [(project_id, acc.can("dataset.read_restricted"))]
    rows = db.execute(select(ProjectMember).where(ProjectMember.user_id == p.id)).scalars().all()
    return [(m.project_id, "dataset.read_restricted" in project_permissions(m.role))
            for m in rows if "search.run" in project_permissions(m.role)]


@router.get("")
def run_search(q: str, project_id: str | None = None, types: list[str] | None = Query(None, alias="type"),
               date_from: str | None = None, date_to: str | None = None, limit: int = 25, offset: int = 0,
               record_history: bool = True, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    scopes = _scopes(db, p, project_id)
    res = search.search(db, query=q, scopes=scopes, types=types, date_from=date_from, date_to=date_to,
                        limit=max(1, min(limit, 200)), offset=max(0, offset))
    if record_history and project_id:
        db.add(QueryHistory(project_id=project_id, user_id=p.id, kind="search", query=q,
                            filters={"types": types, "date_from": date_from, "date_to": date_to}, result_count=res["total"]))
        db.execute(delete(QueryHistory).where(QueryHistory.user_id == p.id,
                                              QueryHistory.created_at < utcnow() - timedelta(days=HISTORY_RETENTION_DAYS)))
        db.commit()
    return res


@router.get("/history")
def history(project_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    resolve_project_access(db, p, project_id)
    rows = db.execute(select(QueryHistory).where(QueryHistory.project_id == project_id, QueryHistory.user_id == p.id)
                      .order_by(QueryHistory.created_at.desc()).limit(50)).scalars().all()
    return {"retention_days": HISTORY_RETENTION_DAYS, "items": [
        {"id": h.id, "kind": h.kind, "query": h.query, "filters": h.filters, "result_count": h.result_count,
         "created_at": h.created_at} for h in rows]}


@router.delete("/history")
def clear_history(project_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    resolve_project_access(db, p, project_id)
    db.execute(delete(QueryHistory).where(QueryHistory.project_id == project_id, QueryHistory.user_id == p.id))
    db.commit()
    return {"ok": True}


@router.get("/saved")
def list_saved(project_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    resolve_project_access(db, p, project_id)
    rows = db.execute(select(SavedQuery).where(SavedQuery.project_id == project_id, SavedQuery.user_id == p.id)
                      .order_by(SavedQuery.name)).scalars().all()
    return [{"id": s.id, "name": s.name, "kind": s.kind, "query": s.query, "filters": s.filters, "created_at": s.created_at}
            for s in rows]


@router.post("/saved")
def save_query(body: SavedQueryBody, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
               ctx: AtlasContext = Depends(get_ctx)):
    resolve_project_access(db, p, body.project_id)
    if body.kind == "search":
        search.parse_query(body.query)  # validate now, not at use time
    s = SavedQuery(project_id=body.project_id, user_id=p.id, name=body.name, kind=body.kind, query=body.query,
                   filters=body.filters)
    db.add(s)
    db.commit()
    return {"id": s.id}


@router.delete("/saved/{saved_id}")
def delete_saved(saved_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    s = db.get(SavedQuery, saved_id)
    if s is None or s.user_id != p.id:
        raise NotFound("Saved query not found")
    db.delete(s)
    db.commit()
    return {"ok": True}
