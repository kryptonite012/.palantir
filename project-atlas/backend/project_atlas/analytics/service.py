"""Reproducible statistical analyses over immutable dataset versions.

Each run records dataset version ids, content hashes, parameters, algorithm
and software versions, execution time and a SHA-256 of the canonical result
so a later re-run can be checked for identical output.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

import numpy as np
import pandas as pd

from project_atlas import __version__
from project_atlas.core.errors import ValidationFailed
from project_atlas.database.models import AnalysisRun

ALGORITHM_VERSIONS = {
    "describe": "describe-1.0", "frequency": "frequency-1.0", "trend": "trend-1.0", "correlation": "pearson-1.0",
    "outliers": "outliers-iqr-mad-1.0", "missing": "missing-1.0", "timeseries": "timeseries-1.0",
}

OUTLIER_DISCLAIMER = (
    "Outliers are values that are statistically unusual relative to this sample. Being an outlier is not evidence "
    "of fraud, error, or malicious activity; it indicates only that the value merits review."
)


def canonical_hash(result: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()


def _clean(v: Any) -> Any:
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 10)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return v


def _require_cols(df: pd.DataFrame, *cols: str) -> None:
    for c in cols:
        if c not in df.columns or c.startswith("__"):
            raise ValidationFailed(f"Field {c!r} does not exist in the dataset version")


def _numeric(df: pd.DataFrame, col: str) -> pd.Series:
    s = pd.to_numeric(df[col], errors="coerce")
    return s


def describe(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    cols = params.get("fields") or [c for c in df.columns if not c.startswith("__")]
    _require_cols(df, *cols)
    out = []
    for c in cols:
        s = df[c]
        entry: dict[str, Any] = {"field": c, "n": int(s.notna().sum()), "missing": int(s.isna().sum()),
                                 "distinct": int(s.nunique(dropna=True))}
        num = _numeric(df, c)
        if s.notna().sum() and num.notna().sum() == s.notna().sum() and s.dtype != bool:
            q = num.quantile([0.25, 0.5, 0.75])
            entry.update({"kind": "numeric", "mean": _clean(num.mean()), "std": _clean(num.std(ddof=1)),
                          "min": _clean(num.min()), "q1": _clean(q[0.25]), "median": _clean(q[0.5]),
                          "q3": _clean(q[0.75]), "max": _clean(num.max())})
        else:
            top = s.dropna().astype(str).value_counts().head(5)
            entry.update({"kind": "categorical", "top": [{"value": k, "count": int(v)} for k, v in top.items()]})
        out.append(entry)
    return {"rows": len(df), "fields": out,
            "assumptions": "Standard deviation uses the sample (n-1) estimator; quantiles use linear interpolation."}


def frequency(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    f = params.get("field")
    _require_cols(df, f)
    limit = int(params.get("limit", 50))
    vc = df[f].astype("string").fillna("(missing)").value_counts()
    n = int(vc.sum())
    return {"field": f, "n": n, "distinct": int(len(vc)), "truncated": len(vc) > limit,
            "values": [{"value": k, "count": int(v), "share": round(v / n, 6)} for k, v in vc.head(limit).items()]}


def _time_series(df: pd.DataFrame, field: str) -> pd.Series:
    t = pd.to_datetime(df[field], errors="coerce", utc=True)
    return t


def trend(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    tf = params.get("time_field")
    _require_cols(df, tf)
    period = params.get("period", "M")
    if period not in {"D", "W", "M", "Q", "Y"}:
        raise ValidationFailed("period must be D, W, M, Q or Y")
    t = _time_series(df, tf)
    valid = t.notna()
    vf = params.get("value_field")
    frame = pd.DataFrame({"t": t[valid].dt.tz_localize(None)})
    if vf:
        _require_cols(df, vf)
        frame["v"] = _numeric(df, vf)[valid].values
    agg_period = {"M": "M", "Q": "Q", "Y": "Y", "D": "D", "W": "W"}[period]
    grouped = frame.groupby(frame["t"].dt.to_period(agg_period))
    series = grouped["v"].sum() if vf else grouped.size()
    points = [{"period": str(k), "value": _clean(v)} for k, v in series.items()]
    slope = None
    if len(points) >= 3:
        y = np.array([p["value"] or 0 for p in points], dtype=float)
        x = np.arange(len(y), dtype=float)
        slope = _clean(np.polyfit(x, y, 1)[0])
    return {"time_field": tf, "value_field": vf, "period": period, "points": points, "n_records": int(valid.sum()),
            "excluded_missing_time": int((~valid).sum()), "linear_slope_per_period": slope,
            "assumptions": "Slope is an ordinary least-squares fit over period index; with few periods it is unstable."
                           + ("" if len(points) >= 3 else " Fewer than 3 periods: no slope computed.")}


def correlation(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    fields = params.get("fields") or []
    if len(fields) < 2:
        raise ValidationFailed("Provide at least two numeric fields")
    _require_cols(df, *fields)
    num = pd.DataFrame({f: _numeric(df, f) for f in fields})
    pairs = []
    for i, a in enumerate(fields):
        for b in fields[i + 1:]:
            sub = num[[a, b]].dropna()
            n = len(sub)
            r = _clean(sub[a].corr(sub[b])) if n >= 3 else None
            ci = None
            if r is not None and n > 3 and abs(r) < 1:
                z, se = math.atanh(r), 1 / math.sqrt(n - 3)
                ci = [round(math.tanh(z - 1.96 * se), 6), round(math.tanh(z + 1.96 * se), 6)]
            pairs.append({"a": a, "b": b, "n": n, "pearson_r": r, "ci95": ci})
    return {"pairs": pairs, "method": "Pearson product-moment; 95% CI via Fisher z-transform",
            "limitations": "Correlation measures linear association only and does not imply causation."}


def outliers(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    f = params.get("field")
    _require_cols(df, f)
    s = _numeric(df, f)
    valid = s.dropna()
    n = len(valid)
    if n < 5:
        return {"field": f, "n": n, "outliers": [], "note": "Fewer than 5 numeric values; outlier detection not meaningful.",
                "disclaimer": OUTLIER_DISCLAIMER}
    q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
    iqr = q3 - q1
    k = float(params.get("iqr_k", 1.5))
    lo, hi = q1 - k * iqr, q3 + k * iqr
    med = valid.median()
    mad = (valid - med).abs().median()
    flagged = []
    for idx, v in valid.items():
        robust_z = 0.6745 * (v - med) / mad if mad else None
        if v < lo or v > hi:
            flagged.append({"row_index": int(df.loc[idx, "__row_index"]) if "__row_index" in df else int(idx),
                            "record_id": df.loc[idx, "__record_id"] if "__record_id" in df else None,
                            "value": _clean(v), "robust_z": _clean(robust_z)})
    flagged.sort(key=lambda x: -abs(x["robust_z"] or 0))
    return {"field": f, "n": n, "method": f"Tukey fences (k={k}) with robust z (median/MAD) for ranking",
            "bounds": {"lower": _clean(lo), "upper": _clean(hi)}, "outlier_count": len(flagged),
            "outliers": flagged[: int(params.get("limit", 100))], "disclaimer": OUTLIER_DISCLAIMER}


def missing(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    cols = [c for c in df.columns if not c.startswith("__")]
    n = len(df)
    per = [{"field": c, "missing": int(df[c].isna().sum()), "share": round(float(df[c].isna().mean()), 6) if n else None}
           for c in cols]
    complete_rows = int(df[cols].notna().all(axis=1).sum()) if cols else 0
    patterns = df[cols].isna().apply(lambda r: ",".join(c for c, m in r.items() if m) or "(none)", axis=1).value_counts().head(10)
    return {"rows": n, "fields": per, "complete_rows": complete_rows,
            "top_missing_patterns": [{"missing_fields": k, "rows": int(v)} for k, v in patterns.items()]}


def timeseries(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    tf = params.get("time_field")
    _require_cols(df, tf)
    t = _time_series(df, tf).dropna().sort_values()
    if t.empty:
        return {"time_field": tf, "n": 0}
    gaps = t.diff().dropna().dt.total_seconds()
    by_hour = t.dt.hour.value_counts().sort_index()
    by_dow = t.dt.dayofweek.value_counts().sort_index()
    return {"time_field": tf, "n": int(len(t)), "first": t.iloc[0].isoformat(), "last": t.iloc[-1].isoformat(),
            "span_days": round((t.iloc[-1] - t.iloc[0]).total_seconds() / 86400, 4),
            "median_gap_seconds": _clean(gaps.median()) if len(gaps) else None,
            "max_gap_seconds": _clean(gaps.max()) if len(gaps) else None,
            "by_hour_utc": {int(k): int(v) for k, v in by_hour.items()},
            "by_weekday": {int(k): int(v) for k, v in by_dow.items()},
            "note": "All times converted to UTC; weekday 0 = Monday."}


ANALYSES = {"describe": describe, "frequency": frequency, "trend": trend, "correlation": correlation,
            "outliers": outliers, "missing": missing, "timeseries": timeseries}


def run_dataset_analysis(df: pd.DataFrame, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind not in ANALYSES:
        raise ValidationFailed(f"Unknown analysis {kind!r}")
    return ANALYSES[kind](df, params)


def record_run(db, *, project_id: str, kind: str, params: dict[str, Any], inputs: dict[str, Any], algorithm_version: str,
               result: dict[str, Any], started: float, user_id: str, reproduced_from: str | None = None,
               commit: bool = True) -> AnalysisRun:
    result = json.loads(json.dumps(result, default=_clean))
    run = AnalysisRun(project_id=project_id, kind=kind, params=params, inputs=inputs, algorithm_version=algorithm_version,
                      software_version=__version__, result=result, result_sha256=canonical_hash(result),
                      duration_ms=round((time.perf_counter() - started) * 1000, 3), reproduced_from_id=reproduced_from,
                      created_by=user_id)
    db.add(run)
    if commit:
        db.commit()
    else:
        db.flush()
    return run


def run_view(r: AnalysisRun, include_result: bool = True) -> dict[str, Any]:
    v = {"id": r.id, "kind": r.kind, "params": r.params, "inputs": r.inputs, "algorithm_version": r.algorithm_version,
         "software_version": r.software_version, "result_sha256": r.result_sha256, "duration_ms": r.duration_ms,
         "reproduced_from_id": r.reproduced_from_id, "created_by": r.created_by, "created_at": r.created_at}
    if include_result:
        v["result"] = r.result
    return v
