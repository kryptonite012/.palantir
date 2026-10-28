"""Dataset retention enforcement.

Policies are periods measured from a version's import time: ``1y``, ``3y``, ``7y`` (365/1095/2555 days);
``indefinite`` and ``until_case_closed`` never expire automatically.

* **Superseded versions** past their retention period are purged: records (raw and normalized), quality
  issues, derived events/map points, entity provenance links and search entries, plus the columnar copy.
  The version row itself is kept as a tombstone (``record_count`` unchanged, ``purged_at`` in the ingestion
  report) so lineage and analysis manifests still resolve to *what existed*.
* **Current versions** past retention are never deleted automatically: owners and project administrators
  are notified to review and delete or re-classify the dataset.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from project_atlas.database.models import (
    Dataset, DatasetVersion, Event, GeoFeature, Notification, ProjectMember, QualityIssue, Record, utcnow,
)

if TYPE_CHECKING:
    from project_atlas.core.context import AtlasContext

POLICY_DAYS = {"1y": 365, "3y": 1095, "7y": 2555}
POLICIES = ["indefinite", "until_case_closed", *POLICY_DAYS]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def review(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    purge, flag = [], []
    for ds in db.execute(select(Dataset).where(Dataset.retention_policy.in_(list(POLICY_DAYS)))).scalars():
        limit = now - timedelta(days=POLICY_DAYS[ds.retention_policy])
        for v in db.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id)).scalars():
            if _aware(v.imported_at) >= limit or v.ingestion_report.get("purged_at"):
                continue
            item = {"project_id": ds.project_id, "dataset_id": ds.id, "dataset": ds.name, "version": v.version,
                    "version_id": v.id, "imported_at": _aware(v.imported_at).isoformat(), "policy": ds.retention_policy,
                    "records": v.record_count}
            (flag if v.version == ds.current_version else purge).append(item)
    return {"evaluated_at": now.isoformat(), "purge": purge, "review_required": flag}


def purge_version(ctx: "AtlasContext", db: Session, dv: DatasetVersion) -> int:
    from project_atlas.ingestion.service import parquet_path

    rec_ids = select(Record.id).where(Record.dataset_version_id == dv.id)
    if db.bind.dialect.name == "sqlite":
        db.execute(text("DELETE FROM search_index WHERE rowid IN (SELECT rowid FROM search_docs WHERE ref_id IN "
                        "(SELECT id FROM records WHERE dataset_version_id = :v))"), {"v": dv.id})
        db.execute(text("DELETE FROM search_docs WHERE ref_id IN (SELECT id FROM records WHERE dataset_version_id = :v)"), {"v": dv.id})
    else:
        db.execute(text("DELETE FROM search_index WHERE ref_id IN (SELECT id FROM records WHERE dataset_version_id = :v)"), {"v": dv.id})
    db.execute(delete(Event).where(Event.record_id.in_(rec_ids)))
    db.execute(delete(GeoFeature).where(GeoFeature.record_id.in_(rec_ids)))
    db.execute(delete(QualityIssue).where(QualityIssue.dataset_version_id == dv.id))
    n = db.execute(delete(Record).where(Record.dataset_version_id == dv.id)).rowcount or 0  # entity_sources cascade
    dv.ingestion_report = {**dv.ingestion_report, "purged_at": utcnow().isoformat(), "purged_records": n}
    parquet_path(ctx, dv.id).unlink(missing_ok=True)
    return n


def apply_retention(ctx: "AtlasContext", db: Session, *, actor_id: str | None) -> dict[str, Any]:
    plan = review(db)
    purged = 0
    for item in plan["purge"]:
        dv = db.get(DatasetVersion, item["version_id"])
        item["purged_records"] = purge_version(ctx, db, dv)
        purged += item["purged_records"]
    for item in plan["review_required"]:
        ds = db.get(Dataset, item["dataset_id"])
        admins = set(db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == ds.project_id,
                                                                     ProjectMember.role == "project_admin")).scalars())
        for uid in admins | {ds.owner_id}:
            exists = db.execute(select(Notification.id).where(Notification.user_id == uid, Notification.kind == "retention",
                                                              Notification.read_at.is_(None),
                                                              Notification.link == f"/catalog/{ds.id}")).first()
            if not exists:
                db.add(Notification(user_id=uid, project_id=ds.project_id, kind="retention",
                                    title=f"Retention period ended: {ds.name}",
                                    body=f"Version {item['version']} is past its {ds.retention_policy} retention period. "
                                         "Review and delete or re-classify the dataset.",
                                    link=f"/catalog/{ds.id}", details={"version_id": item["version_id"]}))
    db.commit()
    for item in plan["purge"]:
        ctx.audit.record("retention.purge", actor_id=actor_id, actor_name="system:retention", resource_type="dataset_version",
                         resource_id=item["version_id"], project_id=item["project_id"],
                         details={"dataset": item["dataset"], "version": item["version"], "records": item["purged_records"],
                                  "policy": item["policy"]})
    return {"purged_versions": len(plan["purge"]), "purged_records": purged,
            "review_required": len(plan["review_required"]), "details": plan}
