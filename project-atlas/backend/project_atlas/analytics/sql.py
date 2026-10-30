"""Read-only SQL over dataset versions using an isolated in-memory DuckDB.

Safety layers:
1. Static validation: one statement, must start with SELECT or WITH, no
   statements or functions that touch files, extensions or configuration.
2. Only datasets the caller may read are loaded, as in-memory tables (Arrow).
   Sensitive columns are dropped unless the caller may read sensitive data.
3. External access is disabled and the configuration locked before the user
   query runs, so even a validator bypass cannot read files or the network.
4. Row limit and wall-clock timeout (query interrupted on expiry).
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from project_atlas.core.errors import ValidationFailed

_FORBIDDEN = re.compile(
    r"\b(attach|detach|copy|export|import|install|load|pragma|set|reset|call|create|drop|alter|insert|update|delete|"
    r"merge|truncate|vacuum|checkpoint|use|grant|revoke|begin|commit|rollback|"
    r"read_csv\w*|read_json\w*|read_parquet|read_text|read_blob|parquet_scan|csv_scan|json_scan|glob|sniff_csv|"
    r"getenv|current_setting|duckdb_\w+|pg_\w+|sqlite_\w+|http\w*|s3\w*|iceberg_\w+|delta_scan|query_table|query)\s*[\(\s;]",
    re.IGNORECASE,
)
_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)


def validate_sql(sql: str) -> str:
    if len(sql) > 20000:
        raise ValidationFailed("Query too long")
    s = strip_comments(sql).strip().rstrip(";").strip()
    if not s:
        raise ValidationFailed("Query is empty")
    # string literals cannot contain statement separators we act on; strip them for checks
    no_strings = re.sub(r"'(?:[^']|'')*'", "''", s)
    if ";" in no_strings:
        raise ValidationFailed("Only a single statement is allowed")
    if not re.match(r"^(select|with)\b", no_strings, re.IGNORECASE):
        raise ValidationFailed("Only read-only SELECT/WITH queries are allowed")
    m = _FORBIDDEN.search(no_strings + " ")
    if m:
        raise ValidationFailed(f"Disallowed keyword or function: {m.group(1)}")
    return s


def table_name(dataset_name: str) -> str:
    t = re.sub(r"[^a-z0-9_]+", "_", dataset_name.lower()).strip("_")
    if not t or not t[0].isalpha():
        t = f"ds_{t}"
    return t[:62]


def run_query(sql: str, tables: dict[str, tuple[Path, list[str]]], *, row_limit: int, timeout_s: float) -> dict[str, Any]:
    """``tables`` maps table name -> (parquet path, columns to drop)."""
    stmt = validate_sql(sql)
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET threads TO 2")
        con.execute("SET memory_limit = '1GB'")
        for name, (path, drop) in tables.items():
            if not _IDENT.match(name):
                continue
            tbl = pq.read_table(path)
            keep = [c for c in tbl.column_names if c not in drop]
            arrow = tbl.select(keep)  # noqa: F841 - referenced by name below
            con.register(f"_arrow_{name}", arrow)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "_arrow_{name}"')
            con.unregister(f"_arrow_{name}")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        timer = threading.Timer(timeout_s, con.interrupt)
        timer.start()
        t0 = time.perf_counter()
        try:
            cur = con.execute(f"SELECT * FROM ({stmt}) AS atlas_q LIMIT {int(row_limit) + 1}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except duckdb.InterruptException as exc:
            raise ValidationFailed(f"Query exceeded the {timeout_s:.0f}s time limit") from exc
        except duckdb.Error as exc:
            raise ValidationFailed(f"Query error: {str(exc).splitlines()[0][:300]}") from exc
        finally:
            timer.cancel()
        truncated = len(rows) > row_limit
        rows = rows[:row_limit]
        return {"columns": cols, "rows": [[_jsonable(v) for v in r] for r in rows], "row_count": len(rows),
                "truncated": truncated, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                "tables": sorted(tables)}
    finally:
        con.close()


def _jsonable(v: Any) -> Any:
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)
