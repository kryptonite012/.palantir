"""Documents: processing, browsing pages, similarity and the evidence-grounded assistant."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from project_atlas.api.common import audit
from project_atlas.api.deps import ProjectAccess, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import NotFound
from project_atlas.database.models import Document, DocumentChunk, Embedding
from project_atlas.documents import service as docs
from project_atlas.ingestion.service import get_file
from project_atlas.search import service as search

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["documents"])


class ProcessBody(BaseModel):
    file_id: str
    title: str | None = None
    classification: str | None = Field(default=None, max_length=64)
    is_synthetic: bool = False


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] | None = None
    use_model: bool = True


def _doc(db: Session, acc: ProjectAccess, document_id: str) -> Document:
    d = db.get(Document, document_id)
    if d is None or d.project_id != acc.project_id:
        raise NotFound("Document not found")
    return d


@router.post("")
def process(body: ProcessBody, acc: ProjectAccess = Depends(project_access), ctx: AtlasContext = Depends(get_ctx),
            db: Session = Depends(get_db)):
    acc.require("document.write")
    get_file(ctx, db, acc.project_id, body.file_id)
    job = ctx.jobs.create(kind="document_process", project_id=acc.project_id, user_id=acc.principal.id,
                          params=body.model_dump())
    audit(ctx, acc, "document.process_started", "job", job.id, details={"file_id": body.file_id})
    from project_atlas.api.data import job_view

    return job_view(job)


@router.get("")
def list_documents(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("document.read")
    rows = db.execute(select(Document).where(Document.project_id == acc.project_id).order_by(Document.created_at.desc())).scalars()
    return [docs.document_view(d) for d in rows]


@router.get("/{document_id}")
def document_detail(document_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("document.read")
    return docs.document_view(_doc(db, acc, document_id), detail=True)


@router.get("/{document_id}/pages/{page}")
def document_page(document_id: str, page: int, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("document.read")
    d = _doc(db, acc, document_id)
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.document_id == d.id, DocumentChunk.page == page)
                        .order_by(DocumentChunk.chunk_index)).scalars().all()
    if not chunks:
        raise NotFound("Page not found")
    return {"document_id": d.id, "title": d.title, "page": page, "page_count": d.page_count,
            "page_label": d.metadata_json.get("page_label", "page"),
            "chunks": [{"id": c.id, "chunk_index": c.chunk_index, "char_start": c.char_start, "text": c.text} for c in chunks]}


@router.get("/{document_id}/similar")
def similar(document_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("document.read")
    _doc(db, acc, document_id)
    return docs.similar_documents(db, acc.project_id, document_id)


@router.get("/{document_id}/original")
def original(document_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
             ctx: AtlasContext = Depends(get_ctx)):
    acc.require("document.read")
    d = _doc(db, acc, document_id)
    f, path = get_file(ctx, db, acc.project_id, d.file_id)
    audit(ctx, acc, "document.download_original", "document", d.id)
    # Served as an attachment so untrusted content is never rendered in the application origin.
    return FileResponse(path, filename=f.original_name, media_type="application/octet-stream",
                        content_disposition_type="attachment")


@router.delete("/{document_id}")
def delete_document(document_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                    ctx: AtlasContext = Depends(get_ctx)):
    acc.require("dataset.delete")
    d = _doc(db, acc, document_id)
    search.remove_dataset(db, d.id)
    chunk_ids = select(DocumentChunk.id).where(DocumentChunk.document_id == d.id)
    db.execute(delete(Embedding).where(Embedding.chunk_id.in_(chunk_ids)))
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == d.id))
    db.delete(d)
    db.commit()
    audit(ctx, acc, "document.delete", "document", document_id)
    return {"ok": True}


@router.post("/ask")
def ask(body: AskBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
        ctx: AtlasContext = Depends(get_ctx)):
    acc.require("document.read")
    use_model = body.use_model and acc.can("ai.use")
    res = docs.ask(ctx, db, acc.project_id, body.question, body.document_ids, use_model=use_model)
    audit(ctx, acc, "document.assistant_query", "document", None,
          details={"mode": res["mode"], "label": res["label"], "citations": len(res["citations"])})
    return res
