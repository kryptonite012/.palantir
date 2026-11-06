"""Vector diagrams for the Project Atlas technical overview."""

from __future__ import annotations

import math
import random

from reportlab.graphics.shapes import Circle, Drawing, Group, Line, Rect, String
from reportlab.lib import colors

from atlas_pdf_kit import (
    ACCENT, ACCENT_2, ACCENT_DEEP, CONTENT_W, DANGER, DANGER_PALE, HYPO, HYPO_PALE, INK, LINE, MUTED, OK, OK_PALE, PALE,
    RAISED, TEXT, WARN, WARN_PALE, WHITE, arrow, box, chip_flow, text, wrap,
)

W = CONTENT_W


def architecture() -> Drawing:
    rows = [
        ("API routers", ["auth", "admin", "projects", "data & jobs", "entities + graph", "search", "documents",
                         "analysis", "investigations", "workflows", "reports", "ai", "system", "workspace"], PALE, ACCENT_DEEP),
        ("Cross-cutting", ["security: Argon2id \u00b7 sessions \u00b7 TOTP \u00b7 RBAC \u00b7 rate limits",
                           "core: config validation \u00b7 context \u00b7 job runner \u00b7 network guard"], RAISED, INK),
        ("Domain services", ["ingestion", "ontology", "entities", "graph", "search", "documents", "temporal", "geospatial",
                             "analytics", "ai", "workflows", "reporting", "audit", "backup", "retention", "notifications"],
         OK_PALE, colors.HexColor("#1F6B46")),
    ]
    # dry run to measure the chip area
    probe = Group()
    y = 0
    for _, chips, _, _ in rows:
        y = chip_flow(probe, 98, y, W - 108, chips) - 9
    chip_h = -y
    store_h, gap_v = 62, 34
    api_h = 30 + chip_h + 4
    H = 6 + store_h + gap_v + api_h + 34 + 32
    d = Drawing(W, H)
    g = Group()
    top_client = H - 2
    box(g, 60, top_client - 30, W - 120, 30, fill=INK, stroke=INK,
        title="Browser or desktop window \u2014 React UI (same origin, CSP 'self')", title_color=WHITE, title_size=9.5)
    top = top_client - 30 - 34
    arrow(g, W / 2, top_client - 31, W / 2, top + 2, color=MUTED)
    text(g, W / 2 + 6, top + 15, "HTTPS via TLS reverse proxy (LAN)  \u00b7  HTTP on loopback (desktop)", size=7.6)
    bottom = top - api_h
    g.add(Rect(0, bottom, W, api_h, rx=8, ry=8, fillColor=colors.HexColor("#F6F9FC"), strokeColor=ACCENT, strokeWidth=1.1))
    text(g, 10, top - 15, "atlas-api  \u2014  one Python process (FastAPI + uvicorn)", size=10, color=ACCENT_DEEP, font="Body-Bold")
    text(g, W - 10, top - 15, "security headers \u2192 router \u2192 auth & permission \u2192 service \u2192 DB \u2192 audit",
         size=7.4, anchor="end")
    y = top - 30
    for label, chips, fill, col in rows:
        text(g, 10, y - 10, label, size=8.2, color=INK, font="Body-Bold")
        y = chip_flow(g, 98, y, W - 108, chips, fill=fill, color=col, size=7.5, h=13, gap=4) - 9
    stores = [
        ("SQLite / PostgreSQL", "system of record via SQLAlchemy + Alembic"),
        ("Search index", "SQLite FTS5 or PostgreSQL tsvector, BM25"),
        ("Parquet per version", "columnar copies for pandas / DuckDB"),
        ("Files on disk", "originals (SHA-256), exports, checkpoints"),
        ("Local model runtime", "Ollama-compatible, optional, loopback/LAN"),
    ]
    n = len(stores)
    gap = 8
    bw = (W - gap * (n - 1)) / n
    for i, (t, b) in enumerate(stores):
        x = i * (bw + gap)
        optional = i == n - 1
        box(g, x, 6, bw, store_h, fill=HYPO_PALE if optional else WHITE, stroke=HYPO if optional else LINE, title=t, body=b,
            title_size=8.6, body_size=7.3, stroke_w=0.9)
        arrow(g, x + bw / 2, bottom - 1, x + bw / 2, 6 + store_h + 2, color=HYPO if optional else MUTED,
              dash=(3, 2) if optional else None)
    d.add(g)
    return d


def ingestion_pipeline() -> Drawing:
    d = Drawing(W, 228)
    g = Group()
    steps = [("1  Upload", "allow-listed type, magic bytes, size limit, SHA-256, 0600 storage"),
             ("2  Inspect", "format, encoding, delimiter, inferred column types, preview"),
             ("3  Map", "targets, types, time zones, required & sensitive, entities, links"),
             ("4  Dry run", "full-file validation + 13 quality checks; writes nothing"),
             ("5  Commit job", "background job, one database transaction")]
    n = len(steps)
    gap = 12
    bw = (W - gap * (n - 1)) / n
    for i, (t, b) in enumerate(steps):
        x = i * (bw + gap)
        last = i == n - 1
        box(g, x, 150, bw, 72, fill=ACCENT if last else PALE, stroke=ACCENT if last else colors.HexColor("#B9D3E8"),
            title=t, body=b, title_color=WHITE if last else ACCENT_DEEP, body_color=WHITE if last else TEXT,
            title_size=9.5, body_size=7.5)
        if not last:
            arrow(g, x + bw + 1, 186, x + bw + gap - 1, 186, color=ACCENT)
    # fan-out from commit
    cx = (n - 1) * (bw + gap) + bw / 2
    outs = ["Records: raw + normalized JSON, row hash", "Quality issues (row, field, check, severity)",
            "Search index rows (with access tag)", "Entities, sources and relationships",
            "Events (UTC) and geo features", "Parquet copy of the dataset version"]
    g.add(Rect(0, 8, W, 112, rx=6, ry=6, fillColor=RAISED, strokeColor=None))
    text(g, 10, 106, "Written atomically by the commit — a failure or cancellation rolls everything back",
         size=8.6, color=INK, font="Body-Bold")
    cols = 3
    ow = (W - 20 - 8 * (cols - 1)) / cols
    for i, o in enumerate(outs):
        r, c = divmod(i, cols)
        x = 10 + c * (ow + 8)
        y = 60 - r * 42
        box(g, x, y, ow, 34, fill=WHITE, stroke=LINE, title=o, title_size=8, title_font="Body", title_color=TEXT)
    arrow(g, cx, 149, cx, 121, color=ACCENT, width=1.2)
    d.add(g)
    return d


def lineage() -> Drawing:
    d = Drawing(W, 150)
    g = Group()
    row1 = [("Source file", "original bytes, SHA-256"), ("Dataset version", "mapping, pipeline version, content hash"),
            ("Records", "raw + normalized, row hash"), ("Entities", "entity_sources, attribute record ids")]
    row2 = [("Relationships", "assertion basis + evidence record ids"), ("Analyses", "dataset version ids + hashes, result SHA-256"),
            ("Reports", "manifest: versions, parameters, redactions")]
    gap = 22
    bw = (W - gap * 3) / 4
    for i, (t, b) in enumerate(row1):
        x = i * (bw + gap)
        box(g, x, 92, bw, 50, fill=PALE if i % 2 == 0 else WHITE, stroke=colors.HexColor("#B9D3E8"), title=t, body=b,
            title_color=ACCENT_DEEP, body_color=TEXT)
        if i < 3:
            arrow(g, x + bw + 2, 117, x + bw + gap - 2, 117, color=ACCENT)
    # turn down
    xr = 3 * (bw + gap) + bw / 2
    arrow(g, xr, 91, xr, 60, color=ACCENT)
    for i, (t, b) in enumerate(row2):
        x = W - (i + 1) * bw - i * gap
        box(g, x, 8, bw, 50, fill=WHITE if i % 2 == 0 else PALE, stroke=colors.HexColor("#B9D3E8"), title=t, body=b,
            title_color=ACCENT_DEEP, body_color=TEXT)
        if i < 2:
            arrow(g, x - 2, 33, x - gap + 2, 33, color=ACCENT)
    x_last = W - 3 * bw - 2 * gap
    text(g, 0, 40, "Every hop keeps", size=8, color=MUTED, font="Body-Bold")
    text(g, 0, 29, "a pointer back to", size=8, color=MUTED)
    text(g, 0, 18, "the original bytes.", size=8, color=MUTED)
    _ = x_last
    d.add(g)
    return d


def data_model_map() -> Drawing:
    d = Drawing(W, 296)
    g = Group()
    areas = [
        ("Identity", "users · sessions · password_reset_tokens", RAISED),
        ("Projects", "projects · project_members · settings", PALE),
        ("Data", "data_sources · files · datasets · dataset_versions · records · quality_issues · jobs", PALE),
        ("Ontology", "entity_types · relationship_types", PALE),
        ("Entities & graph", "entities · entity_sources · relationships · match_candidates · merge_history · graph_snapshots", PALE),
        ("Documents", "documents · document_chunks · embeddings", PALE),
        ("Time & space", "events · geo_features", PALE),
        ("Search", "search_index (FTS5 / tsvector) · saved_queries · query_history", PALE),
        ("Analysis", "analysis_runs (inputs, versions, result SHA-256)", PALE),
        ("Investigations", "investigations · collaborators · items · notes · evidence (+revisions) · findings", PALE),
        ("Workflows & reports", "workflows · workflow_versions · workflow_runs · reports · report_exports", PALE),
        ("Platform", "audit_events (hash chain) · model_registry · backup_manifests · saved views · watches · notifications", RAISED),
    ]
    cols, gap = 3, 10
    bw = (W - gap * (cols - 1)) / cols
    bh = 64
    for i, (t, b, fill) in enumerate(areas):
        r, c = divmod(i, cols)
        x = c * (bw + gap)
        y = 296 - (r + 1) * (bh + 10) + 6
        g.add(Rect(x, y, bw, bh, rx=6, ry=6, fillColor=fill, strokeColor=None))
        text(g, x + 9, y + bh - 15, t, size=9.4, color=ACCENT_DEEP if fill is PALE else INK, font="Body-Bold")
        yy = y + bh - 28
        for ln in wrap(b, "Body", 7.8, bw - 18):
            text(g, x + 9, yy, ln, size=7.8, color=TEXT)
            yy -= 10
    d.add(g)
    return d


def er_flow() -> Drawing:
    d = Drawing(W, 150)
    g = Group()
    steps = [("Blocking", "shared name token or identifier value; blocks > 250 skipped"),
             ("Compare", "only features present on both sides; others ‘not compared’"),
             ("Score", "weighted mean: name .45, identifier .35, attribute .20"),
             ("Band", "strong ≥ .90 + an agreeing identifier and no conflict; else ambiguous ≥ .75"),
             ("Human review", "accept (choose survivor, reason) or reject — audited"),
             ("Merge", "snapshot stored; revert restores attributes, sources, links")]
    n = len(steps)
    gap = 9
    bw = (W - gap * (n - 1)) / n
    for i, (t, b) in enumerate(steps):
        x = i * (bw + gap)
        human = i >= 4
        box(g, x, 40, bw, 100, fill=OK_PALE if human else PALE, stroke=OK if human else colors.HexColor("#B9D3E8"),
            title=t, body=b, title_color=colors.HexColor("#1F6B46") if human else ACCENT_DEEP, body_color=TEXT,
            title_size=9.4, body_size=7.5)
        if i < n - 1:
            arrow(g, x + bw + 1, 90, x + bw + gap - 1, 90, color=ACCENT)
    g.add(Rect(0, 4, 4 * (bw + gap) - gap, 22, rx=4, ry=4, fillColor=RAISED, strokeColor=None))
    text(g, (4 * (bw + gap) - gap) / 2, 12, "deterministic, versioned algorithm  er-1.1", size=8.2, color=INK,
         font="Body-Bold", anchor="middle")
    x0 = 4 * (bw + gap)
    g.add(Rect(x0, 4, W - x0, 22, rx=4, ry=4, fillColor=OK_PALE, strokeColor=None))
    text(g, x0 + (W - x0) / 2, 12, "human decision, never automatic", size=8.2, color=colors.HexColor("#1F6B46"),
         font="Body-Bold", anchor="middle")
    d.add(g)
    return d


def finding_states() -> Drawing:
    d = Drawing(W, 170)
    g = Group()
    bw, bh = 104, 34
    nodes = {
        "draft": (0, 68, PALE, ACCENT_DEEP, "Draft"),
        "review": (126, 68, WARN_PALE, WARN, "Under review"),
        "confirmed": (256, 126, OK_PALE, OK, "Confirmed by reviewer"),
        "disputed": (256, 68, HYPO_PALE, HYPO, "Disputed"),
        "rejected": (256, 10, DANGER_PALE, DANGER, "Rejected"),
        "superseded": (W - bw, 68, RAISED, INK, "Superseded"),
    }
    for k, (x, y, fill, col, label) in nodes.items():
        box(g, x, y, bw, bh, fill=fill, stroke=col, title=label, title_color=col, title_size=9.2, stroke_w=1)
    def mid_r(k):
        x, y = nodes[k][0], nodes[k][1]
        return x + bw, y + bh / 2
    def mid_l(k):
        x, y = nodes[k][0], nodes[k][1]
        return x, y + bh / 2
    arrow(g, *mid_r("draft"), *mid_l("review"), color=MUTED)
    for t in ("confirmed", "disputed", "rejected"):
        x1, y1 = mid_r("review")
        x2, y2 = mid_l(t)
        arrow(g, x1, y1, x2, y2, color=MUTED)
        x1, y1 = mid_r(t)
        x2, y2 = mid_l("superseded")
        arrow(g, x1, y1, x2, y2, color=colors.HexColor("#9AA8B6"), dash=(3, 2))
    text(g, 0, 150, "Guards enforced by the API:", size=8.4, color=INK, font="Body-Bold")
    text(g, 0, 139, "• the author cannot review their own finding", size=8)
    text(g, 0, 128, "• confirmation requires supporting evidence", size=8)
    text(g, 0, 117, "• every transition is kept in the finding history", size=8)
    d.add(g)
    return d


def hash_chain() -> Drawing:
    d = Drawing(W, 150)
    g = Group()
    n = 3
    gap = 22
    cw = 112
    bw = (W - cw - gap * n) / n
    events = [("seq 42", "ingest.commit", "9f3c\u2026a1"), ("seq 43", "entity.merge", "4be0\u2026d7"),
              ("seq 44", "report.export", "c27a\u202619")]
    for i, (s_, a, ph) in enumerate(events):
        x = i * (bw + gap)
        g.add(Rect(x, 52, bw, 90, rx=5, ry=5, fillColor=WHITE, strokeColor=ACCENT, strokeWidth=0.9))
        g.add(Rect(x, 118, bw, 24, rx=5, ry=5, fillColor=PALE, strokeColor=None))
        text(g, x + 8, 126, s_, size=9, color=ACCENT_DEEP, font="Body-Bold")
        text(g, x + bw - 8, 126, a, size=7.6, color=MUTED, anchor="end", font="Mono")
        text(g, x + 8, 102, "prev_hash", size=7.4, color=MUTED, font="Body-Bold")
        text(g, x + 8, 91, ph, size=7.8, color=TEXT, font="Mono")
        text(g, x + 8, 74, "hash = SHA-256(prev_hash", size=7.6, color=MUTED)
        text(g, x + 8, 63, "+ canonical JSON of event)", size=7.6, color=MUTED)
        if i < n - 1:
            arrow(g, x + bw + 2, 96, x + bw + gap - 2, 96, color=ACCENT)
    xc = W - cw
    box(g, xc, 52, cw, 90, fill=OK_PALE, stroke=OK, title="Signed checkpoint",
        body="HMAC of the chain head, written to audit-checkpoints.jsonl (key kept in the workspace, 0600)",
        title_color=OK, body_color=TEXT, title_size=8.8, body_size=7.3)
    arrow(g, (n - 1) * (bw + gap) + bw + 2, 96, xc - 2, 96, color=OK, dash=(3, 2))
    g.add(Rect(0, 8, W, 32, rx=5, ry=5, fillColor=RAISED, strokeColor=None))
    text(g, 10, 26, "Database triggers reject UPDATE and DELETE on audit_events.", size=8.2, color=INK, font="Body-Bold")
    text(g, 10, 15, "Verification recomputes every hash and reports the first broken sequence number.", size=8, color=TEXT)
    d.add(g)
    return d


def sql_layers() -> Drawing:
    d = Drawing(W, 150)
    g = Group()
    layers = [
        (PALE, ACCENT_DEEP, "1  Static validation", "One statement; must start with SELECT or WITH; deny-list of ATTACH, COPY, PRAGMA, SET, INSTALL, read_csv / read_parquet, glob, http, getenv and similar"),
        (OK_PALE, colors.HexColor("#1F6B46"), "2  Permitted tables only", "Only datasets the caller may read are loaded from Parquet via Arrow; sensitive columns dropped without sensitive.read"),
        (WARN_PALE, WARN, "3  Locked engine", "Fresh in-memory DuckDB; enable_external_access = false and lock_configuration = true set before the user query runs"),
        (DANGER_PALE, DANGER, "4  Resource limits", "2 threads, 1 GB memory, row limit (default 5,000) and a wall-clock interrupt (default 20 s)"),
    ]
    pill = 50
    gap = 10
    n = len(layers)
    bw = (W - 2 * pill - gap * (n + 1)) / n
    box(g, 0, 70, pill, 30, fill=INK, stroke=INK, title="Query", title_color=WHITE, title_size=8.6)
    for i, (fill, col, t, b) in enumerate(layers):
        x = pill + gap + i * (bw + gap)
        box(g, x, 30, bw, 110, fill=fill, stroke=col, title=t, body=b, title_color=col, body_color=TEXT, title_size=9,
            body_size=7.6, stroke_w=0.9)
        arrow(g, x - gap + 1, 85, x - 1, 85, color=MUTED)
    xr = W - pill
    arrow(g, xr - gap + 1, 85, xr - 1, 85, color=MUTED)
    box(g, xr, 70, pill, 30, fill=OK_PALE, stroke=OK, title="Rows", title_color=OK, title_size=8.6)
    g.add(Rect(0, 2, W, 20, rx=4, ry=4, fillColor=RAISED, strokeColor=None))
    text(g, W / 2, 9, "Executed as  SELECT * FROM (user query) LIMIT n+1  \u2014  each layer would stop file or network access on its own",
         size=7.8, color=INK, font="Body-Bold", anchor="middle")
    d.add(g)
    return d


def reproducibility() -> Drawing:
    d = Drawing(W, 132)
    g = Group()
    inputs = ["dataset version ids", "content SHA-256 of each version", "parameters", "algorithm + software version"]
    g.add(Rect(0, 8, 150, 118, rx=6, ry=6, fillColor=PALE, strokeColor=None))
    text(g, 10, 110, "Recorded inputs", size=9, color=ACCENT_DEEP, font="Body-Bold")
    for i, s in enumerate(inputs):
        text(g, 12, 92 - i * 18, "• " + s, size=8, color=TEXT)
    box(g, 175, 52, 92, 40, fill=ACCENT, stroke=ACCENT, title="Run analysis", title_color=WHITE, title_size=9)
    arrow(g, 151, 72, 174, 72, color=ACCENT)
    box(g, 292, 52, 92, 40, fill=WHITE, stroke=ACCENT, title="Result", body="canonical JSON", title_color=ACCENT_DEEP)
    arrow(g, 268, 72, 291, 72, color=ACCENT)
    box(g, W - 76, 52, 76, 40, fill=INK, stroke=INK, title="SHA-256", body="stored with run", title_color=WHITE,
        body_color=colors.HexColor("#C9D6E2"))
    arrow(g, 385, 72, W - 77, 72, color=ACCENT)
    # reproduce loop
    box(g, 175, 8, W - 175, 30, fill=OK_PALE, stroke=OK, title="Reproduce: re-execute on the recorded versions and compare hashes → identical ✓ or changed inputs reported",
        title_color=colors.HexColor("#1F6B46"), title_size=8.2)
    arrow(g, W - 38, 51, W - 38, 39, color=OK)
    d.add(g)
    return d


def ask_data() -> Drawing:
    d = Drawing(W, 68)
    g = Group()
    steps = [("You ask", "a question in plain language", PALE, ACCENT_DEEP),
             ("Model drafts SQL", "validated by the same read-only checker", HYPO_PALE, HYPO),
             ("You review & run", "explicit click; sandboxed DuckDB", OK_PALE, colors.HexColor("#1F6B46")),
             ("Deterministic table", "computed by Atlas, not the model", PALE, ACCENT_DEEP),
             ("Model describes", "labelled as model output", HYPO_PALE, HYPO)]
    n = len(steps)
    gap = 12
    bw = (W - gap * (n - 1)) / n
    for i, (t, b, fill, col) in enumerate(steps):
        x = i * (bw + gap)
        box(g, x, 4, bw, 62, fill=fill, stroke=col, title=t, body=b, title_color=col, body_color=TEXT, title_size=9.2)
        if i < n - 1:
            arrow(g, x + bw + 1, 35, x + bw + gap - 1, 35, color=MUTED)
    d.add(g)
    return d


def netguard() -> Drawing:
    d = Drawing(W, 150)
    g = Group()
    g.add(Rect(0, 8, 236, 134, rx=8, ry=8, fillColor=PALE, strokeColor=ACCENT, strokeWidth=0.9))
    text(g, 12, 124, "atlas-api process (ATLAS_OFFLINE_MODE=true)", size=8.8, color=ACCENT_DEEP, font="Body-Bold")
    box(g, 12, 62, 212, 50, fill=WHITE, stroke=LINE, title="Patched socket.connect / connect_ex / getaddrinfo",
        body="every outbound address is checked before the real call", title_size=8.6)
    box(g, 12, 18, 212, 34, fill=INK, stroke=INK, title="Live probe: connect() to TEST-NET-1 must be blocked",
        title_color=WHITE, title_size=8)
    # allowed
    box(g, 300, 96, W - 300, 44, fill=OK_PALE, stroke=OK, title="Allowed", body="loopback · localhost · RFC 1918 / ULA / link-local (LAN DB, local model runtime)",
        title_color=OK, body_color=TEXT, title_size=9)
    box(g, 300, 16, W - 300, 62, fill=DANGER_PALE, stroke=DANGER, title="Blocked → OfflineViolation",
        body="any other IP and DNS lookups of other names; counted, with the last 200 targets shown in the offline report",
        title_color=DANGER, body_color=TEXT, title_size=9)
    arrow(g, 237, 100, 299, 118, color=OK)
    arrow(g, 237, 80, 299, 47, color=DANGER)
    d.add(g)
    return d


def deployment_profiles() -> Drawing:
    d = Drawing(W, 134)
    g = Group()
    profiles = [
        ("Standalone desktop", "127.0.0.1, random port", "SQLite in the user data directory",
         "PyInstaller bundle opens a chromeless Edge/Chrome/Chromium window", PALE, ACCENT_DEEP),
        ("Air-gapped workstation", "127.0.0.1:8000", "SQLite",
         "installed from the offline bundle (wheelhouse + SHA256SUMS)", OK_PALE, colors.HexColor("#1F6B46")),
        ("Private LAN server", "behind a TLS reverse proxy", "PostgreSQL recommended (preview)",
         "ATLAS_ALLOW_LAN + ATLAS_TLS_TERMINATED in production; nginx + systemd examples", WARN_PALE, WARN),
    ]
    gap = 12
    bw = (W - 2 * gap) / 3
    for i, (t, bind, db, note, fill, col) in enumerate(profiles):
        x = i * (bw + gap)
        g.add(Rect(x, 4, bw, 128, rx=7, ry=7, fillColor=fill, strokeColor=None))
        text(g, x + 10, 114, t, size=10, color=col, font="Body-Bold")
        yy = 96
        for lab, val in (("Binding", bind), ("Database", db), ("Notes", note)):
            text(g, x + 10, yy, lab.upper(), size=6.8, color=MUTED, font="Body-Bold")
            yy -= 11
            for ln in wrap(val, "Body", 8.2, bw - 20):
                text(g, x + 10, yy, ln, size=8.2, color=TEXT)
                yy -= 10.5
            yy -= 5
    d.add(g)
    return d


def workflow_example() -> Drawing:
    d = Drawing(W, 120)
    g = Group()
    nodes = [("Dataset input", "transactions v3", 0, 64), ("Filter rows", "amount > 10 000", 1, 64),
             ("Join tables", "← organizations", 2, 64), ("Statistics", "outliers(amount)", 3, 100),
             ("Save as dataset", "side effect · confirm", 3, 28)]
    bw, bh = 98, 40
    gapx = (W - 4 * bw) / 3
    pos = {}
    for t, b, col, y in nodes:
        x = col * (bw + gapx)
        se = "Save" in t
        box(g, x, y - bh / 2, bw, bh, fill=WARN_PALE if se else PALE, stroke=WARN if se else colors.HexColor("#B9D3E8"),
            title=t, body=b, title_color=WARN if se else ACCENT_DEEP, body_color=TEXT, title_size=8.8, body_size=7.4)
        pos[t] = (x, y)
    def link(a, b):
        xa, ya = pos[a]
        xb, yb = pos[b]
        arrow(g, xa + bw + 1, ya, xb - 1, yb, color=ACCENT)
    link("Dataset input", "Filter rows")
    link("Filter rows", "Join tables")
    link("Join tables", "Statistics")
    link("Join tables", "Save as dataset")
    text(g, 0, 4, "Typed ports (table → table / analysis / dataset) are validated; cycles and missing inputs are rejected before saving.",
         size=7.8, color=MUTED)
    d.add(g)
    return d


def cover_network(width: float, height: float, seed: int = 7) -> Group:
    """Decorative constellation for the cover, echoing the logo."""
    rnd = random.Random(seed)
    g = Group()
    pts = []
    for _ in range(46):
        pts.append((rnd.uniform(0, width), rnd.uniform(0, height)))
    for i, (x, y) in enumerate(pts):
        near = sorted(range(len(pts)), key=lambda j: (pts[j][0] - x) ** 2 + (pts[j][1] - y) ** 2)[1:3]
        for j in near:
            g.add(Line(x, y, pts[j][0], pts[j][1], strokeColor=colors.HexColor("#2E5F86"), strokeWidth=0.6))
    for x, y in pts:
        r = rnd.choice([1.6, 2.2, 3.0])
        g.add(Circle(x, y, r, fillColor=colors.HexColor("#4FA3D9") if r > 2.5 else colors.HexColor("#3B7FB0"),
                     strokeColor=None))
    return g
