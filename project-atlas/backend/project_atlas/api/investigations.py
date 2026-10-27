"""Investigation workspaces: scope, collaborators, linked items, notes, evidence and findings.

Access: project members with ``investigation.read`` see an investigation only if they created it,
are a listed collaborator, or are a project administrator. Evidence is stored independently from
findings and keeps a full revision history.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from project_atlas.api.common import audit, get_dataset
from project_atlas.api.deps import ProjectAccess, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from project_atlas.database.models import (
    AnalysisRun, Dataset, Document, DocumentChunk, Entity, Evidence, EvidenceRevision, Finding, FindingEvidence,
    GraphSnapshot, Investigation, InvestigationCollaborator, InvestigationItem, Note, ProjectMember, Record, Relationship,
    SavedQuery, utcnow,
)
from project_atlas.search import service as search

router = APIRouter(prefix="/api/projects/{project_id}/investigations", tags=["investigations"])

FINDING_STATES = ["draft", "under_review", "confirmed_by_reviewer", "disputed", "rejected", "superseded"]
TRANSITIONS = {
    "draft": {"under_review"},
    "under_review": {"confirmed_by_reviewer", "disputed", "rejected", "draft"},
    "disputed": {"under_review", "rejected", "superseded"},
    "confirmed_by_reviewer": {"superseded", "disputed"},
    "rejected": {"draft"},
    "superseded": set(),
}
REVIEW_STATES = {"confirmed_by_reviewer", "disputed", "rejected"}
ITEM_TYPES = {"dataset", "entity", "saved_query", "graph_snapshot", "analysis_run", "document", "timeline_view", "map_view", "report"}


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    objective: str = ""
    scope: str = ""
    classification: str = Field(default="internal", pattern=r"^(public|internal|confidential|restricted)$")


class InvestigationPatch(BaseModel):
    objective: str | None = None
    scope: str | None = None
    status: str | None = Field(default=None, pattern=r"^(open|closed|archived)$")


class ItemBody(BaseModel):
    item_type: str
    ref_id: str = Field(max_length=64)
    label: str = ""


class NoteBody(BaseModel):
    body: str = Field(min_length=1, max_length=20000)


class EvidenceBody(BaseModel):
    source_type: str = Field(pattern=r"^(record|document_chunk|entity|relationship|analysis_run)$")
    source_ref: str
    excerpt: str | None = Field(default=None, max_length=5000)
    classification: str = "internal"


class EvidencePatch(BaseModel):
    excerpt: str | None = Field(default=None, max_length=5000)
    classification: str | None = None


class FindingBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    statement: str = Field(min_length=1, max_length=20000)
    basis: str = Field(default="analyst_assessment", pattern=r"^(direct_evidence|deterministic_calculation|analyst_assessment|model_hypothesis)$")


class FindingStatus(BaseModel):
    status: str
    note: str = ""
    superseded_by_id: str | None = None


class LinkEvidence(BaseModel):
    evidence_id: str
    stance: str = Field(pattern=r"^(supporting|contradicting)$")


def _inv(db: Session, acc: ProjectAccess, inv_id: str, write: bool = False) -> Investigation:
    inv = db.get(Investigation, inv_id)
    if inv is None or inv.project_id != acc.project_id:
        raise NotFound("Investigation not found")
    collab = db.execute(select(InvestigationCollaborator).where(InvestigationCollaborator.investigation_id == inv.id,
                                                                InvestigationCollaborator.user_id == acc.principal.id)).scalar_one_or_none()
    if not (inv.created_by == acc.principal.id or collab or acc.role == "project_admin"):
        raise NotFound("Investigation not found")
    acc.require("investigation.write" if write else "investigation.read")
    if write and inv.status != "open":
        raise Conflict("Investigation is not open")
    return inv


def inv_view(i: Investigation) -> dict:
    return {"id": i.id, "title": i.title, "objective": i.objective, "scope": i.scope, "status": i.status,
            "classification": i.classification, "created_by": i.created_by, "created_at": i.created_at}


@router.get("")
def list_investigations(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("investigation.read")
    q = select(Investigation).where(Investigation.project_id == acc.project_id)
    if acc.role != "project_admin":
        q = q.where(or_(Investigation.created_by == acc.principal.id, Investigation.id.in_(
            select(InvestigationCollaborator.investigation_id).where(InvestigationCollaborator.user_id == acc.principal.id))))
    return [inv_view(i) for i in db.execute(q.order_by(Investigation.created_at.desc())).scalars()]


@router.post("")
def create_investigation(body: InvestigationCreate, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                         ctx: AtlasContext = Depends(get_ctx)):
    acc.require("investigation.create")
    inv = Investigation(project_id=acc.project_id, created_by=acc.principal.id, **body.model_dump())
    db.add(inv)
    db.flush()
    db.add(InvestigationCollaborator(investigation_id=inv.id, user_id=acc.principal.id))
    search.index_item(db, doc_type="investigation", ref_id=inv.id, project_id=acc.project_id, title=inv.title,
                      body=f"{inv.objective} {inv.scope}", access="restricted" if inv.classification == "restricted" else "project")
    db.commit()
    audit(ctx, acc, "investigation.create", "investigation", inv.id, details={"title": inv.title})
    return inv_view(inv)


@router.get("/{inv_id}")
def get_investigation(inv_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    inv = _inv(db, acc, inv_id)
    collabs = db.execute(select(InvestigationCollaborator.user_id).where(InvestigationCollaborator.investigation_id == inv.id)).scalars().all()
    items = db.execute(select(InvestigationItem).where(InvestigationItem.investigation_id == inv.id)).scalars().all()
    notes = db.execute(select(Note).where(Note.investigation_id == inv.id).order_by(Note.created_at)).scalars().all()
    evid = db.execute(select(Evidence).where(Evidence.investigation_id == inv.id).order_by(Evidence.captured_at)).scalars().all()
    finds = db.execute(select(Finding).where(Finding.investigation_id == inv.id).order_by(Finding.created_at)).scalars().all()
    links = db.execute(select(FindingEvidence).where(FindingEvidence.finding_id.in_([f.id for f in finds]))).scalars().all() if finds else []
    return {**inv_view(inv), "collaborators": list(collabs),
            "items": [{"id": i.id, "item_type": i.item_type, "ref_id": i.ref_id, "label": i.label, "added_at": i.added_at} for i in items],
            "notes": [{"id": n.id, "body": n.body, "author_id": n.author_id, "created_at": n.created_at} for n in notes],
            "evidence": [evidence_view(e) for e in evid],
            "findings": [{**finding_view(f), "supporting": [l.evidence_id for l in links if l.finding_id == f.id and l.stance == "supporting"],
                          "contradicting": [l.evidence_id for l in links if l.finding_id == f.id and l.stance == "contradicting"]}
                         for f in finds],
            "finding_states": FINDING_STATES}


@router.patch("/{inv_id}")
def patch_investigation(inv_id: str, body: InvestigationPatch, acc: ProjectAccess = Depends(project_access),
                        db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id)
    acc.require("investigation.write")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(inv, k, v)
    db.commit()
    audit(ctx, acc, "investigation.update", "investigation", inv.id, details=body.model_dump(exclude_none=True))
    return inv_view(inv)


@router.put("/{inv_id}/collaborators/{user_id}")
def add_collaborator(inv_id: str, user_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                     ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id, write=True)
    if inv.created_by != acc.principal.id and acc.role != "project_admin":
        raise Forbidden("Only the investigation owner or a project administrator can add collaborators")
    member = db.execute(select(ProjectMember).where(ProjectMember.project_id == acc.project_id,
                                                    ProjectMember.user_id == user_id)).scalar_one_or_none()
    if member is None:
        raise ValidationFailed("Collaborators must be members of the project")
    if not db.execute(select(InvestigationCollaborator).where(InvestigationCollaborator.investigation_id == inv.id,
                                                              InvestigationCollaborator.user_id == user_id)).scalar_one_or_none():
        db.add(InvestigationCollaborator(investigation_id=inv.id, user_id=user_id))
        db.commit()
    audit(ctx, acc, "investigation.collaborator_added", "investigation", inv.id, details={"user_id": user_id})
    return {"ok": True}


def _check_ref(db: Session, acc: ProjectAccess, item_type: str, ref_id: str) -> str:
    model = {"dataset": Dataset, "entity": Entity, "saved_query": SavedQuery, "graph_snapshot": GraphSnapshot,
             "analysis_run": AnalysisRun, "document": Document}.get(item_type)
    if model is None:
        return ref_id
    obj = db.get(model, ref_id)
    if obj is None or getattr(obj, "project_id", None) != acc.project_id:
        raise NotFound(f"{item_type} not found")
    if item_type == "dataset":
        get_dataset(db, acc, ref_id)
    return getattr(obj, "name", None) or getattr(obj, "display_name", None) or getattr(obj, "title", None) or ref_id


@router.post("/{inv_id}/items")
def add_item(inv_id: str, body: ItemBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
             ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id, write=True)
    if body.item_type not in ITEM_TYPES:
        raise ValidationFailed(f"item_type must be one of {sorted(ITEM_TYPES)}")
    label = body.label or _check_ref(db, acc, body.item_type, body.ref_id)
    it = InvestigationItem(investigation_id=inv.id, item_type=body.item_type, ref_id=body.ref_id, label=label[:255],
                           added_by=acc.principal.id)
    db.add(it)
    db.commit()
    audit(ctx, acc, "investigation.item_added", "investigation", inv.id, details={"item_type": body.item_type, "ref_id": body.ref_id})
    return {"id": it.id}


@router.post("/{inv_id}/notes")
def add_note(inv_id: str, body: NoteBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    inv = _inv(db, acc, inv_id, write=True)
    n = Note(investigation_id=inv.id, body=body.body, author_id=acc.principal.id)
    db.add(n)
    db.commit()
    return {"id": n.id}


# --------------------------------------------------------------------------- evidence


def evidence_view(e: Evidence) -> dict:
    return {"id": e.id, "source_type": e.source_type, "source_ref": e.source_ref, "excerpt": e.excerpt, "location": e.location,
            "classification": e.classification, "provenance": e.provenance, "revision": e.revision,
            "captured_by": e.captured_by, "captured_at": e.captured_at}


def _resolve_source(db: Session, acc: ProjectAccess, source_type: str, ref: str) -> tuple[str, dict, dict]:
    """Return (default excerpt, location, provenance) after verifying the caller may see the source."""
    if source_type == "record":
        r = db.get(Record, ref)
        if r is None or r.project_id != acc.project_id:
            raise NotFound("Record not found")
        ds = get_dataset(db, acc, r.dataset_id)
        from project_atlas.database.models import DatasetVersion

        dv = db.get(DatasetVersion, r.dataset_version_id)
        hidden = {f["name"] for f in dv.schema_json["fields"] if f.get("sensitive")} if not acc.can("sensitive.read") else set()
        excerpt = "; ".join(f"{k}={v}" for k, v in r.normalized.items() if v is not None and k not in hidden)
        return excerpt, {"row_index": r.row_index}, {"dataset_id": ds.id, "dataset_name": ds.name, "dataset_version_id": dv.id,
                                                      "version": dv.version, "row_hash": r.row_hash, "source_file_id": dv.file_id}
    if source_type == "document_chunk":
        c = db.get(DocumentChunk, ref)
        d = db.get(Document, c.document_id) if c else None
        if c is None or d is None or d.project_id != acc.project_id:
            raise NotFound("Document passage not found")
        return c.text[:2000], {"page": c.page, "chunk_index": c.chunk_index, "char_start": c.char_start,
                               "page_label": d.metadata_json.get("page_label", "page")}, \
            {"document_id": d.id, "title": d.title, "sha256": d.sha256, "file_id": d.file_id}
    if source_type == "entity":
        e = db.get(Entity, ref)
        if e is None or e.project_id != acc.project_id:
            raise NotFound("Entity not found")
        return f"{e.display_name} ({e.entity_type})", {}, {"entity_id": e.id, "status": e.status}
    if source_type == "relationship":
        r = db.get(Relationship, ref)
        if r is None or r.project_id != acc.project_id:
            raise NotFound("Relationship not found")
        return f"{r.rel_type}: {r.source_entity_id} -> {r.target_entity_id}", {}, \
            {"assertion": r.assertion, "status": r.status, "evidence": r.evidence}
    if source_type == "analysis_run":
        a = db.get(AnalysisRun, ref)
        if a is None or a.project_id != acc.project_id:
            raise NotFound("Analysis run not found")
        return f"{a.kind} result {a.result_sha256[:12]}", {}, {"kind": a.kind, "inputs": a.inputs, "params": a.params,
                                                               "algorithm_version": a.algorithm_version,
                                                               "result_sha256": a.result_sha256}
    raise ValidationFailed("Unknown source type")


@router.post("/{inv_id}/evidence")
def add_evidence(inv_id: str, body: EvidenceBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id, write=True)
    acc.require("evidence.write")
    default_excerpt, loc, prov = _resolve_source(db, acc, body.source_type, body.source_ref)
    excerpt = body.excerpt or default_excerpt
    if body.excerpt and body.source_type == "document_chunk" and body.excerpt not in default_excerpt:
        raise ValidationFailed("Excerpt must be verbatim text from the referenced passage")
    e = Evidence(investigation_id=inv.id, source_type=body.source_type, source_ref=body.source_ref, excerpt=excerpt,
                 location=loc, classification=body.classification, provenance=prov, captured_by=acc.principal.id)
    db.add(e)
    db.flush()
    db.add(EvidenceRevision(evidence_id=e.id, revision=1, snapshot=evidence_view(e) | {"captured_at": str(e.captured_at)},
                            changed_by=acc.principal.id))
    db.commit()
    audit(ctx, acc, "evidence.capture", "evidence", e.id, details={"source_type": e.source_type, "source_ref": e.source_ref})
    return evidence_view(e)


@router.patch("/{inv_id}/evidence/{evidence_id}")
def edit_evidence(inv_id: str, evidence_id: str, body: EvidencePatch, acc: ProjectAccess = Depends(project_access),
                  db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id, write=True)
    e = db.get(Evidence, evidence_id)
    if e is None or e.investigation_id != inv.id:
        raise NotFound("Evidence not found")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(e, k, v)
    e.revision += 1
    db.add(EvidenceRevision(evidence_id=e.id, revision=e.revision, snapshot={**evidence_view(e), "captured_at": str(e.captured_at)},
                            changed_by=acc.principal.id))
    db.commit()
    audit(ctx, acc, "evidence.revise", "evidence", e.id, details={"revision": e.revision, "fields": sorted(changes)})
    return evidence_view(e)


@router.get("/{inv_id}/evidence/{evidence_id}/revisions")
def evidence_revisions(inv_id: str, evidence_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    inv = _inv(db, acc, inv_id)
    e = db.get(Evidence, evidence_id)
    if e is None or e.investigation_id != inv.id:
        raise NotFound("Evidence not found")
    revs = db.execute(select(EvidenceRevision).where(EvidenceRevision.evidence_id == e.id).order_by(EvidenceRevision.revision)).scalars()
    return [{"revision": r.revision, "snapshot": r.snapshot, "changed_by": r.changed_by, "changed_at": r.changed_at} for r in revs]


# --------------------------------------------------------------------------- findings


def finding_view(f: Finding) -> dict:
    return {"id": f.id, "title": f.title, "statement": f.statement, "status": f.status, "basis": f.basis,
            "revision": f.revision, "history": f.history, "superseded_by_id": f.superseded_by_id,
            "created_by": f.created_by, "reviewed_by": f.reviewed_by, "created_at": f.created_at}


@router.post("/{inv_id}/findings")
def add_finding(inv_id: str, body: FindingBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id, write=True)
    acc.require("finding.write")
    f = Finding(investigation_id=inv.id, created_by=acc.principal.id, **body.model_dump(),
                history=[{"at": utcnow().isoformat(), "by": acc.principal.id, "status": "draft", "note": "created"}])
    db.add(f)
    db.commit()
    audit(ctx, acc, "finding.create", "finding", f.id, details={"basis": f.basis})
    return finding_view(f)


@router.post("/{inv_id}/findings/{finding_id}/evidence")
def link_evidence(inv_id: str, finding_id: str, body: LinkEvidence, acc: ProjectAccess = Depends(project_access),
                  db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id, write=True)
    f, e = db.get(Finding, finding_id), db.get(Evidence, body.evidence_id)
    if f is None or f.investigation_id != inv.id or e is None or e.investigation_id != inv.id:
        raise NotFound("Finding or evidence not found")
    existing = db.execute(select(FindingEvidence).where(FindingEvidence.finding_id == f.id,
                                                        FindingEvidence.evidence_id == e.id)).scalar_one_or_none()
    if existing:
        existing.stance = body.stance
    else:
        db.add(FindingEvidence(finding_id=f.id, evidence_id=e.id, stance=body.stance))
    db.commit()
    audit(ctx, acc, "finding.evidence_linked", "finding", f.id, details={"evidence_id": e.id, "stance": body.stance})
    return {"ok": True}


@router.post("/{inv_id}/findings/{finding_id}/status")
def finding_status(inv_id: str, finding_id: str, body: FindingStatus, acc: ProjectAccess = Depends(project_access),
                   db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    inv = _inv(db, acc, inv_id, write=True)
    f = db.get(Finding, finding_id)
    if f is None or f.investigation_id != inv.id:
        raise NotFound("Finding not found")
    if body.status not in TRANSITIONS.get(f.status, set()):
        raise ValidationFailed(f"Cannot move finding from {f.status} to {body.status}")
    if body.status in REVIEW_STATES:
        acc.require("finding.review")
        if f.created_by == acc.principal.id:
            raise Forbidden("A finding must be reviewed by someone other than its author")
        if body.status == "confirmed_by_reviewer":
            n_support = db.execute(select(FindingEvidence).where(FindingEvidence.finding_id == f.id,
                                                                 FindingEvidence.stance == "supporting")).first()
            if not n_support:
                raise ValidationFailed("A finding needs at least one supporting evidence item before confirmation")
        f.reviewed_by = acc.principal.id
    if body.status == "superseded":
        if not body.superseded_by_id:
            raise ValidationFailed("superseded_by_id is required")
        nxt = db.get(Finding, body.superseded_by_id)
        if nxt is None or nxt.investigation_id != inv.id or nxt.id == f.id:
            raise ValidationFailed("superseded_by_id must reference another finding in this investigation")
        f.superseded_by_id = nxt.id
    f.history = f.history + [{"at": utcnow().isoformat(), "by": acc.principal.id, "from": f.status, "status": body.status,
                              "note": body.note}]
    f.status = body.status
    f.revision += 1
    db.commit()
    audit(ctx, acc, "finding.status_changed", "finding", f.id, details={"to": body.status})
    return finding_view(f)
