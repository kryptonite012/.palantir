"""Controlled import pipeline: upload → inspect → map → validate → preview → commit.

The commit runs as a background job inside a single database transaction, so
a failed or cancelled import leaves no partial data. Retrying a job re-runs
the import from the start (idempotent at the version level).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas import __version__
from project_atlas.core.errors import NotFound, ValidationFailed
from project_atlas.database.models import (
    Dataset, DatasetVersion, Entity, EntitySource, Event, GeoFeature, QualityIssue, Record, Relationship, StoredFile,
    new_id, utcnow,
)
from project_atlas.entities import service as entities
from project_atlas.ingestion import normalize, parsers
from project_atlas.ingestion.quality import QualityAccumulator
from project_atlas.ontology.service import entity_types, relationship_type_names
from project_atlas.search import service as search

if TYPE_CHECKING:
    from project_atlas.core.context import AtlasContext
    from project_atlas.core.jobs import JobReporter

BATCH = 1000
PIPELINE_VERSION = "ingest-1.0"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/")).strip()
    base = _SAFE_NAME.sub("_", base)[:200].lstrip(".")
    if not base:
        raise ValidationFailed("Invalid file name")
    return base


def storage_path(ctx: "AtlasContext", relative: str) -> Path:
    root = ctx.settings.storage_dir.resolve()
    p = (root / relative).resolve()
    if root not in p.parents and p != root:
        raise ValidationFailed("Path escapes the workspace directory")
    return p


def store_upload(ctx: "AtlasContext", db: Session, *, project_id: str, user_id: str, filename: str,
                 stream: BinaryIO, source_id: str | None = None) -> StoredFile:
    name = safe_filename(filename)
    limit = ctx.settings.max_upload_mb * 1024 * 1024
    file_id = new_id("fil")
    rel_dir = Path("files") / project_id
    ext = Path(name).suffix.lower()
    if ext not in parsers.ALLOWED_EXTENSIONS:
        raise ValidationFailed(f"File type {ext or '(none)'} is not permitted")
    rel = rel_dir / f"{file_id}{ext}"
    dest = storage_path(ctx, str(rel))
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    size = 0
    head = b""
    try:
        with open(dest, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValidationFailed(f"File exceeds the {ctx.settings.max_upload_mb} MB upload limit")
                if len(head) < 8192:
                    head += chunk[: 8192 - len(head)]
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ValidationFailed("File is empty")
        fmt = parsers.detect_format(name, head)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    os.chmod(dest, 0o600)
    f = StoredFile(id=file_id, project_id=project_id, source_id=source_id, original_name=name, stored_path=str(rel),
                   sha256=h.hexdigest(), size_bytes=size, detected_format=fmt, uploaded_by=user_id)
    db.add(f)
    db.commit()
    return f


def get_file(ctx: "AtlasContext", db: Session, project_id: str, file_id: str) -> tuple[StoredFile, Path]:
    f = db.get(StoredFile, file_id)
    if f is None or f.project_id != project_id:
        raise NotFound("File not found")
    return f, storage_path(ctx, f.stored_path)


# --------------------------------------------------------------------------- transformation


def resolve_mapping(path: Path, fmt: str, opts: parsers.ParseOptions, mapping: dict | None) -> tuple[dict, parsers.Inspection]:
    insp = parsers.inspect(path, fmt, opts, preview_rows=200)
    if not mapping:
        samples = {c: [r.get(c) for r in insp.preview] for c in insp.columns}
        mapping = normalize.suggest_mapping(insp.columns, samples)
    targets = set()
    for src, spec in mapping.items():
        if "target" not in spec:
            raise ValidationFailed(f"Mapping for column {src!r} lacks a target")
        t = spec["target"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", t):
            raise ValidationFailed(f"Invalid target field name {t!r}")
        if t in targets:
            raise ValidationFailed(f"Duplicate target field {t!r}")
        targets.add(t)
        if spec.get("type", "string") not in {"string", "identifier", "integer", "float", "latitude", "longitude",
                                               "boolean", "datetime", "date", "email", "phone"}:
            raise ValidationFailed(f"Unknown type {spec.get('type')!r} for column {src!r}")
        if spec.get("timezone"):
            try:
                normalize.get_zone(spec["timezone"])
            except ValueError as exc:
                raise ValidationFailed(str(exc)) from exc
    return mapping, insp


def transform(raw: dict[str, Any], mapping: dict[str, dict], null_tokens: list[str], default_tz: str | None,
              keep_unmapped: bool) -> tuple[dict[str, Any], dict[str, str]]:
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for src, spec in mapping.items():
        v = raw.get(src)
        if normalize.is_null(v, null_tokens):
            out[spec["target"]] = None
            continue
        value, err = normalize.convert(v, spec, default_tz)
        out[spec["target"]] = value if err is None or spec.get("type") in {"string", "identifier", "email"} else None
        if err:
            errors[spec["target"]] = err
    if keep_unmapped:
        for k, v in raw.items():
            if k not in mapping and not k.startswith("__"):
                out.setdefault(normalize.snake(k), parsers.jsonable(v))
    return out, errors


def schema_from_mapping(mapping: dict[str, dict]) -> dict[str, Any]:
    return {"fields": [{"name": s["target"], "type": s.get("type", "string"), "source": src,
                        "sensitive": bool(s.get("sensitive")), "required": bool(s.get("required"))}
                       for src, s in mapping.items()]}


def row_hash(normalized: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, default=str).encode()).hexdigest()


_ARROW_TYPES = {"integer": "int64", "float": "float64", "latitude": "float64", "longitude": "float64", "boolean": "bool"}


def _arrow_schema(schema: dict[str, Any]):
    import pyarrow as pa

    fields = [pa.field("__record_id", pa.string()), pa.field("__row_index", pa.int64())]
    for f in schema["fields"]:
        fields.append(pa.field(f["name"], getattr(pa, _ARROW_TYPES.get(f["type"], "string"))()))
    return pa.schema(fields)


def parquet_path(ctx: "AtlasContext", version_id: str) -> Path:
    return ctx.settings.derived_dir / "datasets" / f"{version_id}.parquet"


# --------------------------------------------------------------------------- pipeline


def _validate_config(db: Session, project_id: str, cfg: dict[str, Any], targets: set[str]) -> None:
    types = entity_types(db, project_id)
    rel_names = relationship_type_names(db, project_id)
    specs = cfg.get("entities") or []
    for i, es in enumerate(specs):
        if es.get("entity_type") not in types:
            raise ValidationFailed(f"entities[{i}]: unknown entity type {es.get('entity_type')!r}")
        for key in ("name_field", "id_field"):
            if es.get(key) and es[key] not in targets:
                raise ValidationFailed(f"entities[{i}].{key}: {es[key]!r} is not a mapped field")
        if not es.get("name_field") and not es.get("id_field"):
            raise ValidationFailed(f"entities[{i}]: name_field or id_field is required")
        if es.get("id_namespace") and not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", es["id_namespace"]):
            raise ValidationFailed(f"entities[{i}].id_namespace must be a lowercase identifier")
        for a in es.get("attributes", []):
            if a not in targets:
                raise ValidationFailed(f"entities[{i}].attributes: {a!r} is not a mapped field")
    for i, rs in enumerate(cfg.get("relationships") or []):
        for k in ("source", "target"):
            if not isinstance(rs.get(k), int) or not 0 <= rs[k] < len(specs):
                raise ValidationFailed(f"relationships[{i}].{k} must index an entity spec")
        if rs.get("rel_type") not in rel_names:
            raise ValidationFailed(f"relationships[{i}]: unknown relationship type {rs.get('rel_type')!r}")
    ev = cfg.get("events")
    if ev:
        if ev.get("time_field") not in targets:
            raise ValidationFailed("events.time_field must be a mapped field")
    geo = cfg.get("geo")
    if geo:
        if geo.get("lat_field") not in targets or geo.get("lon_field") not in targets:
            raise ValidationFailed("geo.lat_field and geo.lon_field must be mapped fields")


def _reference_values(db: Session, project_id: str, quality_cfg: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for field, ref in (quality_cfg.get("references") or {}).items():
        ds = db.get(Dataset, ref.get("dataset_id"))
        if ds is None or ds.project_id != project_id:
            raise ValidationFailed(f"Referenced dataset for {field} not found")
        ver = db.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id,
                                                      DatasetVersion.version == ds.current_version)).scalar_one_or_none()
        vals: set[str] = set()
        if ver:
            for (norm,) in db.execute(select(Record.normalized).where(Record.dataset_version_id == ver.id)):
                v = norm.get(ref.get("field"))
                if v not in (None, ""):
                    vals.add(str(v))
        out[field] = vals
    return out


def _parse_iso(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def run_import(ctx: "AtlasContext", db: Session, *, project_id: str, user_id: str, cfg: dict[str, Any],
               dry_run: bool, reporter: "JobReporter | None" = None, preview_limit: int = 20) -> dict[str, Any]:
    t0 = time.perf_counter()
    stored, path = get_file(ctx, db, project_id, cfg.get("file_id", ""))
    if stored.detected_format not in parsers.TABULAR_FORMATS:
        raise ValidationFailed(f"{stored.detected_format} files are imported through Documents or Geospatial, not datasets")
    opts = parsers.ParseOptions.from_dict(cfg.get("parse"))
    mapping, insp = resolve_mapping(path, stored.detected_format, opts, cfg.get("mapping"))
    targets = {s["target"] for s in mapping.values()}
    _validate_config(db, project_id, cfg, targets)
    null_tokens = [t.lower() for t in cfg.get("null_tokens", normalize.DEFAULT_NULL_TOKENS)]
    default_tz = cfg.get("default_timezone", "UTC")
    try:
        normalize.get_zone(default_tz)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    keep_unmapped = cfg.get("unmapped", "drop") == "keep"
    schema = schema_from_mapping(mapping)
    sensitive_cols = {f["name"] for f in schema["fields"] if f["sensitive"]}

    dataset: Dataset | None = None
    prev_schema = None
    if cfg.get("dataset_id"):
        dataset = db.get(Dataset, cfg["dataset_id"])
        if dataset is None or dataset.project_id != project_id:
            raise NotFound("Dataset not found")
        prev = db.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id,
                                                       DatasetVersion.version == dataset.current_version)).scalar_one_or_none()
        prev_schema = prev.schema_json if prev else None
    else:
        name = (cfg.get("dataset_name") or Path(stored.original_name).stem).strip()[:128]
        if not name:
            raise ValidationFailed("dataset_name is required")
        if db.execute(select(Dataset).where(Dataset.project_id == project_id, Dataset.name == name)).scalar_one_or_none():
            raise ValidationFailed(f"A dataset named {name!r} already exists; pass dataset_id to add a version")
        if not dry_run:
            from project_atlas.retention import POLICIES

            if cfg.get("retention_policy", "indefinite") not in POLICIES:
                raise ValidationFailed(f"retention_policy must be one of {POLICIES}")
            policy = cfg.get("access_policy", "project")
            if policy not in {"project", "restricted"}:
                raise ValidationFailed("access_policy must be 'project' or 'restricted'")
            dataset = Dataset(project_id=project_id, name=name, description=cfg.get("description", ""),
                              owner_id=user_id, access_policy=policy,
                              retention_policy=cfg.get("retention_policy", "indefinite"),
                              is_synthetic=bool(cfg.get("is_synthetic")), source_id=stored.source_id)
            db.add(dataset)
            db.flush()

    qa = QualityAccumulator(cfg.get("quality") or {}, mapping, _reference_values(db, project_id, cfg.get("quality") or {}))
    version: DatasetVersion | None = None
    writer = None
    if not dry_run:
        assert dataset is not None
        version = DatasetVersion(dataset_id=dataset.id, version=dataset.current_version + 1, file_id=stored.id,
                                 schema_json=schema, import_config={**cfg, "mapping": mapping},
                                 imported_by=user_id, origin="import")
        db.add(version)
        db.flush()
        import pyarrow.parquet as pq

        pp = parquet_path(ctx, version.id)
        pp.parent.mkdir(parents=True, exist_ok=True)
        arrow_schema = _arrow_schema(schema)
        writer = pq.ParquetWriter(pp, arrow_schema)

    ent_specs = cfg.get("entities") or []
    rel_specs = cfg.get("relationships") or []
    ev_spec = cfg.get("events")
    geo_spec = cfg.get("geo")
    ent_cache: dict[str, Entity] = {}
    rel_cache: dict[tuple[str, str, str], Relationship] = {}
    touched: dict[str, Entity] = {}
    counters = {"records": 0, "entities_touched": 0, "relationships": 0, "events": 0, "geo_features": 0}
    preview: list[dict[str, Any]] = []
    content_hash = hashlib.sha256()
    batch_records: list[dict[str, Any]] = []
    batch_index: list[dict[str, Any]] = []
    batch_arrow: list[dict[str, Any]] = []
    batch_sources: list[dict[str, Any]] = []
    batch_events: list[dict[str, Any]] = []
    batch_geo: list[dict[str, Any]] = []
    rel_records: dict[tuple[str, str, str], list[str]] = {}
    from sqlalchemy import func

    entities_before = db.execute(select(func.count()).select_from(Entity).where(Entity.project_id == project_id)).scalar_one()
    total_bytes = max(path.stat().st_size, 1)
    now = utcnow()

    def flush():
        # Insert order respects foreign keys: records, then ORM-tracked entities/relationships, then dependents.
        if dry_run:
            return
        if batch_records:
            db.bulk_insert_mappings(Record, batch_records)
        db.flush()
        for model, rows in ((EntitySource, batch_sources), (Event, batch_events), (GeoFeature, batch_geo)):
            if rows:
                db.bulk_insert_mappings(model, rows)
                rows.clear()
        search.index_many(db, batch_index)
        if writer is not None and batch_arrow:
            import pyarrow as pa

            writer.write_table(pa.Table.from_pylist(batch_arrow, schema=writer.schema))
        batch_records.clear()
        batch_index.clear()
        batch_arrow.clear()

    prev_autoflush = db.autoflush
    db.autoflush = False  # pending entities/relationships are flushed explicitly, after their source records
    try:
        for i, raw in enumerate(parsers.iter_rows(path, stored.detected_format, opts)):
            raw = {k: parsers.jsonable(v) for k, v in raw.items()}
            norm, errors = transform(raw, mapping, null_tokens, default_tz, keep_unmapped)
            rh = row_hash(norm)
            content_hash.update(rh.encode())
            qa.observe(i, raw, norm, errors, rh)
            counters["records"] += 1
            if len(preview) < preview_limit:
                preview.append({"row_index": i, "raw": raw, "normalized": norm, "errors": errors})
            if dry_run:
                continue
            assert version is not None and dataset is not None
            rid = new_id("rec")
            batch_records.append({"id": rid, "project_id": project_id, "dataset_id": dataset.id,
                                  "dataset_version_id": version.id, "row_index": i, "raw": raw, "normalized": norm,
                                  "row_hash": rh})
            body = " ".join(f"{k}: {v}" for k, v in norm.items() if v not in (None, "") and k not in sensitive_cols)
            batch_index.append({"t": "dataset_record", "r": rid, "p": project_id, "d": dataset.id,
                                "a": dataset.access_policy, "c": now.isoformat(), "ti": f"{dataset.name} · row {i + 1}", "b": body})
            batch_arrow.append({"__record_id": rid, "__row_index": i, **{f["name"]: norm.get(f["name"]) for f in schema["fields"]}})
            row_entities: list[Entity | None] = []
            for es in ent_specs:
                attrs = {a: (raw.get(_src(mapping, a)), norm.get(a)) for a in es.get("attributes", [])}
                ent = entities.upsert_from_record(
                    db, ent_cache, project_id=project_id, entity_type=es["entity_type"],
                    name=norm.get(es["name_field"]) if es.get("name_field") else None,
                    id_field=es.get("id_field"), id_value=norm.get(es["id_field"]) if es.get("id_field") else None,
                    attributes=attrs, record_id=rid, version_id=version.id, id_namespace=es.get("id_namespace"),
                    source_rows=batch_sources)
                row_entities.append(ent)
                if ent is not None:
                    touched[ent.id] = ent
            for rs in rel_specs:
                s_ent, t_ent = row_entities[rs["source"]], row_entities[rs["target"]]
                if s_ent is None or t_ent is None or s_ent.id == t_ent.id:
                    continue
                key = (s_ent.id, t_ent.id, rs["rel_type"])
                vf = _parse_iso(norm.get(rs.get("valid_from_field"))) if rs.get("valid_from_field") else None
                rel = rel_cache.get(key)
                if rel is None:
                    rel = Relationship(id=new_id("rel"), project_id=project_id, source_entity_id=s_ent.id, target_entity_id=t_ent.id,
                                       rel_type=rs["rel_type"], assertion="observed", status="active", confidence=None,
                                       evidence={"records": [], "dataset_version_id": version.id,
                                                 "method": f"{PIPELINE_VERSION} co-occurrence in source record"},
                                       record_id=rid, valid_from=vf, created_by=f"system:{PIPELINE_VERSION}")
                    db.add(rel)
                    rel_cache[key] = rel
                    rel_records[key] = []
                    counters["relationships"] += 1
                rel_records[key].append(rid)
                if vf and (rel.valid_from is None or vf < _aware(rel.valid_from)):
                    rel.valid_from = vf
                if vf and (rel.valid_to is None or vf > _aware(rel.valid_to)):
                    rel.valid_to = vf
            if ev_spec:
                et = _parse_iso(norm.get(ev_spec["time_field"]))
                if et is not None:
                    title = _title(ev_spec, norm, dataset.name)
                    ent = row_entities[ev_spec["entity"]] if isinstance(ev_spec.get("entity"), int) and ev_spec["entity"] < len(row_entities) else None
                    lat = norm.get(geo_spec["lat_field"]) if geo_spec else None
                    lon = norm.get(geo_spec["lon_field"]) if geo_spec else None
                    batch_events.append(dict(
                        id=new_id("evt"), project_id=project_id, dataset_id=dataset.id, record_id=rid,
                        entity_id=ent.id if ent else None, title=title[:255],
                        category=ev_spec.get("category", dataset.name)[:64], event_time=et,
                        end_time=_parse_iso(norm.get(ev_spec.get("end_field"))) if ev_spec.get("end_field") else None,
                        source_timezone=(mapping.get(_src(mapping, ev_spec["time_field"]), {}).get("timezone") or default_tz),
                        source_time_text=str(raw.get(_src(mapping, ev_spec["time_field"])))[:64],
                        record_created_time=_parse_iso(norm.get(ev_spec.get("created_field"))) if ev_spec.get("created_field") else None,
                        ingested_at=now, modified_at=now,
                        latitude=lat if isinstance(lat, float) else None, longitude=lon if isinstance(lon, float) else None))
                    counters["events"] += 1
            if geo_spec:
                lat, lon = norm.get(geo_spec["lat_field"]), norm.get(geo_spec["lon_field"])
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not (lat == 0 and lon == 0):
                    ent = row_entities[geo_spec["entity"]] if isinstance(geo_spec.get("entity"), int) and geo_spec["entity"] < len(row_entities) else None
                    label = str(norm.get(geo_spec.get("label_field")) or f"{dataset.name} row {i + 1}")
                    props = {k: v for k, v in norm.items() if k not in sensitive_cols}
                    batch_geo.append(dict(
                        id=new_id("geo"), project_id=project_id, layer=dataset.name, kind="data", name=label[:255],
                        geometry={"type": "Point", "coordinates": [lon, lat]}, properties=props,
                        min_lon=lon, max_lon=lon, min_lat=lat, max_lat=lat,
                        feature_time=_parse_iso(norm.get(geo_spec.get("time_field"))) if geo_spec.get("time_field") else None,
                        record_id=rid, entity_id=ent.id if ent else None, created_by=f"system:{PIPELINE_VERSION}",
                        created_at=now))
                    counters["geo_features"] += 1
            if len(batch_records) >= BATCH:
                flush()
            if reporter and i % 500 == 0:
                reporter.progress(min(0.9, 0.05 + 0.85 * (i * 200) / total_bytes), f"Processed {i} rows")
        for key, recs in rel_records.items():
            # Evidence keeps up to 1000 source record ids per relationship plus the exact count.
            rel_cache[key].evidence = {**rel_cache[key].evidence, "records": recs[:1000], "record_count": len(recs)}
        flush()
        db.autoflush = prev_autoflush
        quality = qa.finish(prev_schema, schema)
        report: dict[str, Any] = {
            "pipeline_version": PIPELINE_VERSION, "software_version": __version__, "dry_run": dry_run,
            "file": {"id": stored.id, "name": stored.original_name, "sha256": stored.sha256, "format": stored.detected_format,
                     "size_bytes": stored.size_bytes},
            "detected": {"encoding": insp.encoding, "delimiter": insp.delimiter, "columns": insp.columns,
                         "notes": insp.notes},
            "mapping": mapping, "schema": schema, "quality": quality, "counts": counters,
            "issues": qa.issues[:200], "preview": preview,
            "duration_seconds": round(time.perf_counter() - t0, 3),
        }
        if dry_run:
            db.rollback()
            return report
        assert version is not None and dataset is not None
        for issue in qa.issues:
            db.add(QualityIssue(dataset_version_id=version.id, **issue))
        for ent in touched.values():
            entities.reindex_entity(db, ent)
        counters["entities_touched"] = len(touched)
        counters["entities_created"] = db.execute(
            select(func.count()).select_from(Entity).where(Entity.project_id == project_id)).scalar_one() - entities_before
        version.record_count = counters["records"]
        version.quality_summary = quality
        version.content_sha256 = content_hash.hexdigest()
        report["counts"] = counters
        report["dataset"] = {"id": dataset.id, "name": dataset.name, "version": version.version, "version_id": version.id}
        report.pop("preview")
        version.ingestion_report = json.loads(json.dumps(report, default=str))
        dataset.current_version = version.version
        if writer is not None:
            writer.close()
            writer = None
        if reporter:
            reporter.progress(0.97, "Committing")
        db.commit()
        return report
    except BaseException:
        db.autoflush = prev_autoflush
        db.rollback()
        if writer is not None:
            writer.close()
        if version is not None:
            parquet_path(ctx, version.id).unlink(missing_ok=True)
        raise


def _src(mapping: dict[str, dict], target: str) -> str | None:
    return next((s for s, spec in mapping.items() if spec["target"] == target), None)


def _aware(dt: datetime) -> datetime:
    from datetime import timezone

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _title(ev_spec: dict[str, Any], norm: dict[str, Any], default: str) -> str:
    if ev_spec.get("title_template"):
        # Simple {field} substitution only; no attribute access or format specs.
        return re.sub(r"\{([a-z][a-z0-9_]*)\}", lambda m: str(norm.get(m.group(1)) or ""), ev_spec["title_template"])
    if ev_spec.get("title_field") and norm.get(ev_spec["title_field"]):
        return str(norm[ev_spec["title_field"]])
    return default
