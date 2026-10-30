"""Entities, match review, merges, relationships and the knowledge graph."""

from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from project_atlas.analytics.service import record_run, run_view
from project_atlas.api.common import audit, paginate
from project_atlas.api.deps import ProjectAccess, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Conflict, NotFound, ValidationFailed
from project_atlas.database.models import (
    Dataset, Document, DocumentChunk, Entity, EntitySource, Event, GraphSnapshot, MatchCandidate, MergeHistory, QualityIssue,
    Record, Relationship, utcnow,
)
from project_atlas.entities import matching
from project_atlas.entities import service as es
from project_atlas.graph import service as graph
from project_atlas.ontology.service import entity_types, relationship_type_names

router = APIRouter(prefix="/api/projects/{project_id}", tags=["entities", "graph"])


class ReviewBody(BaseModel):
    decision: str = Field(pattern=r"^(accept|reject)$")
    note: str = ""
    survivor_id: str | None = None


class MergeBody(BaseModel):
    survivor_id: str
    merged_id: str
    note: str = ""


class RelationshipCreate(BaseModel):
    source_entity_id: str
    target_entity_id: str
    rel_type: str
    justification: str = Field(min_length=3)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    evidence_refs: list[str] = []


class RelationshipStatus(BaseModel):
    status: str = Field(pattern=r"^(active|rejected)$")
    note: str = ""


class EntityCreate(BaseModel):
    entity_type: str
    display_name: str = Field(min_length=1, max_length=255)
    attributes: dict[str, str] = {}
    justification: str = Field(min_length=3)


class SnapshotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    node_ids: list[str]
    layout: dict = {}
    filters: dict = {}


class AlgorithmBody(BaseModel):
    algorithm: str
    params: dict = {}


class ResolveBody(BaseModel):
    entity_type: str | None = None
    threshold: float = Field(default=0.75, ge=0.5, le=1.0)


def _entity(db: Session, acc: ProjectAccess, entity_id: str) -> Entity:
    e = db.get(Entity, entity_id)
    if e is None or e.project_id != acc.project_id:
        raise NotFound("Entity not found")
    return e


@router.get("/entities")
def list_entities(entity_type: str | None = None, q: str | None = None, status: str = "active", limit: int = 50,
                  offset: int = 0, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("entity.read")
    limit, offset = paginate(limit, offset)
    query = select(Entity).where(Entity.project_id == acc.project_id)
    if status != "all":
        query = query.where(Entity.status == status)
    if entity_type:
        query = query.where(Entity.entity_type == entity_type)
    if q:
        query = query.where(Entity.display_name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.order_by(Entity.display_name).limit(limit).offset(offset)).scalars().all()
    can_s = acc.can("sensitive.read")
    deg = dict(db.execute(select(Relationship.source_entity_id, func.count()).where(
        Relationship.source_entity_id.in_([e.id for e in rows])).group_by(Relationship.source_entity_id)).all())
    for k, v in db.execute(select(Relationship.target_entity_id, func.count()).where(
            Relationship.target_entity_id.in_([e.id for e in rows])).group_by(Relationship.target_entity_id)).all():
        deg[k] = deg.get(k, 0) + v
    return {"total": total, "entities": [{**es.entity_view(db, e, can_s), "relationship_count": deg.get(e.id, 0)} for e in rows]}


@router.post("/entities")
def create_entity(body: EntityCreate, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("entity.write")
    types = entity_types(db, acc.project_id)
    if body.entity_type not in types:
        raise ValidationFailed("Unknown entity type")
    allowed = {f["name"] for f in types[body.entity_type].fields}
    bad = set(body.attributes) - allowed
    if bad:
        raise ValidationFailed(f"Fields not defined in ontology: {sorted(bad)}")
    e = Entity(project_id=acc.project_id, entity_type=body.entity_type, display_name=body.display_name,
               attributes={k: [{"value": v, "normalized": v.strip(), "record_id": None, "dataset_version_id": None,
                                "asserted_by": acc.principal.id, "justification": body.justification}]
                           for k, v in {"name": body.display_name, **body.attributes}.items()})
    db.add(e)
    db.flush()
    es.reindex_entity(db, e)
    db.commit()
    audit(ctx, acc, "entity.create_manual", "entity", e.id, details={"justification": body.justification})
    return es.entity_view(db, e, acc.can("sensitive.read"))


@router.get("/entities/{entity_id}")
def entity_detail(entity_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("entity.read")
    e = _entity(db, acc, entity_id)
    can_s = acc.can("sensitive.read")
    view = es.entity_view(db, e, can_s, detail=True)
    srcs = db.execute(select(Record, Dataset).join(EntitySource, EntitySource.record_id == Record.id)
                      .join(Dataset, Dataset.id == Record.dataset_id).where(EntitySource.entity_id == e.id)).all()
    view["source_records"] = [{"record_id": r.id, "dataset_id": d.id, "dataset_name": d.name, "row_index": r.row_index,
                               "restricted": d.access_policy == "restricted" and not acc.can("dataset.read_restricted")}
                              for r, d in srcs]
    rels = db.execute(select(Relationship).where(Relationship.project_id == acc.project_id, or_(
        Relationship.source_entity_id == e.id, Relationship.target_entity_id == e.id))).scalars().all()
    others = {x.id: x for x in db.execute(select(Entity).where(Entity.id.in_(
        {r.source_entity_id for r in rels} | {r.target_entity_id for r in rels}))).scalars()}
    view["relationships"] = [{**graph.edge_view(r), "evidence": r.evidence, "created_by": r.created_by,
                              "created_at": r.created_at, "valid_from": r.valid_from, "valid_to": r.valid_to,
                              "other": {"id": o.id, "display_name": o.display_name, "entity_type": o.entity_type}
                              if (o := others.get(r.target_entity_id if r.source_entity_id == e.id else r.source_entity_id)) else None,
                              "direction": "out" if r.source_entity_id == e.id else "in"} for r in rels]
    view["merge_history"] = [{"id": m.id, "survivor_id": m.survivor_id, "merged_id": m.merged_id,
                              "performed_by": m.performed_by, "performed_at": m.performed_at,
                              "reverted_at": m.reverted_at, "candidate_id": m.candidate_id}
                             for m in db.execute(select(MergeHistory).where(or_(MergeHistory.survivor_id == e.id,
                                                                                MergeHistory.merged_id == e.id))
                                                 .order_by(MergeHistory.performed_at)).scalars()]
    rec_ids = [s["record_id"] for s in view["source_records"]]
    view["quality_warnings"] = [{"check": q.check, "field": q.field, "message": q.message, "row_index": q.row_index}
                                for q in db.execute(select(QualityIssue).join(Record, (Record.dataset_version_id == QualityIssue.dataset_version_id)
                                                                              & (Record.row_index == QualityIssue.row_index))
                                                    .where(Record.id.in_(rec_ids))).scalars()] if rec_ids else []
    view["events"] = [{"id": ev.id, "title": ev.title, "event_time": ev.event_time, "category": ev.category}
                      for ev in db.execute(select(Event).where(Event.entity_id == e.id).order_by(Event.event_time).limit(100)).scalars()]
    # linked documents: chunks mentioning the entity name (deterministic string match)
    name = e.display_name
    docs = db.execute(select(Document.id, Document.title, func.min(DocumentChunk.page)).join(DocumentChunk, DocumentChunk.document_id == Document.id)
                      .where(Document.project_id == acc.project_id, DocumentChunk.text.ilike(f"%{name}%"))
                      .group_by(Document.id, Document.title).limit(20)).all() if len(name) >= 3 else []
    view["linked_documents"] = [{"document_id": d, "title": t, "first_page": pg, "link_method": "exact name mention"} for d, t, pg in docs]
    return view


@router.post("/entities/resolve")
def start_resolution(body: ResolveBody, acc: ProjectAccess = Depends(project_access), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("entity.resolve")
    job = ctx.jobs.create(kind="entity_resolution", project_id=acc.project_id, user_id=acc.principal.id,
                          params=body.model_dump())
    audit(ctx, acc, "entity.resolution_started", "job", job.id, details=body.model_dump())
    from project_atlas.api.data import job_view

    return job_view(job)


@router.get("/match-candidates")
def list_candidates(status: str = "pending", band: str | None = None, limit: int = 50, offset: int = 0,
                    acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("entity.read")
    limit, offset = paginate(limit, offset)
    q = select(MatchCandidate).where(MatchCandidate.project_id == acc.project_id)
    if status != "all":
        q = q.where(MatchCandidate.status == status)
    if band:
        q = q.where(MatchCandidate.band == band)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(MatchCandidate.score.desc()).limit(limit).offset(offset)).scalars().all()
    ids = {c.entity_a_id for c in rows} | {c.entity_b_id for c in rows}
    ents = {e.id: e for e in db.execute(select(Entity).where(Entity.id.in_(ids))).scalars()}
    can_s = acc.can("sensitive.read")
    hidden = set() if can_s else set().union(*[set(f["name"] for f in t.fields if f.get("sensitive"))
                                               for t in entity_types(db, acc.project_id).values()])

    def ev(c: MatchCandidate):
        e = dict(c.evidence)
        e["features"] = [{**f, "a": "[restricted]", "b": "[restricted]"} if f["feature"] in hidden else f
                         for f in e.get("features", [])]
        return e

    return {"total": total, "candidates": [
        {"id": c.id, "entity_type": c.entity_type, "score": c.score, "band": c.band, "status": c.status,
         "algorithm_version": c.algorithm_version, "evidence": ev(c), "review_note": c.review_note,
         "reviewed_by": c.reviewed_by, "reviewed_at": c.reviewed_at,
         "entity_a": es.entity_view(db, ents[c.entity_a_id], can_s) if c.entity_a_id in ents else None,
         "entity_b": es.entity_view(db, ents[c.entity_b_id], can_s) if c.entity_b_id in ents else None}
        for c in rows]}


@router.post("/match-candidates/{candidate_id}/review")
def review_candidate(candidate_id: str, body: ReviewBody, acc: ProjectAccess = Depends(project_access),
                     db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("entity.review")
    c = db.get(MatchCandidate, candidate_id)
    if c is None or c.project_id != acc.project_id:
        raise NotFound("Candidate not found")
    if c.status != "pending":
        raise Conflict(f"Candidate already {c.status}")
    c.reviewed_by, c.reviewed_at, c.review_note = acc.principal.id, utcnow(), body.note
    merge_id = None
    if body.decision == "accept":
        survivor = body.survivor_id or c.entity_a_id
        if survivor not in {c.entity_a_id, c.entity_b_id}:
            raise ValidationFailed("survivor_id must be one of the candidate entities")
        merged = c.entity_b_id if survivor == c.entity_a_id else c.entity_a_id
        mh = es.merge(db, acc.project_id, survivor, merged, acc.principal.id, candidate_id=c.id)
        merge_id = mh.id
        c.status = "accepted"
    else:
        c.status = "rejected"
    db.commit()
    audit(ctx, acc, f"entity.match_{c.status}", "match_candidate", c.id,
          details={"score": c.score, "band": c.band, "merge_id": merge_id, "note": body.note})
    return {"status": c.status, "merge_id": merge_id}


@router.post("/entities/merge")
def manual_merge(body: MergeBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    acc.require("entity.review")
    if len(body.note.strip()) < 3:
        raise ValidationFailed("A justification note is required for manual merges")
    a, b = _entity(db, acc, body.survivor_id), _entity(db, acc, body.merged_id)
    preview = matching.compare(es.entity_features(a), es.entity_features(b),
                               {f["name"] for f in entity_types(db, acc.project_id)[a.entity_type].fields if f.get("identifier")})
    mh = es.merge(db, acc.project_id, a.id, b.id, acc.principal.id)
    db.commit()
    audit(ctx, acc, "entity.merge_manual", "entity", a.id, details={"merged_id": b.id, "merge_id": mh.id,
                                                                    "score": preview["score"], "note": body.note})
    return {"merge_id": mh.id, "comparison": preview}


@router.get("/merges")
def list_merges(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("entity.read")
    rows = db.execute(select(MergeHistory).where(MergeHistory.project_id == acc.project_id)
                      .order_by(MergeHistory.performed_at.desc()).limit(200)).scalars().all()
    return [{"id": m.id, "survivor_id": m.survivor_id, "merged_id": m.merged_id, "candidate_id": m.candidate_id,
             "performed_by": m.performed_by, "performed_at": m.performed_at, "reverted_at": m.reverted_at,
             "merged_name": m.snapshot.get("merged_entity", {}).get("display_name")} for m in rows]


@router.post("/merges/{merge_id}/revert")
def revert(merge_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
           ctx: AtlasContext = Depends(get_ctx)):
    acc.require("entity.review")
    mh = es.revert_merge(db, acc.project_id, merge_id, acc.principal.id)
    db.commit()
    audit(ctx, acc, "entity.merge_reverted", "merge", mh.id, details={"survivor_id": mh.survivor_id, "merged_id": mh.merged_id})
    return {"ok": True}


# --------------------------------------------------------------------------- relationships


@router.post("/relationships")
def create_relationship(body: RelationshipCreate, acc: ProjectAccess = Depends(project_access),
                        db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("graph.write")
    s, t = _entity(db, acc, body.source_entity_id), _entity(db, acc, body.target_entity_id)
    if s.status != "active" or t.status != "active":
        raise Conflict("Both entities must be active")
    if body.rel_type not in relationship_type_names(db, acc.project_id):
        raise ValidationFailed("Unknown relationship type")
    r = Relationship(project_id=acc.project_id, source_entity_id=s.id, target_entity_id=t.id, rel_type=body.rel_type,
                     assertion="manual", status="active", confidence=None,
                     evidence={"justification": body.justification, "evidence_refs": body.evidence_refs,
                               "asserted_by": acc.principal.id},
                     valid_from=body.valid_from, valid_to=body.valid_to, created_by=acc.principal.id)
    db.add(r)
    db.commit()
    audit(ctx, acc, "relationship.create_manual", "relationship", r.id, details={"rel_type": r.rel_type})
    return graph.edge_view(r)


@router.get("/relationships/{rel_id}")
def relationship_detail(rel_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("graph.read")
    r = db.get(Relationship, rel_id)
    if r is None or r.project_id != acc.project_id:
        raise NotFound("Relationship not found")
    recs = []
    for rid in (r.evidence or {}).get("records", [])[:50]:
        rec = db.get(Record, rid)
        if rec:
            ds = db.get(Dataset, rec.dataset_id)
            recs.append({"record_id": rid, "dataset": ds.name if ds else None, "row_index": rec.row_index})
    s, t = db.get(Entity, r.source_entity_id), db.get(Entity, r.target_entity_id)
    return {**graph.edge_view(r), "evidence": r.evidence, "evidence_records": recs, "created_by": r.created_by,
            "created_at": r.created_at, "valid_from": r.valid_from, "valid_to": r.valid_to,
            "source": {"id": s.id, "display_name": s.display_name, "entity_type": s.entity_type},
            "target": {"id": t.id, "display_name": t.display_name, "entity_type": t.entity_type},
            "how_created": graph.ASSERTION_LABELS.get(r.assertion)}


@router.patch("/relationships/{rel_id}")
def set_relationship_status(rel_id: str, body: RelationshipStatus, acc: ProjectAccess = Depends(project_access),
                            db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    """Reviewers verify (activate) or reject relationships, e.g. model-suggested hypotheses."""
    acc.require("entity.review")
    r = db.get(Relationship, rel_id)
    if r is None or r.project_id != acc.project_id:
        raise NotFound("Relationship not found")
    old = r.status
    r.status = body.status
    r.evidence = {**r.evidence, "review": {"by": acc.principal.id, "at": utcnow().isoformat(), "note": body.note,
                                           "from": old, "to": body.status}}
    db.commit()
    audit(ctx, acc, "relationship.status_changed", "relationship", r.id, details={"from": old, "to": body.status})
    return graph.edge_view(r)


# --------------------------------------------------------------------------- graph


@router.get("/graph")
def get_graph(center: str | None = None, depth: int = 1, limit: int = 300,
              entity_types_: list[str] | None = Query(None, alias="entity_type"),
              rel_types: list[str] | None = Query(None, alias="rel_type"),
              assertions: list[str] | None = Query(None, alias="assertion"), include_unverified: bool = False,
              acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
              ctx: AtlasContext = Depends(get_ctx)):
    acc.require("graph.read")
    limit = max(1, min(limit, ctx.settings.graph_node_limit))
    return graph.neighborhood(db, acc.project_id, center=center, depth=depth, limit=limit, entity_types=entity_types_,
                              rel_types=rel_types, assertions=assertions, include_unverified=include_unverified)


@router.post("/graph/analyze")
def analyze_graph(body: AlgorithmBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("analysis.run")
    t0 = time.perf_counter()
    result, inputs = graph.run_algorithm(db, acc.project_id, body.algorithm, body.params)
    run = record_run(db, project_id=acc.project_id, kind=f"graph.{body.algorithm}", params=body.params, inputs=inputs,
                     algorithm_version=graph.ALGORITHM_VERSION, result=result, started=t0, user_id=acc.principal.id)
    audit(ctx, acc, "analysis.run", "analysis_run", run.id, details={"kind": run.kind})
    return run_view(run)


@router.get("/graph/snapshots")
def list_snapshots(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("graph.read")
    rows = db.execute(select(GraphSnapshot).where(GraphSnapshot.project_id == acc.project_id)
                      .order_by(GraphSnapshot.created_at.desc())).scalars().all()
    return [{"id": s.id, "name": s.name, "nodes": len(s.node_ids), "edges": len(s.edge_ids), "created_at": s.created_at,
             "created_by": s.created_by} for s in rows]


@router.post("/graph/snapshots")
def create_snapshot(body: SnapshotCreate, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                    ctx: AtlasContext = Depends(get_ctx)):
    acc.require("graph.write")
    ents = set(db.execute(select(Entity.id).where(Entity.project_id == acc.project_id, Entity.id.in_(body.node_ids))).scalars())
    if not ents:
        raise ValidationFailed("Snapshot needs at least one entity of this project")
    edges = list(db.execute(select(Relationship.id).where(Relationship.project_id == acc.project_id,
                                                         Relationship.source_entity_id.in_(ents),
                                                         Relationship.target_entity_id.in_(ents),
                                                         Relationship.status != "rejected")).scalars())
    s = GraphSnapshot(project_id=acc.project_id, name=body.name, node_ids=sorted(ents), edge_ids=sorted(edges),
                      layout=body.layout, filters=body.filters, created_by=acc.principal.id)
    db.add(s)
    db.commit()
    audit(ctx, acc, "graph.snapshot_created", "graph_snapshot", s.id, details={"nodes": len(ents), "edges": len(edges)})
    return {"id": s.id, "nodes": len(ents), "edges": len(edges)}


@router.get("/graph/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("graph.read")
    s = db.get(GraphSnapshot, snapshot_id)
    if s is None or s.project_id != acc.project_id:
        raise NotFound("Snapshot not found")
    ents = db.execute(select(Entity).where(Entity.id.in_(s.node_ids))).scalars().all()
    rels = db.execute(select(Relationship).where(Relationship.id.in_(s.edge_ids))).scalars().all()
    return {"id": s.id, "name": s.name, "layout": s.layout, "filters": s.filters, "created_at": s.created_at,
            "nodes": [graph.node_view(e) for e in ents], "edges": [graph.edge_view(r) for r in rels]}


@router.post("/graph/export")
def export_graph(body: SnapshotCreate, fmt: str = "graphml", acc: ProjectAccess = Depends(project_access),
                 db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("report.export")
    data, media = graph.export_subgraph(db, acc.project_id, body.node_ids, fmt)
    audit(ctx, acc, "export.graph", "graph", None, details={"format": fmt, "nodes": len(body.node_ids), "name": body.name})
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="atlas-subgraph.{fmt}"'})


@router.get("/graph/explain")
def explain_connection(source: str, target: str, max_paths: int = 3, include_unverified: bool = False,
                       acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                       ctx: AtlasContext = Depends(get_ctx)):
    """How are two entities connected? Shortest paths with the relationships and source evidence behind every hop."""
    import networkx as nx

    from project_atlas.api.common import can_read_dataset, redact_record
    from project_atlas.database.models import DatasetVersion

    acc.require("graph.read")
    a, b = _entity(db, acc, source), _entity(db, acc, target)
    t0 = time.perf_counter()
    g = graph.build_graph(db, acc.project_id, include_unverified=include_unverified)
    if a.id not in g or b.id not in g:
        raise ValidationFailed("Both entities must be active")
    ug = nx.Graph(g)
    try:
        paths = list(nx.all_shortest_paths(ug, a.id, b.id))[: max(1, min(max_paths, 10))]
    except nx.NetworkXNoPath:
        paths = []
    labels = nx.get_node_attributes(g, "label")
    datasets: dict[str, Dataset | None] = {}
    versions: dict[str, DatasetVersion | None] = {}

    def evidence_sample(r: Relationship) -> dict | None:
        rid = (r.evidence or {}).get("records", [None])[0] if (r.evidence or {}).get("records") else r.record_id
        rec = db.get(Record, rid) if rid else None
        if rec is None:
            return {"kind": "assertion", "text": (r.evidence or {}).get("justification") or (r.evidence or {}).get("quote")}
        ds = datasets.setdefault(rec.dataset_id, db.get(Dataset, rec.dataset_id))
        if ds is None or not can_read_dataset(acc, ds):
            return {"kind": "record", "restricted": True}
        dv = versions.setdefault(rec.dataset_version_id, db.get(DatasetVersion, rec.dataset_version_id))
        hidden = set() if acc.can("sensitive.read") else {f["name"] for f in dv.schema_json["fields"] if f.get("sensitive")}
        vals = redact_record(rec.normalized, hidden)
        return {"kind": "record", "record_id": rec.id, "dataset": ds.name, "row_index": rec.row_index,
                "text": "; ".join(f"{k}={v}" for k, v in vals.items() if v not in (None, ""))[:400]}

    out = []
    for p in paths:
        hops = []
        for u, v in zip(p, p[1:]):
            keys = [k for k in g.get_edge_data(u, v, default={})] + [k for k in g.get_edge_data(v, u, default={})]
            rels = db.execute(select(Relationship).where(Relationship.id.in_(keys))).scalars().all()
            hops.append({"from": {"id": u, "label": labels.get(u)}, "to": {"id": v, "label": labels.get(v)},
                         "relationships": [{**graph.edge_view(r), "valid_from": r.valid_from, "valid_to": r.valid_to,
                                            "evidence_sample": evidence_sample(r)} for r in rels]})
        bases = {rel["assertion"] for h in hops for rel in h["relationships"]}
        out.append({"length": len(p) - 1, "nodes": [{"id": n, "label": labels.get(n)} for n in p], "hops": hops,
                    "bases": sorted(bases),
                    "all_observed": bases == {"observed"}})
    audit(ctx, acc, "graph.explain", "entity", a.id, details={"target": b.id, "paths": len(out)})
    return {"source": {"id": a.id, "label": a.display_name}, "target": {"id": b.id, "label": b.display_name},
            "found": bool(out), "paths": out, "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "note": "A path shows recorded links only. It does not establish intent, knowledge or wrongdoing; "
                    "check each hop's basis and evidence."}
