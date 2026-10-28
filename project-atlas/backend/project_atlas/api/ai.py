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


# --------------------------------------------------------------------------- assistants added in 0.2


class AskData(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    sql: str | None = Field(default=None, max_length=20000)
    execute: bool = False


class FileRef(BaseModel):
    file_id: str


@router.post("/projects/{project_id}/ai/ask-data")
def ask_data(body: AskData, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
             ctx: AtlasContext = Depends(get_ctx)):
    """Natural-language data exploration in two explicit steps.

    1. Without ``execute``: the local model drafts SQL (validated, not run).
    2. With ``execute`` and the reviewed ``sql``: the SQL runs in the read-only sandbox and the model
       describes the result rows. The narrative is labelled as model output; the table is the evidence.
    """
    acc.require("ai.use")
    acc.require("query.sql")
    from project_atlas.analytics import sql as sqlx
    from project_atlas.api.analysis import _sql_tables, sql_tables

    if not body.execute:
        tables = {t["table"]: t["columns"] for t in sql_tables(acc, db)}
        res = _wrap(lambda: ai.draft_sql(ctx, db, body.question, tables))
        audit(ctx, acc, "ai.ask_data_draft", "query", None, details={"valid": res["valid"]})
        return {"stage": "draft", **res}
    if not body.sql:
        raise ValidationFailed("Provide the reviewed SQL to execute")
    tables, versions = _sql_tables(ctx, db, acc)
    res = sqlx.run_query(body.sql, tables, row_limit=min(ctx.settings.query_row_limit, 1000),
                         timeout_s=ctx.settings.query_timeout_seconds)
    narrative = None
    try:
        narrative = ai.narrate_table(ctx, db, body.question, res["columns"], res["rows"]) if res["rows"] else None
    except ai.AIUnavailable:
        narrative = None
    audit(ctx, acc, "ai.ask_data_execute", "query", None, details={"sql": body.sql[:2000], "rows": res["row_count"]})
    return {"stage": "result", **res, "dataset_versions": versions, "narrative": narrative,
            "narrative_label": "model_description_of_result" if narrative else None,
            "note": "The result table is computed deterministically; the narrative is a local-model description of it."}


@router.post("/projects/{project_id}/ai/schema-mapping")
def schema_mapping(body: FileRef, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                   ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ai.use")
    acc.require("ingest.run")
    from project_atlas.ingestion import normalize, parsers
    from project_atlas.ingestion.service import get_file

    f, path = get_file(ctx, db, acc.project_id, body.file_id)
    if f.detected_format not in parsers.TABULAR_FORMATS:
        raise ValidationFailed("Schema mapping applies to tabular files")
    insp = parsers.inspect(path, f.detected_format, parsers.ParseOptions(), preview_rows=50)
    samples = {c: [r.get(c) for r in insp.preview] for c in insp.columns}
    res = _wrap(lambda: ai.suggest_schema(ctx, db, insp.columns, samples))
    audit(ctx, acc, "ai.schema_mapping", "file", f.id, details={"suggested": len(res["suggestions"])})
    return {**res, "deterministic": normalize.suggest_mapping(insp.columns, samples)}


@router.get("/projects/{project_id}/datasets/{dataset_id}/quality/explain")
def quality_explain(dataset_id: str, use_model: bool = False, acc: ProjectAccess = Depends(project_access),
                    db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    """Plain-language explanation of a dataset version's quality issues; optional local-model summary."""
    from project_atlas.api.common import get_dataset, get_version
    from project_atlas.ingestion.quality import explain

    ds = get_dataset(db, acc, dataset_id, ctx)
    dv = get_version(db, ds)
    items = explain(dv.quality_summary)
    out = {"dataset": ds.name, "version": dv.version, "rows": dv.quality_summary.get("rows"), "explanations": items,
           "label": "deterministic_explanation", "narrative": None}
    if use_model and acc.can("ai.use") and items:
        out["narrative"] = _wrap(lambda: ai.explain_quality(ctx, db, ds.name, items))
        out["narrative_label"] = "model_generated_summary"
    return out


@router.post("/projects/{project_id}/ai/investigations/{inv_id}/summary")
def investigation_summary(inv_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                          ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ai.use")
    from project_atlas.api.investigations import _inv
    from project_atlas.database.models import Evidence, Finding

    inv = _inv(db, acc, inv_id)
    findings = db.execute(select(Finding).where(Finding.investigation_id == inv.id).order_by(Finding.created_at)).scalars().all()
    evidence = db.execute(select(Evidence).where(Evidence.investigation_id == inv.id).order_by(Evidence.captured_at)).scalars().all()
    if not findings and not evidence:
        raise ValidationFailed("The investigation has no findings or evidence to summarise yet")
    res = _wrap(lambda: ai.summarize_investigation(ctx, db, inv, findings, evidence))
    audit(ctx, acc, "ai.investigation_summary", "investigation", inv.id, details={"cited": len(res["cited"])})
    return res


@router.post("/projects/{project_id}/ai/reports/{report_id}/draft")
def report_draft(report_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    """Draft an executive summary from the report's reviewed findings and recorded analyses (never auto-inserted)."""
    acc.require("ai.use")
    acc.require("report.write")
    from project_atlas.database.models import AnalysisRun, Finding, Report

    r = db.get(Report, report_id)
    if r is None or r.project_id != acc.project_id:
        raise NotFound("Report not found")
    facts: list[str] = []
    for s in r.definition.get("sections", []):
        if s.get("type") == "findings" and s.get("investigation_id"):
            from project_atlas.api.investigations import _inv

            inv = _inv(db, acc, s["investigation_id"])
            for f in db.execute(select(Finding).where(Finding.investigation_id == inv.id,
                                                      Finding.status == "confirmed_by_reviewer")).scalars():
                facts.append(f"Confirmed finding '{f.title}': {f.statement[:300]}")
        if s.get("type") == "analysis" and s.get("analysis_run_id"):
            run = db.get(AnalysisRun, s["analysis_run_id"])
            if run and run.project_id == acc.project_id:
                summary = {k: v for k, v in run.result.items() if isinstance(v, (int, float, str)) and k not in {"disclaimer"}}
                facts.append(f"Analysis {run.kind} ({run.algorithm_version}): {summary}")
    res = _wrap(lambda: ai.draft_report_text(ctx, db, r.title, facts))
    audit(ctx, acc, "ai.report_draft", "report", r.id, details={"facts": len(facts)})
    return {**res, "facts": facts}
