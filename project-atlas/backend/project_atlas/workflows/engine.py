"""Visual workflow engine: typed node graph validation and real execution.

A workflow definition is ``{"nodes": [{"id", "type", "params", "position"?}],
"edges": [{"source", "target", "target_port"}]}``. Every node runs a real
backend operation; nothing is simulated. Side-effecting nodes (exports,
materialization) are skipped in preview mode and require explicit
confirmation when run.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

import networkx as nx
import pandas as pd
from sqlalchemy import select

from project_atlas.core.errors import ValidationFailed
from project_atlas.database.models import Dataset, DatasetVersion, ProjectMember, Workflow, WorkflowRun, WorkflowVersion, utcnow
from project_atlas.security.rbac import project_permissions

if TYPE_CHECKING:
    from project_atlas.core.context import AtlasContext
    from project_atlas.core.jobs import JobReporter

ENGINE_VERSION = "workflow-1.0"
PREVIEW_ROWS = 200


@dataclass
class NodeSpec:
    label: str
    inputs: dict[str, str]
    output: str
    params: dict[str, dict[str, Any]]
    side_effect: bool = False
    writes_data: bool = False
    permission: str = "workflow.run"
    fn: Callable | None = None


@dataclass
class ExecContext:
    ctx: "AtlasContext"
    db: Any
    project_id: str
    user_id: str
    perms: set[str]
    preview: bool
    run_id: str | None
    logs: list[dict[str, Any]] = field(default_factory=list)

    def log(self, node: str, level: str, msg: str) -> None:
        self.logs.append({"at": utcnow().isoformat(), "node": node, "level": level, "message": msg})


NODE_TYPES: dict[str, NodeSpec] = {}


def node(name: str, **kw):
    def deco(fn):
        NODE_TYPES[name] = NodeSpec(fn=fn, **kw)
        return fn

    return deco


def _p(type_: str, required: bool = False, **extra) -> dict[str, Any]:
    return {"type": type_, "required": required, **extra}


def _version(ex: ExecContext, dataset_id: str, version: int | None) -> tuple[Dataset, DatasetVersion]:
    ds = ex.db.get(Dataset, dataset_id)
    if ds is None or ds.project_id != ex.project_id:
        raise ValidationFailed("Dataset not found")
    if ds.access_policy == "restricted" and "dataset.read_restricted" not in ex.perms:
        raise ValidationFailed("Dataset not found")
    v = version or ds.current_version
    dv = ex.db.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id, DatasetVersion.version == v)).scalar_one_or_none()
    if dv is None:
        raise ValidationFailed(f"Dataset version {v} not found")
    return ds, dv


# --------------------------------------------------------------------------- node implementations


@node("dataset_input", label="Dataset input", inputs={}, output="table",
      params={"dataset_id": _p("dataset", True), "version": _p("integer")})
def n_dataset_input(ex: ExecContext, inp, params):
    from project_atlas.ingestion.service import parquet_path

    ds, dv = _version(ex, params["dataset_id"], params.get("version"))
    df = pd.read_parquet(parquet_path(ex.ctx, dv.id))
    if "sensitive.read" not in ex.perms:
        hidden = [f["name"] for f in dv.schema_json["fields"] if f.get("sensitive") and f["name"] in df.columns]
        df = df.drop(columns=hidden)
    if ex.preview:
        df = df.head(PREVIEW_ROWS)
    df.attrs["lineage"] = [{"dataset_id": ds.id, "version_id": dv.id, "version": dv.version, "content_sha256": dv.content_sha256}]
    return df


_OPS = {"eq", "ne", "gt", "lt", "gte", "lte", "contains", "is_null", "not_null", "in"}


@node("filter", label="Filter rows", inputs={"table": "table"}, output="table",
      params={"conditions": _p("conditions", True), "mode": _p("enum", options=["all", "any"])})
def n_filter(ex, inp, params):
    df: pd.DataFrame = inp["table"]
    masks = []
    for c in params["conditions"]:
        f, op, v = c.get("field"), c.get("op"), c.get("value")
        if f not in df.columns:
            raise ValidationFailed(f"filter: unknown field {f}")
        if op not in _OPS:
            raise ValidationFailed(f"filter: unknown operator {op}")
        s = df[f]
        if op in {"gt", "lt", "gte", "lte"}:
            num = pd.to_numeric(s, errors="coerce")
            try:
                tv = float(v)
                cmp = num
            except (TypeError, ValueError):
                cmp, tv = s.astype("string"), str(v)
            m = {"gt": cmp > tv, "lt": cmp < tv, "gte": cmp >= tv, "lte": cmp <= tv}[op]
        elif op == "eq":
            m = s.astype("string") == str(v)
        elif op == "ne":
            m = s.astype("string") != str(v)
        elif op == "contains":
            m = s.astype("string").str.contains(str(v), case=False, regex=False)
        elif op == "in":
            m = s.astype("string").isin([str(x) for x in (v or [])])
        elif op == "is_null":
            m = s.isna()
        else:
            m = s.notna()
        masks.append(m.fillna(False).astype(bool))
    if not masks:
        return df
    mask = masks[0]
    for m in masks[1:]:
        mask = (mask | m) if params.get("mode") == "any" else (mask & m)
    out = df[mask].copy()
    out.attrs = df.attrs
    return out


@node("select_columns", label="Select columns", inputs={"table": "table"}, output="table",
      params={"columns": _p("fields", True)})
def n_select(ex, inp, params):
    df = inp["table"]
    missing = [c for c in params["columns"] if c not in df.columns]
    if missing:
        raise ValidationFailed(f"select_columns: unknown fields {missing}")
    keep = [c for c in ["__record_id", "__row_index"] if c in df.columns] + [c for c in params["columns"] if not c.startswith("__")]
    out = df[keep].copy()
    out.attrs = df.attrs
    return out


@node("normalize", label="Normalize text", inputs={"table": "table"}, output="table",
      params={"fields": _p("fields", True), "case": _p("enum", options=["lower", "upper", "title", "none"]),
              "trim": _p("boolean")})
def n_normalize(ex, inp, params):
    df = inp["table"].copy()
    for f in params["fields"]:
        if f not in df.columns:
            raise ValidationFailed(f"normalize: unknown field {f}")
        s = df[f].astype("string")
        if params.get("trim", True):
            s = s.str.strip().str.replace(r"\s+", " ", regex=True)
        case = params.get("case", "none")
        if case == "lower":
            s = s.str.lower()
        elif case == "upper":
            s = s.str.upper()
        elif case == "title":
            s = s.str.title()
        df[f] = s
    df.attrs = inp["table"].attrs
    return df


@node("join", label="Join tables", inputs={"left": "table", "right": "table"}, output="table",
      params={"left_on": _p("field", True), "right_on": _p("field", True),
              "how": _p("enum", options=["inner", "left"])})
def n_join(ex, inp, params):
    left, right = inp["left"], inp["right"]
    for side, df, key in (("left", left, params["left_on"]), ("right", right, params["right_on"])):
        if key not in df.columns:
            raise ValidationFailed(f"join: {side} table has no field {key}")
    how = params.get("how", "inner")
    if how not in {"inner", "left"}:
        raise ValidationFailed("join: how must be inner or left")
    out = left.merge(right, how=how, left_on=params["left_on"], right_on=params["right_on"], suffixes=("", "_right"))
    out.attrs["lineage"] = left.attrs.get("lineage", []) + right.attrs.get("lineage", [])
    return out


@node("dedupe", label="Remove duplicates", inputs={"table": "table"}, output="table", params={"keys": _p("fields")})
def n_dedupe(ex, inp, params):
    df = inp["table"]
    keys = params.get("keys") or [c for c in df.columns if not c.startswith("__")]
    missing = [k for k in keys if k not in df.columns]
    if missing:
        raise ValidationFailed(f"dedupe: unknown fields {missing}")
    out = df.drop_duplicates(subset=keys, keep="first").copy()
    out.attrs = df.attrs
    ex.log("dedupe", "info", f"removed {len(df) - len(out)} duplicate rows on {keys}")
    return out


@node("quality_check", label="Quality check", inputs={"table": "table"}, output="quality",
      params={"required": _p("fields")})
def n_quality(ex, inp, params):
    df = inp["table"]
    cols = [c for c in df.columns if not c.startswith("__")]
    req = params.get("required") or []
    return {"rows": len(df), "missing_by_field": {c: int(df[c].isna().sum()) for c in cols},
            "required_violations": {r: int(df[r].isna().sum()) for r in req if r in df.columns},
            "duplicate_rows": int(df[cols].duplicated().sum()) if cols else 0}


@node("statistics", label="Statistics", inputs={"table": "table"}, output="analysis",
      params={"kind": _p("enum", True, options=["describe", "frequency", "trend", "correlation", "outliers", "missing", "timeseries"]),
              "analysis_params": _p("object")})
def n_statistics(ex, inp, params):
    from project_atlas.analytics import service as an

    t0 = time.perf_counter()
    res = an.run_dataset_analysis(inp["table"], params["kind"], params.get("analysis_params") or {})
    if ex.preview:
        return res
    run = an.record_run(ex.db, project_id=ex.project_id, kind=params["kind"],
                        params={**(params.get("analysis_params") or {}), "workflow_run_id": ex.run_id},
                        inputs={"dataset_versions": inp["table"].attrs.get("lineage", []), "via": "workflow"},
                        algorithm_version=an.ALGORITHM_VERSIONS[params["kind"]], result=res, started=t0, user_id=ex.user_id, commit=False)
    return {"analysis_run_id": run.id, "result_sha256": run.result_sha256, "summary": res}


@node("timeline_analysis", label="Timeline analysis", inputs={"table": "table"}, output="analysis",
      params={"time_field": _p("field", True)})
def n_timeline(ex, inp, params):
    from project_atlas.analytics import service as an

    return an.timeseries(inp["table"], {"time_field": params["time_field"]})


@node("graph_build", label="Build graph", inputs={"table": "table"}, output="graph",
      params={"source_field": _p("field", True), "target_field": _p("field", True)})
def n_graph(ex, inp, params):
    df = inp["table"]
    s, t = params["source_field"], params["target_field"]
    for f in (s, t):
        if f not in df.columns:
            raise ValidationFailed(f"graph_build: unknown field {f}")
    g = nx.Graph()
    for a, b in df[[s, t]].dropna().itertuples(index=False):
        g.add_edge(str(a), str(b))
    deg = sorted(g.degree, key=lambda x: (-x[1], x[0]))[:20]
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "components": nx.number_connected_components(g) if g.number_of_nodes() else 0,
            "top_degree": [{"node": n, "degree": d} for n, d in deg],
            "note": "Ephemeral graph built from table columns; not persisted to the knowledge graph."}


@node("entity_resolution", label="Entity resolution", inputs={}, output="candidates",
      params={"entity_type": _p("string"), "threshold": _p("number")}, permission="entity.resolve")
def n_resolution(ex, inp, params):
    from project_atlas.entities.service import resolve

    if ex.preview:
        return {"skipped": "entity resolution writes candidates; skipped in preview"}
    return resolve(ex.db, ex.project_id, params.get("entity_type"), float(params.get("threshold", 0.75)))


@node("document_search", label="Document retrieval", inputs={}, output="passages", params={"query": _p("string", True)},
      permission="document.read")
def n_docsearch(ex, inp, params):
    from project_atlas.documents.service import retrieve

    hits = retrieve(ex.db, ex.project_id, params["query"], k=10)
    return {"query": params["query"], "passages": [{k: h[k] for k in ("document_id", "title", "page", "chunk_id", "score")}
                                                   | {"excerpt": h["text"][:300]} for h in hits]}


@node("embedding_generation", label="Embedding generation", inputs={}, output="embeddings", params={},
      permission="ai.use", side_effect=True)
def n_embed(ex, inp, params):
    from project_atlas.ai import service as ai

    m = ai.default_model(ex.db, "embedding")
    if m is None or not ex.ctx.settings.ai_enabled:
        raise ValidationFailed("No healthy local embedding model is available (AI is optional)")

    class _R:
        def progress(self, *_a, **_k):
            pass

    return ai.embed_project_chunks(ex.ctx, ex.project_id, m.id, _R())


@node("export_csv", label="Export CSV", inputs={"table": "table"}, output="artifact",
      params={"filename": _p("string", True)}, side_effect=True, permission="report.export")
def n_export(ex, inp, params):
    import hashlib
    import re

    name = re.sub(r"[^A-Za-z0-9_.-]", "_", params["filename"])[:100]
    if not name.endswith(".csv"):
        name += ".csv"
    d = ex.ctx.settings.exports_dir / ex.project_id / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{ex.run_id}-{name}"
    inp["table"].to_csv(path, index=False)
    return {"path": str(path.relative_to(ex.ctx.settings.storage_dir)), "rows": len(inp["table"]),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@node("materialize_dataset", label="Save as dataset version", inputs={"table": "table"}, output="dataset",
      params={"dataset_name": _p("string", True)}, side_effect=True, writes_data=True, permission="workflow.write_data")
def n_materialize(ex, inp, params):
    return materialize(ex, inp["table"], params["dataset_name"])


@node("report_export", label="Export report", inputs={}, output="artifact",
      params={"report_id": _p("report", True), "format": _p("enum", True, options=["pdf", "html", "json", "csv", "xlsx"])},
      side_effect=True, permission="report.export")
def n_report(ex, inp, params):
    from project_atlas.reporting.service import export_report

    rex = export_report(ex.ctx, ex.db, project_id=ex.project_id, report_id=params["report_id"], fmt=params["format"],
                        user_id=ex.user_id, perms=ex.perms)
    return {"export_id": rex.id, "sha256": rex.sha256, "format": rex.format}


def materialize(ex: ExecContext, df: pd.DataFrame, name: str) -> dict[str, Any]:
    import hashlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    from project_atlas.database.models import Record, new_id
    from project_atlas.ingestion.service import parquet_path, row_hash
    from project_atlas.search import service as search

    name = name.strip()[:128]
    ds = ex.db.execute(select(Dataset).where(Dataset.project_id == ex.project_id, Dataset.name == name)).scalar_one_or_none()
    if ds is None:
        ds = Dataset(project_id=ex.project_id, name=name, description="Created by workflow", owner_id=ex.user_id)
        ex.db.add(ds)
        ex.db.flush()
    cols = [c for c in df.columns if not c.startswith("__")]
    schema = {"fields": [{"name": c, "type": _dtype(df[c]), "source": c, "sensitive": False, "required": False} for c in cols]}
    dv = DatasetVersion(dataset_id=ds.id, version=ds.current_version + 1, file_id=None, origin="workflow",
                        parent_version_id=(df.attrs.get("lineage") or [{}])[0].get("version_id"), schema_json=schema,
                        import_config={"workflow_run_id": ex.run_id, "lineage": df.attrs.get("lineage", [])},
                        imported_by=ex.user_id)
    ex.db.add(dv)
    ex.db.flush()
    h = hashlib.sha256()
    recs, idx, arrow_rows = [], [], []
    for i, row in enumerate(json.loads(df[cols].to_json(orient="records", date_format="iso"))):
        rid = new_id("rec")
        rh = row_hash(row)
        h.update(rh.encode())
        recs.append({"id": rid, "project_id": ex.project_id, "dataset_id": ds.id, "dataset_version_id": dv.id, "row_index": i,
                     "raw": row, "normalized": row, "row_hash": rh})
        idx.append({"t": "dataset_record", "r": rid, "p": ex.project_id, "d": ds.id, "a": ds.access_policy,
                    "c": utcnow().isoformat(), "ti": f"{ds.name} · row {i + 1}",
                    "b": " ".join(f"{k}: {v}" for k, v in row.items() if v is not None)})
        arrow_rows.append({"__record_id": rid, "__row_index": i, **row})
    if recs:
        ex.db.bulk_insert_mappings(Record, recs)
        search.index_many(ex.db, idx)
    p = parquet_path(ex.ctx, dv.id)
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(arrow_rows) if arrow_rows else pa.table({"__record_id": pa.array([], pa.string())}), p)
    dv.record_count = len(recs)
    dv.content_sha256 = h.hexdigest()
    dv.ingestion_report = {"pipeline_version": ENGINE_VERSION, "origin": "workflow", "workflow_run_id": ex.run_id}
    ds.current_version = dv.version
    ex.db.flush()
    return {"dataset_id": ds.id, "version": dv.version, "version_id": dv.id, "records": len(recs)}


def _dtype(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_integer_dtype(s):
        return "integer"
    if pd.api.types.is_float_dtype(s):
        return "float"
    return "string"


# --------------------------------------------------------------------------- validation & execution


def catalog() -> list[dict[str, Any]]:
    return [{"type": k, "label": v.label, "inputs": v.inputs, "output": v.output, "params": v.params,
             "side_effect": v.side_effect, "writes_data": v.writes_data, "permission": v.permission}
            for k, v in NODE_TYPES.items()]


def validate(defn: dict[str, Any]) -> list[str]:
    """Return topological order of node ids or raise ValidationFailed with all problems."""
    errors: list[str] = []
    nodes = defn.get("nodes") or []
    edges = defn.get("edges") or []
    if not nodes:
        raise ValidationFailed("Workflow has no nodes")
    if len(nodes) > 100:
        raise ValidationFailed("Workflow too large (max 100 nodes)")
    by_id: dict[str, dict] = {}
    for n in nodes:
        nid = str(n.get("id", ""))
        if not nid or nid in by_id:
            errors.append(f"duplicate or missing node id {nid!r}")
            continue
        by_id[nid] = n
        spec = NODE_TYPES.get(n.get("type"))
        if spec is None:
            errors.append(f"{nid}: unknown node type {n.get('type')!r}")
            continue
        params = n.get("params") or {}
        for pname, pspec in spec.params.items():
            if pspec.get("required") and params.get(pname) in (None, "", []):
                errors.append(f"{nid}: missing required parameter {pname}")
            if pspec["type"] == "enum" and params.get(pname) not in (None, *pspec.get("options", [])):
                errors.append(f"{nid}: {pname} must be one of {pspec['options']}")
        unknown = set(params) - set(spec.params) - {"retries"}
        if unknown:
            errors.append(f"{nid}: unknown parameters {sorted(unknown)}")
    incoming: dict[str, dict[str, str]] = defaultdict(dict)
    g = nx.DiGraph()
    g.add_nodes_from(by_id)
    for e in edges:
        s, t, port = e.get("source"), e.get("target"), e.get("target_port")
        if s not in by_id or t not in by_id:
            errors.append(f"edge {s}->{t} references unknown node")
            continue
        ts, ss = NODE_TYPES.get(by_id[t].get("type")), NODE_TYPES.get(by_id[s].get("type"))
        if ts is None or ss is None:
            continue
        if port is None and len(ts.inputs) == 1:
            port = next(iter(ts.inputs))
        if port not in ts.inputs:
            errors.append(f"{t}: no input port {port!r}")
            continue
        if ts.inputs[port] != ss.output:
            errors.append(f"type mismatch: {s} outputs {ss.output} but {t}.{port} expects {ts.inputs[port]}")
        if port in incoming[t]:
            errors.append(f"{t}.{port} has more than one incoming edge")
        incoming[t][port] = s
        g.add_edge(s, t)
    for nid, n in by_id.items():
        spec = NODE_TYPES.get(n.get("type"))
        if spec:
            for port in spec.inputs:
                if port not in incoming[nid]:
                    errors.append(f"{nid}: input {port} is not connected")
    if not nx.is_directed_acyclic_graph(g):
        errors.append("workflow contains a cycle")
    if errors:
        raise ValidationFailed("Workflow is invalid", details={"errors": errors})
    return list(nx.lexicographical_topological_sort(g))


def _summarize(out: Any) -> dict[str, Any]:
    if isinstance(out, pd.DataFrame):
        sample = json.loads(out.head(20).to_json(orient="records", date_format="iso", default_handler=str))
        return {"kind": "table", "rows": len(out), "columns": [c for c in out.columns], "sample": sample,
                "lineage": out.attrs.get("lineage", [])}
    return {"kind": "object", "value": json.loads(json.dumps(out, default=str))}


def run_definition(ex: ExecContext, defn: dict[str, Any], reporter: "JobReporter | None" = None,
                   confirm_side_effects: bool = False) -> dict[str, Any]:
    order = validate(defn)
    nodes = {n["id"]: n for n in defn["nodes"]}
    inputs_of: dict[str, dict[str, str]] = defaultdict(dict)
    for e in defn.get("edges", []):
        spec = NODE_TYPES[nodes[e["target"]]["type"]]
        inputs_of[e["target"]][e.get("target_port") or next(iter(spec.inputs))] = e["source"]
    for nid in order:
        spec = NODE_TYPES[nodes[nid]["type"]]
        if spec.permission not in ex.perms and not (ex.preview and spec.side_effect):
            raise ValidationFailed(f"{nid}: your role lacks permission {spec.permission}")
        if spec.side_effect and not ex.preview and not confirm_side_effects:
            raise ValidationFailed(f"{nid}: {spec.label} has side effects; confirm the run to proceed",
                                   details={"requires_confirmation": True})
    outputs: dict[str, Any] = {}
    results: dict[str, Any] = {}
    for i, nid in enumerate(order):
        n = nodes[nid]
        spec = NODE_TYPES[n["type"]]
        if reporter:
            reporter.progress(i / len(order), f"Running {nid} ({spec.label})")
        if ex.preview and spec.side_effect:
            results[nid] = {"status": "skipped", "reason": "side-effecting node skipped in preview"}
            ex.log(nid, "info", "skipped in preview")
            continue
        if any(results.get(src, {}).get("status") != "succeeded" for src in inputs_of[nid].values()):
            results[nid] = {"status": "skipped", "reason": "upstream node did not succeed"}
            continue
        retries = int((n.get("params") or {}).get("retries", 0))
        params = {k: v for k, v in (n.get("params") or {}).items() if k != "retries"}
        attempt = 0
        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                out = spec.fn(ex, {port: outputs[src] for port, src in inputs_of[nid].items()}, params)
                outputs[nid] = out
                results[nid] = {"status": "succeeded", "attempts": attempt,
                                "duration_ms": round((time.perf_counter() - t0) * 1000, 2), "output": _summarize(out)}
                ex.log(nid, "info", f"succeeded in {results[nid]['duration_ms']} ms")
                break
            except ValidationFailed as exc:
                results[nid] = {"status": "failed", "attempts": attempt, "error": exc.message, "details": exc.details}
                ex.log(nid, "error", exc.message)
                break  # configuration errors are not retried
            except Exception as exc:  # noqa: BLE001 - node boundary
                ex.log(nid, "error", f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt > retries:
                    results[nid] = {"status": "failed", "attempts": attempt, "error": f"{type(exc).__name__}: {exc}"}
                    break
        if reporter:
            reporter.check_cancel()
    status = "succeeded" if all(r["status"] in {"succeeded", "skipped"} for r in results.values()) and \
        any(r["status"] == "succeeded" for r in results.values()) else "failed"
    return {"status": status, "order": order, "nodes": results, "engine_version": ENGINE_VERSION}


def perms_for(db, project_id: str, user_id: str) -> set[str]:
    m = db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)).scalar_one_or_none()
    return project_permissions(m.role if m else None)


def execute_run(ctx: "AtlasContext", job, reporter: "JobReporter") -> dict[str, Any]:
    run_id = job.params["run_id"]
    with ctx.sm() as db:
        run = db.get(WorkflowRun, run_id)
        wv = db.get(WorkflowVersion, run.workflow_version_id)
        run.status = "running"
        db.commit()
        ex = ExecContext(ctx=ctx, db=db, project_id=job.project_id, user_id=job.created_by,
                         perms=perms_for(db, job.project_id, job.created_by), preview=False, run_id=run_id)
        try:
            res = run_definition(ex, wv.definition, reporter, confirm_side_effects=bool(job.params.get("confirm")))
        except Exception as exc:
            db.rollback()
            run = db.get(WorkflowRun, run_id)
            run.status = "failed"
            run.logs = ex.logs + [{"at": utcnow().isoformat(), "node": None, "level": "error",
                                   "message": getattr(exc, "message", str(exc))}]
            db.commit()
            raise
        if res["status"] == "succeeded":
            db.commit()  # commit side effects (analysis runs, materialized datasets)
        else:
            db.rollback()
        run = db.get(WorkflowRun, run_id)
        run.status = res["status"]
        run.node_results = res["nodes"]
        run.logs = ex.logs
        db.commit()
    if res["status"] != "succeeded":
        failed = [k for k, v in res["nodes"].items() if v["status"] == "failed"]
        raise RuntimeError(f"Workflow failed at node(s): {', '.join(failed)}; side effects rolled back")
    return {"run_id": run_id, "status": res["status"], "order": res["order"]}
