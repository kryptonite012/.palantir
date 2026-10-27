"""Timeline queries: filtering, clustering, durations, comparisons, time-constrained relationships."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from project_atlas.core.errors import ValidationFailed
from project_atlas.database.models import Dataset, Entity, Event, Relationship


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def event_view(e: Event, display_tz: str | None, entity_names: dict[str, str]) -> dict[str, Any]:
    et = _aware(e.event_time)
    local = et.astimezone(ZoneInfo(display_tz)).isoformat() if display_tz else None
    return {
        "id": e.id, "title": e.title, "category": e.category, "entity_id": e.entity_id,
        "entity_name": entity_names.get(e.entity_id or ""), "record_id": e.record_id, "dataset_id": e.dataset_id,
        "event_time": et.isoformat(), "event_time_display": local, "end_time": _aware(e.end_time).isoformat() if e.end_time else None,
        "duration_seconds": (_aware(e.end_time) - et).total_seconds() if e.end_time else None,
        "source_timezone": e.source_timezone, "source_time_text": e.source_time_text,
        "record_created_time": _aware(e.record_created_time).isoformat() if e.record_created_time else None,
        "ingested_at": _aware(e.ingested_at).isoformat(), "modified_at": _aware(e.modified_at).isoformat(),
        "latitude": e.latitude, "longitude": e.longitude,
    }


def query_events(db: Session, project_id: str, *, start: datetime | None, end: datetime | None,
                 entity_ids: list[str] | None, categories: list[str] | None, dataset_ids_allowed: set[str] | None,
                 display_tz: str | None, limit: int = 1000, order: str = "asc") -> dict[str, Any]:
    if display_tz:
        try:
            ZoneInfo(display_tz)
        except Exception as exc:  # noqa: BLE001
            raise ValidationFailed(f"Unknown time zone {display_tz}") from exc
    q = select(Event).where(Event.project_id == project_id)
    if start:
        q = q.where(Event.event_time >= start)
    if end:
        q = q.where(Event.event_time <= end)
    if entity_ids:
        q = q.where(Event.entity_id.in_(entity_ids))
    if categories:
        q = q.where(Event.category.in_(categories))
    if dataset_ids_allowed is not None:
        q = q.where(or_(Event.dataset_id.is_(None), Event.dataset_id.in_(dataset_ids_allowed)))
    q = q.order_by(Event.event_time.asc() if order == "asc" else Event.event_time.desc()).limit(min(limit, 5000) + 1)
    rows = db.execute(q).scalars().all()
    truncated = len(rows) > limit
    rows = rows[:limit]
    names = {e.id: e.display_name for e in db.execute(select(Entity).where(Entity.id.in_({r.entity_id for r in rows if r.entity_id}))).scalars()}
    events = [event_view(e, display_tz, names) for e in rows]
    cats = sorted({e.category for e in rows})
    return {"events": events, "truncated": truncated, "categories": cats,
            "time_basis": "event_time (UTC); record_created_time, ingested_at and modified_at are reported separately"}


def cluster(events: list[dict[str, Any]], gap_seconds: float) -> list[dict[str, Any]]:
    """Group chronologically sorted events whose consecutive gap is <= gap_seconds."""
    evs = sorted(events, key=lambda e: e["event_time"])
    clusters: list[dict[str, Any]] = []
    for e in evs:
        t = datetime.fromisoformat(e["event_time"])
        if clusters and (t - clusters[-1]["_last"]).total_seconds() <= gap_seconds:
            c = clusters[-1]
            c["event_ids"].append(e["id"])
            c["_last"] = t
            c["end"] = e["event_time"]
        else:
            clusters.append({"start": e["event_time"], "end": e["event_time"], "event_ids": [e["id"]], "_last": t})
    for c in clusters:
        c.pop("_last")
        c["size"] = len(c["event_ids"])
        c["span_seconds"] = (datetime.fromisoformat(c["end"]) - datetime.fromisoformat(c["start"])).total_seconds()
    return clusters


def compare_entities(db: Session, project_id: str, a: str, b: str, window_seconds: float) -> dict[str, Any]:
    ea = db.execute(select(Event).where(Event.project_id == project_id, Event.entity_id == a).order_by(Event.event_time)).scalars().all()
    eb = db.execute(select(Event).where(Event.project_id == project_id, Event.entity_id == b).order_by(Event.event_time)).scalars().all()

    def span(evs):
        if not evs:
            return None
        return {"first": _aware(evs[0].event_time).isoformat(), "last": _aware(evs[-1].event_time).isoformat(), "count": len(evs)}

    near = []
    j = 0
    for x in ea:
        tx = _aware(x.event_time)
        while j < len(eb) and _aware(eb[j].event_time) < tx - timedelta(seconds=window_seconds):
            j += 1
        k = j
        while k < len(eb) and _aware(eb[k].event_time) <= tx + timedelta(seconds=window_seconds):
            near.append({"a_event": x.id, "b_event": eb[k].id, "a_title": x.title, "b_title": eb[k].title,
                         "delta_seconds": (_aware(eb[k].event_time) - tx).total_seconds()})
            k += 1
    sa, sb = span(ea), span(eb)
    overlap = None
    if sa and sb:
        lo, hi = max(sa["first"], sb["first"]), min(sa["last"], sb["last"])
        overlap = {"start": lo, "end": hi} if lo <= hi else None
    return {"a": sa, "b": sb, "activity_overlap": overlap, "co_occurrences": near[:500], "window_seconds": window_seconds,
            "note": "Temporal proximity is descriptive; it does not establish that the entities interacted."}


def relationships_in_window(db: Session, project_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    q = select(Relationship).where(Relationship.project_id == project_id, Relationship.status == "active",
                                   Relationship.valid_from.is_not(None),
                                   Relationship.valid_from <= end,
                                   or_(Relationship.valid_to.is_(None), Relationship.valid_to >= start))
    rels = db.execute(q).scalars().all()
    names = {e.id: e.display_name for e in db.execute(select(Entity).where(Entity.id.in_(
        {r.source_entity_id for r in rels} | {r.target_entity_id for r in rels}))).scalars()}
    return [{"id": r.id, "rel_type": r.rel_type, "source": names.get(r.source_entity_id), "target": names.get(r.target_entity_id),
             "source_entity_id": r.source_entity_id, "target_entity_id": r.target_entity_id,
             "valid_from": _aware(r.valid_from).isoformat(), "valid_to": _aware(r.valid_to).isoformat() if r.valid_to else None,
             "assertion": r.assertion} for r in rels]


def allowed_dataset_ids(db: Session, project_id: str, can_restricted: bool) -> set[str]:
    q = select(Dataset.id).where(Dataset.project_id == project_id)
    if not can_restricted:
        q = q.where(Dataset.access_policy != "restricted")
    return set(db.execute(q).scalars())
