"""Unified full-text search over datasets, entities, relationships, documents and reports.

SQLite uses an FTS5 virtual table; PostgreSQL uses a generated tsvector
column. User query syntax is parsed and re-emitted so that raw FTS syntax
from users can never reach the engine unescaped.

Query syntax::

    alpha beta            implicit AND
    "exact phrase"        phrase
    alpha OR beta         Boolean OR (AND / NOT also supported, NOT is binary)
    (a OR b) AND c        grouping
    pref*                 prefix
    type:entity           filter by result type (dataset_record, entity, relationship, document, report)
    amount>100 city:Oslo  record field filters (numeric >, <, >=, <= and equality)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from project_atlas.core.errors import ValidationFailed

DOC_TYPES = {"dataset_record", "entity", "relationship", "document", "report", "investigation"}

_TOKEN_RE = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')
_FIELD_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)(:|>=|<=|>|<)(.+)$")
_WORD_RE = re.compile(r"^[\w\-.@'+]+\*?$", re.UNICODE)


@dataclass
class ParsedQuery:
    fts: str
    types: set[str] = field(default_factory=set)
    field_filters: list[tuple[str, str, str]] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)


def parse_query(q: str) -> ParsedQuery:
    if len(q) > 1000:
        raise ValidationFailed("Query too long")
    tokens = _TOKEN_RE.findall(q)
    out: list[str] = []
    pq = ParsedQuery(fts="")
    depth = 0
    prev_kind = "start"  # start | term | op | open | close
    for tok in tokens:
        upper = tok.upper()
        if tok.startswith('"'):
            inner = tok.strip('"').replace('"', "").strip()
            if not inner:
                continue
            if prev_kind in {"term", "close"}:
                out.append("AND")
            out.append('"' + inner + '"')
            pq.terms.extend(inner.split())
            prev_kind = "term"
        elif tok == "(":
            if prev_kind in {"term", "close"}:
                out.append("AND")
            out.append("(")
            depth += 1
            prev_kind = "open"
        elif tok == ")":
            depth -= 1
            if depth < 0 or prev_kind in {"op", "open", "start"}:
                raise ValidationFailed("Unbalanced or empty parentheses in query")
            out.append(")")
            prev_kind = "close"
        elif upper in {"AND", "OR", "NOT"}:
            if prev_kind in {"start", "op", "open"}:
                raise ValidationFailed(f"Operator {upper} must follow a term")
            out.append(upper)
            prev_kind = "op"
        else:
            m = _FIELD_RE.match(tok)
            if m and not tok.startswith("http"):
                name, op, value = m.groups()
                if name == "type" and op == ":":
                    for t in value.split(","):
                        if t not in DOC_TYPES:
                            raise ValidationFailed(f"Unknown type filter {t!r}")
                        pq.types.add(t)
                else:
                    pq.field_filters.append((name, op, value.strip('"')))
                continue
            if not _WORD_RE.match(tok):
                tok = re.sub(r"[^\w\-.@'+*]", " ", tok).strip()
                if not tok:
                    continue
                parts = tok.split()
            else:
                parts = [tok]
            for part in parts:
                if prev_kind in {"term", "close"}:
                    out.append("AND")
                prefix = part.endswith("*")
                word = part.rstrip("*").replace('"', "")
                if not word:
                    continue
                out.append(f'"{word}"' + ("*" if prefix else ""))
                pq.terms.append(word)
                prev_kind = "term"
    if depth != 0:
        raise ValidationFailed("Unbalanced parentheses in query")
    while out and out[-1] in {"AND", "OR", "NOT"}:
        out.pop()
    pq.fts = " ".join(out)
    return pq


def index_item(db: Session, *, doc_type: str, ref_id: str, project_id: str, title: str, body: str,
               dataset_id: str | None = None, access: str = "project", created_at: datetime | None = None) -> None:
    db.execute(
        text("INSERT INTO search_index (doc_type, ref_id, project_id, dataset_id, access, created_at, title, body) "
             "VALUES (:t, :r, :p, :d, :a, :c, :ti, :b)"),
        {"t": doc_type, "r": ref_id, "p": project_id, "d": dataset_id, "a": access,
         "c": (created_at.isoformat() if created_at else datetime.now(timezone.utc).isoformat()), "ti": title[:500],
         "b": body[:20000]},
    )


def index_many(db: Session, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    db.execute(
        text("INSERT INTO search_index (doc_type, ref_id, project_id, dataset_id, access, created_at, title, body) "
             "VALUES (:t, :r, :p, :d, :a, :c, :ti, :b)"),
        rows,
    )


def remove_item(db: Session, ref_id: str) -> None:
    db.execute(text("DELETE FROM search_index WHERE ref_id = :r"), {"r": ref_id})


def remove_dataset(db: Session, dataset_id: str) -> None:
    db.execute(text("DELETE FROM search_index WHERE dataset_id = :d"), {"d": dataset_id})


def set_dataset_access(db: Session, dataset_id: str, access: str) -> None:
    if db.bind.dialect.name == "sqlite":
        # FTS5 supports UPDATE of UNINDEXED columns.
        db.execute(text("UPDATE search_index SET access = :a WHERE dataset_id = :d"), {"a": access, "d": dataset_id})
    else:
        db.execute(text("UPDATE search_index SET access = :a WHERE dataset_id = :d"), {"a": access, "d": dataset_id})


def _match_field(value: Any, op: str, target: str) -> bool:
    if value is None:
        return False
    if op == ":":
        return str(value).lower() == target.lower() or target.lower() in str(value).lower()
    try:
        a, b = float(value), float(target)
    except (TypeError, ValueError):
        a, b = str(value), target  # ISO dates compare lexicographically
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]


def search(db: Session, *, query: str, scopes: list[tuple[str, bool]], types: list[str] | None = None,
           date_from: str | None = None, date_to: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """``scopes`` lists (project_id, may_read_restricted) for every project the caller may search."""
    pq = parse_query(query)
    wanted = set(types or []) | pq.types
    if not scopes:
        return {"total": 0, "results": [], "parsed": pq.fts}
    if not pq.fts and not pq.field_filters:
        raise ValidationFailed("Query is empty")
    params: dict[str, Any] = {}
    scope_sql = []
    for i, (pid, restricted_ok) in enumerate(scopes):
        params[f"p{i}"] = pid
        scope_sql.append(f"(project_id = :p{i}" + ("" if restricted_ok else " AND access != 'restricted'") + ")")
    where = ["(" + " OR ".join(scope_sql) + ")"]
    if wanted:
        where.append("doc_type IN (" + ",".join(f":t{i}" for i in range(len(wanted))) + ")")
        params.update({f"t{i}": t for i, t in enumerate(sorted(wanted))})
    if pq.field_filters:
        where.append("doc_type = 'dataset_record'")
    if date_from:
        where.append("created_at >= :df")
        params["df"] = date_from
    if date_to:
        where.append("created_at <= :dt")
        params["dt"] = date_to + ("T23:59:59.999999" if len(date_to) == 10 else "")
    fetch_limit = 2000 if pq.field_filters else limit + offset
    dialect = db.bind.dialect.name
    if dialect == "sqlite":
        if pq.fts:
            where.insert(0, "search_index MATCH :q")
            params["q"] = pq.fts
            sql = ("SELECT doc_type, ref_id, project_id, dataset_id, title, created_at, "
                   "snippet(search_index, 7, '[[', ']]', ' … ', 18) AS snip, bm25(search_index) AS score "
                   f"FROM search_index WHERE {' AND '.join(where)} ORDER BY score LIMIT :lim")
            count_sql = f"SELECT count(*) FROM search_index WHERE {' AND '.join(where)}"
        else:
            sql = ("SELECT doc_type, ref_id, project_id, dataset_id, title, created_at, substr(body, 1, 200) AS snip, 0 AS score "
                   f"FROM search_index WHERE {' AND '.join(where)} LIMIT :lim")
            count_sql = f"SELECT count(*) FROM search_index WHERE {' AND '.join(where)}"
    else:  # PostgreSQL: websearch-style tsquery from sanitized terms
        if pq.fts:
            where.insert(0, "tsv @@ websearch_to_tsquery('simple', :q)")
            params["q"] = pq.fts.replace(" AND ", " ").replace(" NOT ", " -")
        sql = ("SELECT doc_type, ref_id, project_id, dataset_id, title, created_at, substr(body, 1, 200) AS snip, "
               + ("-ts_rank(tsv, websearch_to_tsquery('simple', :q))" if pq.fts else "0") + " AS score "
               f"FROM search_index WHERE {' AND '.join(where)} ORDER BY score LIMIT :lim")
        count_sql = f"SELECT count(*) FROM search_index WHERE {' AND '.join(where)}"
    try:
        total = db.execute(text(count_sql), params).scalar_one()
        rows = db.execute(text(sql), {**params, "lim": fetch_limit}).mappings().all()
    except Exception as exc:  # malformed query that slipped through parsing
        raise ValidationFailed(f"Search query could not be executed: {exc.__class__.__name__}") from exc
    results = [dict(r) for r in rows]
    if pq.field_filters:
        from project_atlas.database.models import Record

        ids = [r["ref_id"] for r in results]
        recs = {r.id: r for r in db.query(Record).filter(Record.id.in_(ids)).all()} if ids else {}
        kept = []
        for r in results:
            rec = recs.get(r["ref_id"])
            if rec and all(_match_field(rec.normalized.get(f), op, v) for f, op, v in pq.field_filters):
                kept.append(r)
        total = len(kept)
        results = kept
    results = results[offset: offset + limit]
    for r in results:
        r["score"] = round(-float(r["score"] or 0), 4)
    return {"total": total, "results": results, "parsed": pq.fts, "field_filters": pq.field_filters}
