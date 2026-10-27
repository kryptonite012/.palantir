"""Streaming data-quality checks.

Checks are configurable via ``quality`` in the import configuration::

    {"required": ["name"], "unique": ["person_id"], "future_tolerance_days": 1,
     "min_year": 1900, "references": {"org_id": {"dataset_id": "...", "field": "org_id"}}}

Every issue carries the row index, field, check id, severity and message.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from project_atlas.ingestion.normalize import UNIT_RE

MOJIBAKE_RE = re.compile(r"(Ã[\x80-\xbf¡-ÿ]|â€|Â[\xa0-\xbf])")
MAX_ISSUES_PER_CHECK = 500
ALGORITHM_VERSION = "quality-1.0"


class QualityAccumulator:
    def __init__(self, config: dict[str, Any], mapping: dict[str, dict[str, Any]],
                 reference_values: dict[str, set[str]] | None = None):
        self.config = config or {}
        self.mapping = mapping
        self.required = set(self.config.get("required", [])) | {
            spec["target"] for spec in mapping.values() if spec.get("required")
        }
        self.unique = list(self.config.get("unique", []))
        self.future_tol = timedelta(days=float(self.config.get("future_tolerance_days", 1)))
        self.min_year = int(self.config.get("min_year", 1900))
        self.references = reference_values or {}
        self.issues: list[dict[str, Any]] = []
        self.counts: dict[str, int] = defaultdict(int)
        self.missing: dict[str, int] = defaultdict(int)
        self.row_hashes: dict[str, int] = {}
        self.key_values: dict[str, dict[Any, int]] = defaultdict(dict)
        self.units: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.rows = 0
        self.rows_with_errors: set[int] = set()
        self.now = datetime.now(timezone.utc)

    def _add(self, row: int | None, field: str | None, check: str, severity: str, message: str, value: Any = None):
        self.counts[check] += 1
        if severity == "error" and row is not None:
            self.rows_with_errors.add(row)
        if self.counts[check] <= MAX_ISSUES_PER_CHECK:
            self.issues.append({"row_index": row, "field": field, "check": check, "severity": severity,
                                "message": message, "value": None if value is None else str(value)[:500]})

    def observe(self, row_index: int, raw: dict[str, Any], normalized: dict[str, Any], errors: dict[str, str],
                row_hash: str) -> None:
        self.rows += 1
        if "__parse_error__" in raw:
            self._add(row_index, None, "parse_error", "error", raw["__parse_error__"])
        if "__extra_columns__" in raw:
            self._add(row_index, None, "extra_columns", "warning", "Row has more values than header columns")
        # encoding problems in any raw string
        for k, v in raw.items():
            if isinstance(v, str) and ("�" in v or MOJIBAKE_RE.search(v)):
                self._add(row_index, k, "encoding", "warning", "Value contains replacement or mojibake characters", v)
        for target, err in errors.items():
            check = "invalid_format"
            spec_type = next((s.get("type") for s in self.mapping.values() if s["target"] == target), "")
            if spec_type in {"datetime", "date"}:
                check = "timestamp_error"
            elif spec_type in {"latitude", "longitude"}:
                check = "coordinate_error"
            elif spec_type in {"integer", "float", "boolean"}:
                check = "unexpected_type"
            self._add(row_index, target, check, "error", err)
        for f in self.required:
            if normalized.get(f) in (None, ""):
                self.missing[f] += 1
                self._add(row_index, f, "missing_required", "error", f"Required field {f} is missing")
        for f, v in normalized.items():
            if v is None and f not in self.required:
                self.missing[f] += 1
        # duplicates
        if row_hash in self.row_hashes:
            self._add(row_index, None, "duplicate_row", "warning",
                      f"Exact duplicate of row {self.row_hashes[row_hash]}")
        else:
            self.row_hashes[row_hash] = row_index
        for key in self.unique:
            v = normalized.get(key)
            if v in (None, ""):
                continue
            seen = self.key_values[key]
            if v in seen:
                self._add(row_index, key, "duplicate_key", "warning", f"Value already used by row {seen[v]}", v)
            else:
                seen[v] = row_index
        # timestamps: plausibility
        for spec in self.mapping.values():
            t, f = spec.get("type"), spec["target"]
            v = normalized.get(f)
            if v is None:
                continue
            if t == "datetime":
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt > self.now + self.future_tol:
                    self._add(row_index, f, "timestamp_error", "warning", "Timestamp is in the future", v)
                if dt.year < self.min_year:
                    self._add(row_index, f, "timestamp_error", "warning", f"Timestamp before {self.min_year}", v)
            if t == "date" and int(v[:4]) < self.min_year:
                self._add(row_index, f, "timestamp_error", "warning", f"Date before {self.min_year}", v)
        # coordinates: null island
        lat_f = next((s["target"] for s in self.mapping.values() if s.get("type") == "latitude"), None)
        lon_f = next((s["target"] for s in self.mapping.values() if s.get("type") == "longitude"), None)
        if lat_f and lon_f:
            la, lo = normalized.get(lat_f), normalized.get(lon_f)
            if la == 0 and lo == 0:
                self._add(row_index, lat_f, "coordinate_error", "warning", "Coordinates are (0, 0); likely a placeholder")
            if (la is None) != (lo is None) and lat_f not in errors and lon_f not in errors:
                self._add(row_index, lat_f, "coordinate_error", "warning", "Only one of latitude/longitude present")
        # units: collect suffixes from raw values of float columns
        for src, spec in self.mapping.items():
            if spec.get("type") == "float":
                v = raw.get(src)
                if isinstance(v, str):
                    m = UNIT_RE.match(v)
                    if m:
                        self.units[spec["target"]][m.group(2).lower()] += 1
        # referential integrity
        for f, allowed in self.references.items():
            v = normalized.get(f)
            if v not in (None, "") and str(v) not in allowed:
                self._add(row_index, f, "referential_integrity", "error", f"Value {v!r} not found in referenced dataset", v)

    def finish(self, previous_schema: dict[str, Any] | None, schema: dict[str, Any]) -> dict[str, Any]:
        for f, units in self.units.items():
            if len(units) > 1:
                self._add(None, f, "inconsistent_units", "warning",
                          f"Mixed units in column: {', '.join(f'{u} ({n})' for u, n in sorted(units.items()))}")
        drift: dict[str, Any] = {}
        if previous_schema:
            prev = {c["name"]: c["type"] for c in previous_schema.get("fields", [])}
            cur = {c["name"]: c["type"] for c in schema.get("fields", [])}
            added = sorted(set(cur) - set(prev))
            removed = sorted(set(prev) - set(cur))
            changed = sorted(k for k in set(cur) & set(prev) if cur[k] != prev[k])
            drift = {"added": added, "removed": removed, "type_changed": changed}
            if added or removed or changed:
                self._add(None, None, "schema_drift", "warning",
                          f"Schema changed vs previous version: +{added} -{removed} ~{changed}")
        completeness = {
            f: round(1 - self.missing.get(f, 0) / self.rows, 4) if self.rows else None
            for f in [c["name"] for c in schema.get("fields", [])]
        }
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "rows": self.rows,
            "rows_with_errors": len(self.rows_with_errors),
            "issue_counts": dict(self.counts),
            "errors": sum(n for c, n in self.counts.items() if any(i["check"] == c and i["severity"] == "error" for i in self.issues)),
            "warnings": sum(n for c, n in self.counts.items() if any(i["check"] == c and i["severity"] == "warning" for i in self.issues)),
            "completeness": completeness,
            "schema_drift": drift,
            "duplicate_rows": self.counts.get("duplicate_row", 0),
        }
