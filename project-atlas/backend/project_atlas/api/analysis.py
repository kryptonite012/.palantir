"""Analytics (reproducible runs and read-only SQL), timeline and geospatial endpoints."""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas.analytics import service as an
from project_atlas.analytics import sql as sqlx
from project_atlas.api.common import audit, can_read_dataset, get_dataset, get_version, get_version_by_id, sensitive_columns
from project_atlas.api.deps import ProjectAccess, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import NotFound, ValidationFailed
from project_atlas.database.models import AnalysisRun, Dataset, DatasetVersion, Entity, GeoFeature, Record
from project_atlas.entities import matching
from project_atlas.entities.service import entity_features
from project_atlas.geospatial import service as geo
from project_atlas.graph import service as graph
from project_atlas.ingestion.service import parquet_path
from project_atlas.ontology.service import entity_types
from project_atlas.temporal import service as tl

router = APIRouter(prefix="/api/projects/{project_id}", tags=["analytics", "timeline", "geospatial"])


class AnalysisBody(BaseModel):
    kind: str
    dataset_version_id: str | None = None
    params: dict = {}


class SQLBody(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)


class FeatureCreate(BaseModel):
    layer: str = Field(default="annotations", min_length=1, max_length=128)
    name: str = Field(default="", max_length=255)
    geometry: dict
    properties: dict = {}
    kind: str = Field(default="annotation", pattern=r"^(annotation|layer)$")


def load_frame(ctx: AtlasContext, acc: ProjectAccess, dv: DatasetVersion) -> pd.DataFrame:
    p = parquet_path(ctx, dv.id)
    if not p.exists():
        raise NotFound("Columnar copy of this dataset version is missing; re-import or restore from backup")
    df = pd.read_parquet(p)
    hidden = sensitive_columns(acc, dv)
    return df.drop(columns=[c for c in hidden if c in df.columns])


def _execute(ctx: AtlasContext, db: Session, acc: ProjectAccess, kind: str, dataset_version_id: str | None, params: dict):
    t0 = time.perf_counter()
    if kind in an.ANALYSES:
        if not dataset_version_id:
            raise ValidationFailed("dataset_version_id is required")
        ds, dv = get_version_by_id(db, acc, dataset_version_id)
        df = load_frame(ctx, acc, dv)
        result = an.run_dataset_analysis(df, kind, params)
        inputs = {"dataset_versions": [{"dataset_id": ds.id, "dataset_name": ds.name, "version": dv.version,
                                        "version_id": dv.id, "content_sha256": dv.content_sha256}],
                  "redacted_fields": sorted(sensitive_columns(acc, dv))}
        algo = an.ALGORITHM_VERSIONS[kind]
    elif kind == "entity_similarity":
        a, b = db.get(Entity, params.get("entity_a")), db.get(Entity, params.get("entity_b"))
        if not a or not b or a.project_id != acc.project_id or b.project_id != acc.project_id:
            raise NotFound("Entity not found")
        if a.entity_type != b.entity_type:
            raise ValidationFailed("Entities must be of the same type")
        idf = {f["name"] for f in entity_types(db, acc.project_id)[a.entity_type].fields if f.get("identifier")}
        result = matching.compare(entity_features(a), entity_features(b), idf)
        if not acc.can("sensitive.read"):
            hidden = {f["name"] for f in entity_types(db, acc.project_id)[a.entity_type].fields if f.get("sensitive")}
            result["features"] = [{**f, "a": "[restricted]", "b": "[restricted]"} if f["feature"] in hidden else f
                                  for f in result["features"]]
        inputs = {"entities": [a.id, b.id], "entity_updated_at": [str(a.updated_at), str(b.updated_at)]}
        algo = matching.ALGORITHM_VERSION
    elif kind.startswith("graph."):
        result, inputs = graph.run_algorithm(db, acc.project_id, kind[6:], params)
        algo = graph.ALGORITHM_VERSION
    else:
        raise ValidationFailed(f"Unknown analysis kind {kind!r}")
    return result, inputs, algo, t0


@router.post("/analyses")
def run_analysis(body: AnalysisBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                 ctx: AtlasContext = Depends(get_ctx)):
    acc.require("analysis.run")
    result, inputs, algo, t0 = _execute(ctx, db, acc, body.kind, body.dataset_version_id, body.params)
    params = {**body.params, **({"dataset_version_id": body.dataset_version_id} if body.dataset_version_id else {})}
    run = an.record_run(db, project_id=acc.project_id, kind=body.kind, params=params, inputs=inputs,
                        algorithm_version=algo, result=result, started=t0, user_id=acc.principal.id)
    audit(ctx, acc, "analysis.run", "analysis_run", run.id, details={"kind": run.kind})
    return an.run_view(run)


@router.get("/analyses")
def list_analyses(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("analysis.read")
    rows = db.execute(select(AnalysisRun).where(AnalysisRun.project_id == acc.project_id)
                      .order_by(AnalysisRun.created_at.desc()).limit(200)).scalars().all()
    return [an.run_view(r, include_result=False) for r in rows]


def _get_run(db: Session, acc: ProjectAccess, run_id: str) -> AnalysisRun:
    r = db.get(AnalysisRun, run_id)
    if r is None or r.project_id != acc.project_id:
        raise NotFound("Analysis run not found")
    for dsv in r.inputs.get("dataset_versions", []):
        get_version_by_id(db, acc, dsv["version_id"])  # enforces dataset access
    return r


@router.get("/analyses/{run_id}")
def get_analysis(run_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("analysis.read")
    return an.run_view(_get_run(db, acc, run_id))


@router.post("/analyses/{run_id}/reproduce")
def reproduce(run_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
              ctx: AtlasContext = Depends(get_ctx)):
    acc.require("analysis.run")
    orig = _get_run(db, acc, run_id)
    params = dict(orig.params)
    dvid = params.pop("dataset_version_id", None)
    result, inputs, algo, t0 = _execute(ctx, db, acc, orig.kind, dvid, params)
    run = an.record_run(db, project_id=acc.project_id, kind=orig.kind, params=orig.params, inputs=inputs,
                        algorithm_version=algo, result=result, started=t0, user_id=acc.principal.id, reproduced_from=orig.id)
    same_inputs = {k: v for k, v in inputs.items() if k != "redacted_fields"} == {k: v for k, v in orig.inputs.items() if k != "redacted_fields"}
    audit(ctx, acc, "analysis.reproduce", "analysis_run", run.id, details={"original": orig.id,
                                                                            "identical": run.result_sha256 == orig.result_sha256})
    return {"original_id": orig.id, "reproduction": an.run_view(run), "identical_result": run.result_sha256 == orig.result_sha256,
            "identical_inputs": same_inputs, "algorithm_version_changed": algo != orig.algorithm_version}


@router.get("/sql/tables")
def sql_tables(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("query.sql")
    out = []
    for ds in db.execute(select(Dataset).where(Dataset.project_id == acc.project_id)).scalars():
        if not can_read_dataset(acc, ds) or ds.current_version == 0:
            continue
        dv = get_version(db, ds)
        hidden = sensitive_columns(acc, dv)
        out.append({"table": sqlx.table_name(ds.name), "dataset_id": ds.id, "version": dv.version,
                    "columns": ["__record_id", "__row_index"] + [f["name"] for f in dv.schema_json["fields"] if f["name"] not in hidden]})
    return out


def _sql_tables(ctx: AtlasContext, db: Session, acc: ProjectAccess):
    tables = {}
    versions = []
    for ds in db.execute(select(Dataset).where(Dataset.project_id == acc.project_id)).scalars():
        if not can_read_dataset(acc, ds) or ds.current_version == 0:
            continue
        dv = get_version(db, ds)
        p = parquet_path(ctx, dv.id)
        if p.exists():
            tables[sqlx.table_name(ds.name)] = (p, sorted(sensitive_columns(acc, dv)))
            versions.append({"dataset_id": ds.id, "version_id": dv.id, "version": dv.version})
    return tables, versions


@router.post("/sql")
def run_sql(body: SQLBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
            ctx: AtlasContext = Depends(get_ctx)):
    acc.require("query.sql")
    tables, versions = _sql_tables(ctx, db, acc)
    try:
        res = sqlx.run_query(body.sql, tables, row_limit=ctx.settings.query_row_limit,
                             timeout_s=ctx.settings.query_timeout_seconds)
    except ValidationFailed as exc:
        audit(ctx, acc, "query.sql", "query", None, outcome="denied", details={"sql": body.sql[:2000], "error": exc.message})
        raise
    from project_atlas.database.models import QueryHistory

    db.add(QueryHistory(project_id=acc.project_id, user_id=acc.principal.id, kind="sql", query=body.sql[:5000],
                        filters={}, result_count=res["row_count"]))
    db.commit()
    audit(ctx, acc, "query.sql", "query", None, details={"sql": body.sql[:2000], "rows": res["row_count"]})
    return {**res, "dataset_versions": versions}


# --------------------------------------------------------------------------- timeline


@router.get("/timeline")
def timeline(start: datetime | None = None, end: datetime | None = None,
             entity_id: list[str] | None = Query(None), category: list[str] | None = Query(None),
             tz: str | None = None, limit: int = 1000, order: str = "asc", cluster_gap_seconds: float | None = None,
             acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("timeline.read")
    allowed = tl.allowed_dataset_ids(db, acc.project_id, acc.can("dataset.read_restricted"))
    res = tl.query_events(db, acc.project_id, start=start, end=end, entity_ids=entity_id, categories=category,
                          dataset_ids_allowed=allowed, display_tz=tz, limit=max(1, limit), order=order)
    if cluster_gap_seconds:
        res["clusters"] = tl.cluster(res["events"], cluster_gap_seconds)
    if start and end:
        res["relationships_in_window"] = tl.relationships_in_window(db, acc.project_id, start, end)
    return res


@router.get("/timeline/compare")
def timeline_compare(entity_a: str, entity_b: str, window_seconds: float = 3600,
                     acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("timeline.read")
    for e in (entity_a, entity_b):
        ent = db.get(Entity, e)
        if ent is None or ent.project_id != acc.project_id:
            raise NotFound("Entity not found")
    return tl.compare_entities(db, acc.project_id, entity_a, entity_b, window_seconds)


# --------------------------------------------------------------------------- geospatial


def _filter_geo_access(db: Session, acc: ProjectAccess, feats: list[GeoFeature]) -> list[GeoFeature]:
    allowed = tl.allowed_dataset_ids(db, acc.project_id, acc.can("dataset.read_restricted"))
    rec_ids = {f.record_id for f in feats if f.record_id}
    rec_ds = dict(db.execute(select(Record.id, Record.dataset_id).where(Record.id.in_(rec_ids))).all()) if rec_ids else {}
    return [f for f in feats if not f.record_id or rec_ds.get(f.record_id) in allowed]


@router.get("/geo/layers")
def geo_layers(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("geo.read")
    from sqlalchemy import func

    rows = db.execute(select(GeoFeature.layer, GeoFeature.kind, func.count(), func.min(GeoFeature.min_lon), func.min(GeoFeature.min_lat),
                             func.max(GeoFeature.max_lon), func.max(GeoFeature.max_lat))
                      .where(GeoFeature.project_id == acc.project_id).group_by(GeoFeature.layer, GeoFeature.kind)).all()
    return [{"layer": l, "kind": k, "count": c, "bbox": [a, b, cc, d]} for l, k, c, a, b, cc, d in rows]


@router.get("/geo/features")
def geo_features(layer: list[str] | None = Query(None), bbox: str | None = None, start: datetime | None = None,
                 end: datetime | None = None, limit: int = 5000, acc: ProjectAccess = Depends(project_access),
                 db: Session = Depends(get_db)):
    acc.require("geo.read")
    bb = [float(x) for x in bbox.split(",")] if bbox else None
    feats = _filter_geo_access(db, acc, geo.query(db, acc.project_id, layers=layer, bbox=bb, start=start, end=end, limit=limit))
    return {"type": "FeatureCollection", "features": [geo.feature_view(f) for f in feats]}


@router.get("/geo/radius")
def geo_radius(lon: float, lat: float, radius_m: float, layer: list[str] | None = Query(None),
               acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("geo.read")
    res = geo.radius(db, acc.project_id, lon, lat, radius_m, layer)
    ok = {f.id for f in _filter_geo_access(db, acc, [db.get(GeoFeature, r["id"]) for r in res])}
    return {"center": [lon, lat], "radius_m": radius_m, "results": [r for r in res if r["id"] in ok],
            "method": "haversine great-circle distance (spherical Earth, R=6371.0088 km)"}


@router.get("/geo/distance")
def geo_distance(lon1: float, lat1: float, lon2: float, lat2: float, acc: ProjectAccess = Depends(project_access)):
    acc.require("geo.read")
    for lo, la in ((lon1, lat1), (lon2, lat2)):
        if not (-180 <= lo <= 180 and -90 <= la <= 90):
            raise ValidationFailed("Coordinates out of range")
    return {"distance_m": round(geo.haversine_m(lon1, lat1, lon2, lat2), 2), "method": "haversine"}


@router.get("/geo/join")
def geo_join(point_layer: str, polygon_layer: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    acc.require("geo.read")
    return geo.spatial_join(db, acc.project_id, point_layer, polygon_layer)


@router.get("/geo/clusters")
def geo_clusters(cell_deg: float = 1.0, layer: list[str] | None = Query(None), acc: ProjectAccess = Depends(project_access),
                 db: Session = Depends(get_db)):
    acc.require("geo.read")
    feats = _filter_geo_access(db, acc, geo.query(db, acc.project_id, layers=layer, bbox=None, start=None, end=None))
    return {"cell_deg": cell_deg, "clusters": geo.grid_clusters(feats, cell_deg)}


@router.post("/geo/features")
def geo_add(body: FeatureCreate, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
            ctx: AtlasContext = Depends(get_ctx)):
    acc.require("geo.write")
    f = geo.add_feature(db, project_id=acc.project_id, layer=body.layer, kind=body.kind, name=body.name,
                        geometry=body.geometry, properties=body.properties, user_id=acc.principal.id)
    db.commit()
    audit(ctx, acc, "geo.feature_added", "geo_feature", f.id, details={"layer": body.layer, "kind": body.kind})
    return geo.feature_view(f)


@router.post("/geo/layers")
def geo_import(layer: str = Form(...), file: UploadFile = File(...), acc: ProjectAccess = Depends(project_access),
               db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("geo.write")
    data = file.file.read(ctx.settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > ctx.settings.max_upload_mb * 1024 * 1024:
        raise ValidationFailed("File too large")
    n = geo.import_geojson(db, acc.project_id, layer, data, acc.principal.id)
    db.commit()
    audit(ctx, acc, "geo.layer_imported", "geo_layer", layer, details={"features": n, "file": file.filename})
    return {"layer": layer, "features": n}
