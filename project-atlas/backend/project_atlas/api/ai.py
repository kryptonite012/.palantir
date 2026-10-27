"""Optional local AI: model registry, health, assisted tasks. Every output is labelled as a model suggestion."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas.ai import service as ai
from project_atlas.api.common import audit
from project_atlas.api.deps import Principal, ProjectAccess, current_principal, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import AtlasError, NotFound, ValidationFailed
from project_atlas.database.models import Document, ModelRegistryEntry, Relationship
from project_atlas.ontology.service import relationship_type_names

router = APIRouter(prefix="/api", tags=["ai"])


class AIUnavailableError(AtlasError):
    status_code = 503
    code = "ai_unavailable"


class ModelBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    kind: str = Field(pattern=r"^(chat|embedding|reranker|ocr)$")
    runtime: str = Field(default="ollama", pattern=r"^(ollama|llama_cpp)$")
    runtime_model_name: str
    file_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    quantization: str | None = None
    license: str = "unspecified"
    ram_mb: int | None = None


class AskSQL(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def model_view(m: ModelRegistryEntry) -> dict:
    return {"id": m.id, "name": m.name, "version": m.version, "kind": m.kind, "runtime": m.runtime,
            "runtime_model_name": m.runtime_model_name, "file_path": m.file_path, "sha256": m.sha256,
            "quantization": m.quantization, "license": m.license, "ram_mb": m.ram_mb, "enabled": m.enabled,
            "health": m.health, "health_detail": m.health_detail, "checked_at": m.checked_at}


@router.get("/ai/status")
def ai_status(p: Principal = Depends(current_principal), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    models = db.execute(select(ModelRegistryEntry)).scalars().all()
    return {"enabled": ctx.settings.ai_enabled, "base_url": ctx.settings.ai_base_url or None,
            "models": [model_view(m) for m in models],
            "available": ctx.settings.ai_enabled and any(m.health == "healthy" and m.enabled for m in models),
            "note": "AI is optional. All non-AI features work without a model. Inference is local only; there is no external fallback."}


@router.post("/ai/models")
def register_model(body: ModelBody, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                   ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("admin.models")
    if body.file_path:
        mp = Path(body.file_path).resolve()
        root = ctx.settings.model_dir.resolve()
        if root not in mp.parents:
            raise ValidationFailed(f"Model files must be stored under ATLAS_MODEL_DIR ({root})")
    m = ModelRegistryEntry(**body.model_dump())
    db.add(m)
    db.commit()
    ctx.audit.record("ai.model_registered", actor_id=p.id, actor_name=p.name, resource_type="model", resource_id=m.id,
                     details={"name": m.name, "version": m.version, "kind": m.kind})
    return model_view(m)


@router.post("/ai/models/{model_id}/check")
def check_model(model_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("admin.models")
    m = db.get(ModelRegistryEntry, model_id)
    if m is None:
        raise NotFound("Model not found")
    return model_view(ai.check_health(ctx, db, m))


@router.patch("/ai/models/{model_id}")
def toggle_model(model_id: str, enabled: bool, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("admin.models")
    m = db.get(ModelRegistryEntry, model_id)
    if m is None:
        raise NotFound("Model not found")
    m.enabled = enabled
    db.commit()
    ctx.audit.record("ai.model_toggled", actor_id=p.id, actor_name=p.name, resource_type="model", resource_id=m.id,
                     details={"enabled": enabled})
    return model_view(m)


def _wrap(fn):
    try:
        return fn()
    except ai.AIUnavailable as exc:
        raise AIUnavailableError(f"Local AI unavailable: {exc}") from exc


@router.post("/projects/{project_id}/ai/sql-draft")
def sql_draft(body: AskSQL, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
              ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ai.use")
    acc.require("query.sql")
    from project_atlas.api.analysis import sql_tables

    tables = {t["table"]: t["columns"] for t in sql_tables(acc, db)}
    res = _wrap(lambda: ai.draft_sql(ctx, db, body.question, tables))
    audit(ctx, acc, "ai.sql_draft", "query", None, details={"valid": res["valid"]})
    return res


@router.post("/projects/{project_id}/ai/documents/{document_id}/summary")
def summarize(document_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
              ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ai.use")
    d = db.get(Document, document_id)
    if d is None or d.project_id != acc.project_id:
        raise NotFound("Document not found")
    res = _wrap(lambda: ai.summarize_document(ctx, db, d))
    audit(ctx, acc, "ai.summary", "document", d.id)
    return res


@router.post("/projects/{project_id}/ai/documents/{document_id}/relationship-hypotheses")
def hypotheses(document_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
               ctx: AtlasContext = Depends(get_ctx)):
    """Stores model suggestions as *unverified* relationships that reviewers must verify or reject."""
    acc.require("ai.use")
    acc.require("graph.write")
    d = db.get(Document, document_id)
    if d is None or d.project_id != acc.project_id:
        raise NotFound("Document not found")
    hyps = _wrap(lambda: ai.suggest_relationships(ctx, db, acc.project_id, d))
    known = relationship_type_names(db, acc.project_id)
    m = ai.default_model(db, "chat")
    created = []
    for h in hyps:
        rel_type = h["rel_type"] if h["rel_type"] in known else "associated_with"
        r = Relationship(project_id=acc.project_id, source_entity_id=h["source_entity_id"],
                         target_entity_id=h["target_entity_id"], rel_type=rel_type, assertion="model_suggested",
                         status="unverified", confidence=None,
                         evidence={"document_id": d.id, "quote": h["quote"], "quote_found_in_document": h["quote_found_in_document"],
                                   "model": m.name if m else None, "proposed_rel_type": h["rel_type"],
                                   "label": "Model hypothesis — not verified"},
                         created_by=f"model:{m.name if m else 'unknown'}")
        db.add(r)
        created.append(r)
    db.commit()
    audit(ctx, acc, "ai.relationship_hypotheses", "document", d.id, details={"created": len(created)})
    return {"created": [r.id for r in created], "label": "model_suggested_unverified",
            "note": "Hypotheses are hidden from the default graph until a reviewer verifies them."}


@router.post("/projects/{project_id}/ai/embeddings")
def embed_docs(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ai.use")
    m = ai.default_model(db, "embedding")
    if m is None or not ctx.settings.ai_enabled:
        raise AIUnavailableError("No healthy local embedding model")
    job = ctx.jobs.create(kind="embed_documents", project_id=acc.project_id, user_id=acc.principal.id, params={"model_id": m.id})
    from project_atlas.api.data import job_view

    return job_view(job)


@router.get("/projects/{project_id}/ai/semantic-search")
def semantic(q: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("search.run")
    acc.require("ai.use")
    return _wrap(lambda: ai.semantic_search(ctx, db, acc.project_id, q))
