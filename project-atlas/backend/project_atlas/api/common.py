"""Helpers shared by API routers: auditing, dataset access, pagination."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas.api.deps import Principal, ProjectAccess
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Forbidden, NotFound
from project_atlas.database.models import Dataset, DatasetVersion


def audit(ctx: AtlasContext, p: Principal | ProjectAccess, action: str, resource_type: str, resource_id: str | None = None,
          *, outcome: str = "success", details: dict[str, Any] | None = None) -> None:
    principal = p.principal if isinstance(p, ProjectAccess) else p
    project_id = p.project_id if isinstance(p, ProjectAccess) else None
    ctx.audit.record(action, actor_id=principal.id, actor_name=principal.name, resource_type=resource_type,
                     resource_id=resource_id, project_id=project_id, outcome=outcome, details=details)


def can_read_dataset(acc: ProjectAccess, ds: Dataset) -> bool:
    if ds.access_policy == "restricted":
        return acc.can("dataset.read_restricted")
    return acc.can("dataset.read")


def get_dataset(db: Session, acc: ProjectAccess, dataset_id: str, ctx: AtlasContext | None = None) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None or ds.project_id != acc.project_id:
        raise NotFound("Dataset not found")
    if not can_read_dataset(acc, ds):
        if ctx is not None:
            audit(ctx, acc, "dataset.access", "dataset", dataset_id, outcome="denied")
        raise NotFound("Dataset not found")
    return ds


def get_version(db: Session, ds: Dataset, version: int | None = None) -> DatasetVersion:
    v = version if version is not None else ds.current_version
    dv = db.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id, DatasetVersion.version == v)).scalar_one_or_none()
    if dv is None:
        raise NotFound(f"Dataset version {v} not found")
    return dv


def get_version_by_id(db: Session, acc: ProjectAccess, version_id: str) -> tuple[Dataset, DatasetVersion]:
    dv = db.get(DatasetVersion, version_id)
    if dv is None:
        raise NotFound("Dataset version not found")
    ds = get_dataset(db, acc, dv.dataset_id)
    return ds, dv


def sensitive_columns(acc: ProjectAccess, dv: DatasetVersion) -> set[str]:
    if acc.can("sensitive.read"):
        return set()
    return {f["name"] for f in dv.schema_json.get("fields", []) if f.get("sensitive")}


def redact_record(values: dict[str, Any], hidden: set[str]) -> dict[str, Any]:
    return {k: ("[restricted]" if k in hidden and v is not None else v) for k, v in values.items()}


def require_any(acc: ProjectAccess, *perms: str) -> None:
    if not any(acc.can(p) for p in perms):
        raise Forbidden(f"Requires one of: {', '.join(perms)}")


def paginate(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 500)), max(0, offset)
