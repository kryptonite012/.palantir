"""Entities: creation from records, views with field-level redaction, resolution and reversible merges."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from project_atlas.core.errors import Conflict, NotFound, ValidationFailed
from project_atlas.database.models import (
    Entity, EntitySource, Event, GeoFeature, MatchCandidate, MergeHistory, Relationship, utcnow,
)
from project_atlas.entities import matching
from project_atlas.ontology.service import entity_types, sensitive_fields
from project_atlas.search import service as search

REDACTED = "[restricted]"


def identity_key(entity_type: str, id_field: str | None, value: Any) -> str | None:
    if not id_field or value in (None, ""):
        return None
    return f"{entity_type}:{id_field}:{str(value).strip().lower()}"


def add_attribute_values(entity: Entity, values: dict[str, tuple[Any, Any]], record_id: str, version_id: str) -> None:
    attrs = {k: list(v) for k, v in (entity.attributes or {}).items()}
    for field, (raw, norm) in values.items():
        if norm in (None, "") and raw in (None, ""):
            continue
        lst = attrs.setdefault(field, [])
        if not any(x.get("normalized") == norm and x.get("record_id") == record_id for x in lst):
            lst.append({"value": raw, "normalized": norm, "record_id": record_id, "dataset_version_id": version_id})
    entity.attributes = attrs
    entity.updated_at = utcnow()


def upsert_from_record(db: Session, cache: dict[str, Entity], *, project_id: str, entity_type: str, name: Any,
                       id_field: str | None, id_value: Any, attributes: dict[str, tuple[Any, Any]], record_id: str,
                       version_id: str, id_namespace: str | None = None) -> Entity | None:
    """Create or extend an entity from one record.

    Records sharing an identifier value (within ``id_namespace``, default the id field name) map to the same
    entity. Without a name, a record can only extend an entity by identifier; the identifier is then used as a
    provisional display name.
    """
    has_name = name not in (None, "")
    if not has_name and id_value in (None, ""):
        return None
    key = identity_key(entity_type, id_namespace or id_field, id_value)
    ent = None
    if key:
        ent = cache.get(key)
        if ent is None:
            ent = db.execute(select(Entity).where(Entity.project_id == project_id, Entity.identity_key == key)).scalar_one_or_none()
            # follow merges to the surviving entity
            while ent is not None and ent.status == "merged" and ent.merged_into_id:
                ent = db.get(Entity, ent.merged_into_id)
    if ent is None:
        ent = Entity(project_id=project_id, entity_type=entity_type, display_name=str(name if has_name else id_value)[:255],
                     identity_key=key, attributes={})
        db.add(ent)
        db.flush()
    if key:
        cache[key] = ent
    values = dict(attributes)
    if has_name:
        values.setdefault("name", (name, str(name)))
        if ent.display_name == str(id_value) and str(name) != str(id_value):
            ent.display_name = str(name)[:255]  # replace provisional identifier-only name
    if id_field and id_value not in (None, ""):
        values.setdefault(id_field, (id_value, str(id_value).strip()))
    add_attribute_values(ent, values, record_id, version_id)
    db.add(EntitySource(entity_id=ent.id, record_id=record_id, original_entity_id=ent.id))
    return ent


def summarize_attributes(attrs: dict[str, Any], hidden: set[str]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for f, items in (attrs or {}).items():
        vals = []
        for it in items:
            v = it.get("normalized") if isinstance(it, dict) else it
            if v not in vals:
                vals.append(v)
        out[f] = [REDACTED] * min(len(vals), 1) if f in hidden else vals
    return out


def entity_view(db: Session, e: Entity, can_sensitive: bool, *, detail: bool = False) -> dict[str, Any]:
    hidden = set() if can_sensitive else sensitive_fields(db, e.project_id).get(e.entity_type, set())
    view = {"id": e.id, "entity_type": e.entity_type, "display_name": e.display_name, "status": e.status,
            "merged_into_id": e.merged_into_id, "attributes": summarize_attributes(e.attributes, hidden),
            "created_at": e.created_at, "updated_at": e.updated_at, "redacted_fields": sorted(hidden & set(e.attributes or {}))}
    if detail:
        view["attribute_provenance"] = {
            f: ([{"value": REDACTED, "record_id": it.get("record_id"), "dataset_version_id": it.get("dataset_version_id")} for it in items]
                if f in hidden else items)
            for f, items in (e.attributes or {}).items()
        }
    return view


def entity_features(e: Entity) -> dict[str, Any]:
    return {"id": e.id, "name": e.display_name, "type": e.entity_type, "attributes": e.attributes or {}}


# --------------------------------------------------------------------------- resolution


def resolve(db: Session, project_id: str, entity_type: str | None = None, threshold: float = matching.DEFAULT_THRESHOLD) -> dict[str, Any]:
    types = entity_types(db, project_id)
    if entity_type and entity_type not in types:
        raise ValidationFailed(f"Unknown entity type {entity_type}")
    created, considered = 0, 0
    by_band: dict[str, int] = {"strong": 0, "ambiguous": 0}
    for tname in [entity_type] if entity_type else sorted(types):
        ents = db.execute(select(Entity).where(Entity.project_id == project_id, Entity.entity_type == tname,
                                               Entity.status == "active")).scalars().all()
        if len(ents) < 2:
            continue
        id_fields = {f["name"] for f in types[tname].fields if f.get("identifier")}
        items = [entity_features(e) for e in ents]
        considered += len(items)
        existing = {(c.entity_a_id, c.entity_b_id) for c in db.execute(
            select(MatchCandidate).where(MatchCandidate.project_id == project_id,
                                         MatchCandidate.algorithm_version == matching.ALGORITHM_VERSION)).scalars()}
        for m in matching.find_matches(items, id_fields, threshold):
            a, b = sorted([m["a"], m["b"]])
            if (a, b) in existing:
                continue
            ev = {k: m[k] for k in ("features", "matching_fields", "conflicting_fields", "not_compared", "note")}
            ev["sources"] = {
                a: [s.record_id for s in db.execute(select(EntitySource).where(EntitySource.entity_id == a)).scalars()],
                b: [s.record_id for s in db.execute(select(EntitySource).where(EntitySource.entity_id == b)).scalars()],
            }
            db.add(MatchCandidate(project_id=project_id, entity_type=tname, entity_a_id=a, entity_b_id=b,
                                  score=m["score"], band=m["band"], evidence=ev, algorithm_version=matching.ALGORITHM_VERSION))
            created += 1
            by_band[m["band"]] += 1
    db.commit()
    return {"entities_considered": considered, "candidates_created": created, "by_band": by_band,
            "algorithm_version": matching.ALGORITHM_VERSION, "threshold": threshold}


def merge(db: Session, project_id: str, survivor_id: str, merged_id: str, user_id: str,
          candidate_id: str | None = None) -> MergeHistory:
    if survivor_id == merged_id:
        raise ValidationFailed("Cannot merge an entity with itself")
    survivor, merged = db.get(Entity, survivor_id), db.get(Entity, merged_id)
    for e in (survivor, merged):
        if e is None or e.project_id != project_id:
            raise NotFound("Entity not found")
        if e.status != "active":
            raise Conflict(f"Entity {e.id} is not active (status {e.status})")
    if survivor.entity_type != merged.entity_type:
        raise ValidationFailed("Entities of different types cannot be merged")
    rels = db.execute(select(Relationship).where(or_(Relationship.source_entity_id == merged_id,
                                                     Relationship.target_entity_id == merged_id))).scalars().all()
    sources = db.execute(select(EntitySource).where(EntitySource.entity_id == merged_id)).scalars().all()
    events = db.execute(select(Event.id).where(Event.entity_id == merged_id)).scalars().all()
    geos = db.execute(select(GeoFeature.id).where(GeoFeature.entity_id == merged_id)).scalars().all()
    snapshot = {
        "merged_entity": {"display_name": merged.display_name, "identity_key": merged.identity_key},
        "merged_record_ids": sorted({s.record_id for s in sources}),
        "relationships": [{"id": r.id, "source": r.source_entity_id, "target": r.target_entity_id} for r in rels],
        "entity_sources": [s.id for s in sources],
        "events": list(events), "geo_features": list(geos),
        "survivor_display_name": survivor.display_name,
    }
    attrs = {k: list(v) for k, v in (survivor.attributes or {}).items()}
    for f, items in (merged.attributes or {}).items():
        lst = attrs.setdefault(f, [])
        for it in items:
            if it not in lst:
                lst.append(it)
    survivor.attributes = attrs
    survivor.updated_at = utcnow()
    for r in rels:
        if r.source_entity_id == merged_id:
            r.source_entity_id = survivor_id
        if r.target_entity_id == merged_id:
            r.target_entity_id = survivor_id
    for s in sources:
        s.entity_id = survivor_id
    db.execute(update(Event).where(Event.entity_id == merged_id).values(entity_id=survivor_id))
    db.execute(update(GeoFeature).where(GeoFeature.entity_id == merged_id).values(entity_id=survivor_id))
    merged.status = "merged"
    merged.merged_into_id = survivor_id
    mh = MergeHistory(project_id=project_id, survivor_id=survivor_id, merged_id=merged_id, candidate_id=candidate_id,
                      snapshot=snapshot, performed_by=user_id)
    db.add(mh)
    search.remove_item(db, merged_id)
    reindex_entity(db, survivor)
    db.flush()
    return mh


def revert_merge(db: Session, project_id: str, merge_id: str, user_id: str) -> MergeHistory:
    mh = db.get(MergeHistory, merge_id)
    if mh is None or mh.project_id != project_id:
        raise NotFound("Merge not found")
    if mh.reverted_at:
        raise Conflict("Merge already reverted")
    merged = db.get(Entity, mh.merged_id)
    survivor = db.get(Entity, mh.survivor_id)
    if merged is None or survivor is None:
        raise Conflict("Entities involved in this merge no longer exist")
    if survivor.status != "active":
        raise Conflict("Survivor has since been merged into another entity; revert that merge first")
    snap = mh.snapshot
    rec_ids = set(snap["merged_record_ids"])
    survivor.attributes = {
        f: kept for f, items in (survivor.attributes or {}).items()
        if (kept := [it for it in items if it.get("record_id") not in rec_ids])
    }
    for r in snap["relationships"]:
        rel = db.get(Relationship, r["id"])
        if rel is not None:
            rel.source_entity_id, rel.target_entity_id = r["source"], r["target"]
    for sid in snap["entity_sources"]:
        s = db.get(EntitySource, sid)
        if s is not None:
            s.entity_id = mh.merged_id
    if snap["events"]:
        db.execute(update(Event).where(Event.id.in_(snap["events"])).values(entity_id=mh.merged_id))
    if snap["geo_features"]:
        db.execute(update(GeoFeature).where(GeoFeature.id.in_(snap["geo_features"])).values(entity_id=mh.merged_id))
    merged.status = "active"
    merged.merged_into_id = None
    mh.reverted_at = utcnow()
    mh.reverted_by = user_id
    if mh.candidate_id:
        c = db.get(MatchCandidate, mh.candidate_id)
        if c:
            c.status = "pending"
            c.review_note = (c.review_note or "") + " [merge reverted]"
    reindex_entity(db, survivor)
    reindex_entity(db, merged)
    db.flush()
    return mh


def reindex_entity(db: Session, e: Entity) -> None:
    search.remove_item(db, e.id)
    if e.status != "active":
        return
    hidden = sensitive_fields(db, e.project_id).get(e.entity_type, set())
    attrs = summarize_attributes(e.attributes, hidden)
    body = " ".join(f"{k}: {' '.join(str(v) for v in vals)}" for k, vals in attrs.items() if k not in hidden)
    search.index_item(db, doc_type="entity", ref_id=e.id, project_id=e.project_id,
                      title=f"{e.display_name} ({e.entity_type})", body=body, created_at=e.created_at)
