"""Build docs/overview/Project-Atlas-Technical-Overview.pdf.

Run from anywhere:  python3 docs/overview/source/build_pdf.py
Facts are taken from the repository (README, docs/, backend and frontend sources, test and benchmark results).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from reportlab.lib.enums import TA_RIGHT  # noqa: E402
from reportlab.platypus import CondPageBreak, Flowable, KeepTogether, NextPageTemplate, PageBreak, Spacer  # noqa: E402

import atlas_diagrams as D  # noqa: E402
from atlas_pdf_kit import *  # noqa: E402,F403
from atlas_pdf_kit import (  # noqa: E402
    ACCENT, ACCENT_2, CONTENT_W, INK, MUTED, PAGE_H, PAGE_W, WHITE, AtlasDoc, C, CHECK, ChapterHeading, DOT, P, bullets,
    callout, code_block, figure, h2, h3, hbar_chart, logo, screenshot, screenshot_pair, stat_tiles, table, toc,
)

REPO = HERE.parents[2]
SHOTS = REPO / "docs" / "screenshots"
OUT = HERE.parent / "Project-Atlas-Technical-Overview.pdf"


def shot(name: str) -> Path:
    return SHOTS / name


# ================================================================================================ cover
class Cover(Flowable):
    def wrap(self, aw, ah):
        return PAGE_W, PAGE_H - 1

    def draw(self):
        from reportlab.graphics import renderPDF
        from reportlab.graphics.shapes import Drawing

        c = self.canv
        c.setFillColor(INK)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        net = Drawing(PAGE_W, 260)
        net.add(D.cover_network(PAGE_W * 0.56, 220, seed=11))
        c.saveState()
        c.translate(PAGE_W * 0.40, 150)
        renderPDF.draw(net, c, 0, 0)
        c.restoreState()
        lg = Drawing(72, 72)
        lg.add(logo(72))
        renderPDF.draw(lg, c, 54, PAGE_H - 140)
        c.setFillColor(colors_hex("#9AD0F2"))
        c.setFont("Body-Bold", 11)
        c.drawString(140, PAGE_H - 96, "  ".join("ATLAS"))
        c.setFont("Body", 8.5)
        c.setFillColor(colors_hex("#8A97A6"))
        c.drawString(140, PAGE_H - 110, " ".join("NAVIGATE THE COMPLEXITY OF DATA"))
        c.setFillColor(colors_hex("#4FA3D9"))
        c.setFont("Body-Bold", 12)
        c.drawString(54, PAGE_H - 250, " ".join("PROJECT ATLAS"))
        c.setFillColor(WHITE)
        c.setFont("Body-Bold", 40)
        c.drawString(54, PAGE_H - 298, "Technical Overview")
        c.drawString(54, PAGE_H - 342, "and System Guide")
        c.setFont("Body", 15)
        c.setFillColor(colors_hex("#C9D6E2"))
        c.drawString(54, PAGE_H - 380, "Offline Intelligence and Data Operations Platform")
        c.setFont("Body", 10.5)
        c.setFillColor(colors_hex("#8A97A6"))
        y = PAGE_H - 418
        for ln in ("Architecture, features, data model, security, operations, testing and",
                   "project status — everything in the repository, explained in one place."):
            c.drawString(54, y, ln)
            y -= 15
        # footer block
        c.setStrokeColor(colors_hex("#2C3540"))
        c.setLineWidth(0.8)
        c.line(54, 118, PAGE_W - 54, 118)
        meta = [("VERSION", "0.2.0"), ("RELEASED", "28 October 2026"), ("DOCUMENT DATE", "November 2026"),
                ("LICENSE", "MIT")]
        x = 54
        for k, v in meta:
            c.setFont("Body-Bold", 7.5)
            c.setFillColor(colors_hex("#8A97A6"))
            c.drawString(x, 96, " ".join(k))
            c.setFont("Body-Bold", 12)
            c.setFillColor(WHITE)
            c.drawString(x, 78, v)
            x += (PAGE_W - 108) / 4
        c.setFont("Body", 8)
        c.setFillColor(colors_hex("#6B7886"))
        c.drawString(54, 48, "All sample data referenced in this document is synthetic. Figures were measured by the project's own "
                             "test, acceptance and benchmark runs.")


def colors_hex(h):
    from reportlab.lib import colors as _c

    return _c.HexColor(h)


# ================================================================================================ story helpers
story: list = []


def add(f):
    if isinstance(f, list):
        story.extend(f)
    else:
        story.append(f)


def chapter(num: str, title: str, lead: str, kicker: str = ""):
    add(PageBreak())
    add(ChapterHeading(num, title, kicker))
    add(P(lead, "lead"))


def para(t: str):
    add(P(t))


def addl(items):
    story.extend(items)


# ================================================================================================ front matter
add(NextPageTemplate("content"))
add(Cover())
add(PageBreak())
add(ChapterHeading("", "Contents", "About this document", in_toc=False))
addl([
    P("This guide explains <b>Project Atlas</b> end to end — why it exists, how it is built, what every module does, "
      "how it is secured and operated offline, how it was tested, and what is complete, partial or deferred. Facts come "
      "directly from the repository: source code, documentation, sample-data ground truth and the recorded test, "
      "acceptance and benchmark results for release 0.2.0.", "small", textColor=MUTED, spaceAfter=6),
    toc(),
    Spacer(1, 6),
    Paragraph("Suggested reading paths", STY["h3"]),
    table([
        ["Reader", "Start with", "Then"],
        ["Decision makers", "1 Executive Summary, 2 Vision", "3 Capabilities, 20 Status and Roadmap"],
        ["Engineers", "4 Architecture, 5 Codebase, 6 Data Model", "7–13 feature chapters, 18 API, 19 Testing"],
        ["Security reviewers", "14 Security Model, 15 Audit and Offline", "12 Local AI, 20 Limitations"],
        ["Administrators", "16 Deployment and Operations", "15 Backup and Restore, 19 Performance"],
        ["Analysts", "17 Guided Tour", "7–13 feature chapters"],
    ], [0.22, 0.38, 0.40], bold_first=True, font_size=8.4, pad=3),
])

# ================================================================================================ 1 executive summary
chapter("01", "Executive Summary",
        "Project Atlas is an offline-first, local-control platform for turning authorized datasets and documents into "
        "evidence-backed, auditable analysis — with no cloud dependency at install time or at run time.")
para("Analysts in compliance, auditing, research and organizational review routinely have to combine spreadsheets, "
     "database extracts, PDFs and e-mails, work out which records describe the same person or organization, explore how "
     "those entities are connected, and then defend their conclusions to someone else. Cloud tools are often ruled out "
     "by data sensitivity or air-gapped networks, and ad-hoc local tools lose provenance. Atlas covers the entire chain "
     "— import, quality control, entity resolution, graph exploration, search, timelines, maps, analytics, "
     "investigations and reporting — inside a single process that runs on a workstation or a private LAN.")
addl([Spacer(1, 4), stat_tiles([
    ("167", "REST API operations, documented in OpenAPI"),
    ("16", "UI modules in the analytical workstation"),
    ("111", "backend tests passing (plus 11 UI unit tests and an end-to-end run)"),
    ("13", "file formats: 8 tabular, 5 document"),
    ("13", "data-quality checks with plain-language explanations"),
    ("0", "cloud services, telemetry or external fallbacks"),
], cols=3), Spacer(1, 10)])
add(h2("What the platform does"))
addl(bullets([
    "<b>Import and validate</b> CSV, TSV, XLSX, JSON, JSONL, XML, SQLite and Parquet through a controlled "
    "upload → inspect → map → dry run → commit pipeline with 13 quality checks and versioned, hashed datasets.",
    "<b>Resolve entities</b> with a deterministic, explainable matcher (algorithm <i>er-1.1</i>) whose every candidate shows "
    "matching, conflicting and “not compared” fields, followed by human review and reversible merges.",
    "<b>Explore relationships</b> in a knowledge graph where each edge is labelled <i>observed</i>, <i>inferred</i>, "
    "<i>model hypothesis</i> or <i>manual</i>, with centrality, communities, paths and “explain connection”.",
    "<b>Search and read</b> across records, entities, documents, reports and investigations; a grounded document assistant "
    "quotes page-level evidence and declines when there is none.",
    "<b>Analyse reproducibly</b> — descriptive statistics, trends, correlation, outliers, time series and a sandboxed SQL "
    "console; every run is re-executable and verified by hash.",
    "<b>Investigate and report</b> with verbatim evidence, a reviewed findings workflow, typed visual workflows and "
    "PDF/HTML/XLSX/CSV/JSON reports that carry a manifest of exactly what they were built from.",
    "<b>Prove what happened</b> with an append-only, hash-chained audit log, verified (optionally encrypted) backups and an "
    "offline verification report.",
]))
add(h2("What makes it different"))
add(table([
    ["Property", "How Atlas delivers it"],
    ["Offline by design", "No external assets, no telemetry, an in-process outbound network guard, bundled basemap and fonts; verified inside a network namespace with no route to the internet."],
    ["Evidence over assertion", "Original values are kept beside normalized ones; every entity, edge, analysis and report links back to source records and file hashes."],
    ["Explainable automation", "Matching, quality and graph explanations are deterministic and versioned; scores are labelled as similarity, not probability."],
    ["Human in the loop", "Merges, findings, model-suggested relationships and generated SQL all require an explicit human decision."],
    ["Least privilege", "Two-layer RBAC, restricted datasets and sensitive-field redaction enforced by the backend on every route; system administrators do not automatically see project data."],
    ["Tamper evidence", "SHA-256 hash chain over canonical JSON, database triggers that block edits, HMAC-signed checkpoints."],
], [0.24, 0.76], bold_first=True))
add(Spacer(1, 8))
add(callout("Status at a glance (release 0.2.0, 28 October 2026)",
            "All automated suites pass: 111 backend tests, 11 frontend unit tests, a Playwright end-to-end run across all modules "
            "and the 14-step acceptance scenario including a network-isolated phase. Known gaps are stated plainly: PostgreSQL "
            "support is implemented but untested, local-AI features are tested against a mock runtime, Windows/macOS packages "
            "have not been built, and no independent penetration test has been performed (Chapter 20).", "ok"))

# ================================================================================================ 2 vision
chapter("02", "Vision, Principles and Scope",
        "Atlas is built around a small set of principles that show up repeatedly in the code: keep control local, keep "
        "the evidence, explain every automated step, and never let software make a judgement a person should make.")
add(h2("The problem it addresses"))
para("Organizational analysis rarely starts with clean data. A typical review receives a staff list as CSV, a supplier "
     "register in Excel, a payments extract from a database, a handful of audit reports as PDF and a folder of e-mails. "
     "The same person appears as <i>Dr. Amelia Okafor</i> in one file and <i>Amelia Okafor</i> in another; a phone number is "
     "stored in three formats; timestamps arrive in local time without a zone. The analyst must reconcile all of this, "
     "spot what is unusual, and produce a conclusion that will be challenged — often on a machine that may not "
     "connect to the internet.")
para("General-purpose BI tools do not keep row-level provenance or support entity resolution; cloud analytics platforms "
     "are unavailable for sensitive or air-gapped work; scripts and spreadsheets cannot show a reviewer how a conclusion "
     "was reached. Atlas is designed to close that gap with one installable product.")
add(h2("Design principles"))
add(table([
    ["Principle", "What it means in practice", "Where it is enforced"],
    ["Offline-first", "Install from a bundle and run with no network; private-range services only.", f"{C('core/netguard.py')}, {C('core/config.py')}"],
    ["Local control", "One process, local SQLite or a LAN PostgreSQL; data never leaves the host.", "deployment profiles"],
    ["Evidence first", "Keep raw values, hashes and record links at every step.", f"{C('records.raw')}, {C('entity_sources')}"],
    ["Explainability", "Deterministic, versioned algorithms with visible inputs.", f"{C('er-1.1')}, {C('quality-1.0')}"],
    ["Human judgement", "Software proposes; people decide and are recorded.", "review, findings, AI"],
    ["Reproducibility", "Re-run any analysis on recorded inputs and compare hashes.", f"{C('analysis_runs')}"],
    ["Least privilege", "Deny by default; hide existence of other projects (404).", f"{C('security/rbac.py')}"],
    ["Tamper evidence", "Append-only audit with a hash chain and checkpoints.", f"{C('audit/service.py')}"],
    ["Honest status", "Document what is untested or deferred rather than imply it works.", "engineering report"],
], [0.18, 0.5, 0.32], bold_first=True))
add(h2("Product identity"))
add(table([
    ["Item", "Value"],
    ["Product name / short name", "PROJECT ATLAS / Atlas — “Navigate the Complexity of Data.”"],
    ["Python distribution / import package", f"{C('project-atlas')} / {C('project_atlas')} (Python 3.11+)"],
    ["API service", f"{C('atlas-api')} — FastAPI, OpenAPI served at {C('/api/docs')}"],
    ["UI package", f"{C('project-atlas-ui')} — React + TypeScript + Vite"],
    ["Desktop app", "Project Atlas — PyInstaller bundle with a chromeless browser window"],
    ["Command-line tools", f"{C('atlas')} (serve, create-admin, backup, verify-backup, offline-check, migrate), {C('atlas-desktop')}"],
    ["Configuration prefix", f"{C('ATLAS_')} environment variables, overlaid on {C('.env')}"],
    ["License", "MIT; bundled DejaVu fonts and Natural Earth data keep their own licenses"],
], [0.34, 0.66], bold_first=True))
add(h2("Intended use and responsible-use safeguards"))
para("Atlas is intended for authorized research, compliance, auditing and organizational analysis over data the user is "
     "permitted to process. Several safeguards are built into the product rather than left to policy:")
addl(bullets([
    "Outlier results always carry a disclaimer that statistical unusualness is <i>not evidence of wrongdoing</i>.",
    "Connection paths in the graph “show recorded links only; they do not establish intent or wrongdoing”.",
    "Temporal proximity between two entities is described as descriptive, not proof of interaction.",
    "Investigations require an objective and a scope/authorization basis; findings need independent review.",
    "All bundled demonstration data is <b>synthetic</b> (seed 20251027, e-mail domain <i>example.invalid</i>, "
    f"{C('record_origin=SYNTHETIC')} on every row).",
]))
add(h2("Who uses it"))
add(table([
    ["Role", "Typical work in Atlas"],
    ["System Administrator", "Users, projects, backups and restore, settings, local model registry, audit read"],
    ["Security Administrator", "Account security, session revocation, MFA resets, audit read and chain verification"],
    ["Project Administrator", "Membership, access policies, sensitive data, dataset deletion, project archive"],
    ["Data Engineer", "Imports, ontology, restricted datasets, entity resolution, data-writing workflows"],
    ["Analyst", "Analysis, SQL, graph and map annotations, investigations, reports, AI assistants"],
    ["Reviewer", "Match review, finding review, read access"],
    ["Read-Only User", "Browse and search"],
], [0.28, 0.72], bold_first=True))

# ================================================================================================ 3 capabilities
chapter("03", "Capabilities at a Glance",
        "The user interface is an analytical workstation with sixteen modules. Each is backed by real API behaviour, "
        "access control and automated tests.")
add(table([
    ["Module", "Key", "What you do there"],
    ["Atlas Home", "g h", "Project dashboard: counts, events over time, entities by type, most-connected entities, data quality by check, activity feed, watchlist, running jobs"],
    ["Data Catalog", "g c", "Datasets, versions, normalized vs original values, schema completeness, quality issues and explanations, lineage, access and retention policy"],
    ["Ingestion", "g i", "Upload, inspect, map fields, define entities/links/events/map points, dry run, commit as a background job"],
    ["Global Search", "g s", "Boolean, phrase, prefix, field and numeric/date filters across all permitted content; saved searches and history"],
    ["Entity Explorer", "g e", "Entities with attribute provenance, match review, merge history and revert, watchlists"],
    ["Knowledge Graph", "g g", "Neighbourhoods, filters by type and basis, centrality, communities, paths, explain connection, snapshots, exports"],
    ["Timeline", "g t", "Events in a chosen display time zone, gap clustering, relationships in a window, two-entity comparison"],
    ["Geospatial Explorer", "g m", "Offline basemap, layers, heatmap and clustering, radius and distance tools, annotations, spatial joins"],
    ["Analytics", "g a", "Reproducible analyses, run history and reproduction, read-only SQL console, “Ask your data”"],
    ["Documents", "g d", "PDF/DOCX/TXT/MD/EML processing, page view, similar documents, grounded document assistant"],
    ["Investigations", "g v", "Scope, collaborators, linked items, verbatim evidence with revisions, findings and review"],
    ["Workflows", "g w", "Typed visual pipelines: validate, version, preview without side effects, run with confirmation"],
    ["Reports", "g r", "Compose sections, preview, export PDF/HTML/XLSX/CSV/JSON with a manifest"],
    ["Audit Center", "g u", "Filter events, verify the hash chain, write signed checkpoints, export CSV"],
    ["Administration", "g x", "System and offline status, users, members, ontology, backups, retention, AI models"],
    ["Settings", "g ,", "Profile, password, MFA enrolment, sessions, theme and display preferences"],
], [0.2, 0.07, 0.73], bold_first=True, font_size=8.8))
add(h2("Platform capabilities"))
add(table([
    ["Area", "Highlights"],
    ["Identity & access", "Argon2id, one-time setup token, sliding sessions with revocation, rate limiting and lockout, optional TOTP MFA, admin-issued recovery tokens, global and project roles, restricted datasets, sensitive-field redaction"],
    ["Ingestion & catalog", "8 tabular formats, encoding/delimiter/type detection, normalization (time zones, numbers, phones, e-mails, case), dry runs, 13 quality checks, versioned datasets with lineage"],
    ["Ontology & resolution", "10 default entity types and 9 relationship types, editable; explainable matching with evidence; human review; reversible merges"],
    ["Knowledge graph", "Typed, directional edges with assertion basis; neighbourhoods, paths, components, centrality, Louvain communities, snapshots, GraphML/GEXF/JSON export"],
    ["Search & documents", "FTS5 with BM25 and snippets; PDF/DOCX/TXT/MD/EML extraction, language, keywords, entity candidates, duplicates, page-level evidence, grounded assistant"],
    ["Time & space", "UTC event times with source text and zone; offline MapLibre maps; radius, bbox, distance, spatial join, heatmap, clustering"],
    ["Analytics", "Describe, frequency, trend, correlation with confidence intervals, outliers, missing data, time series; reproducible by hash; sandboxed DuckDB SQL"],
    ["Optional local AI", "Grounded answers, SQL drafts, summaries, schema-mapping suggestions, relationship hypotheses, embeddings and semantic search — local endpoint only"],
    ["Case work", "Investigations with evidence revisions; findings state machine; workflows with rollback; reports with manifests"],
    ["Assurance", "Hash-chained audit, checkpoints, encrypted backups with verification and restore, offline verification report"],
    ["Usability (0.2)", "One-click synthetic demo, Ctrl/⌘ K command palette, saved views, watchlists and notifications, explain connection, retention enforcement"],
], [0.22, 0.78], bold_first=True, font_size=8.8))

# ================================================================================================ 4 architecture
chapter("04", "System Architecture",
        "Atlas is a modular monolith: one Python process serves the REST API, runs background jobs and serves the built "
        "React UI. Extra services are introduced only where they are genuinely required.")
addl(figure(D.architecture(), "Component view. Routers translate HTTP into calls on domain services; all services share one "
            "database session factory, job runner, audit log and network guard. The optional model runtime is the only "
            "external process Atlas talks to."))
add(h2("Why a modular monolith"))
para("A single process keeps installation, upgrades and the security boundary simple: one runtime, one set of "
     "dependencies, one place where authorization is enforced, and one audit log. Packages are separated by domain "
     f"({C('ingestion')}, {C('entities')}, {C('graph')}, {C('search')}, {C('analytics')} and so on) and communicate through "
     "plain Python interfaces, so a service can be extracted later if measurements justify it. The engineering report "
     "explicitly defers a dedicated graph database, an external search engine, a vector database and multi-process "
     "workers because the measured workloads do not need them.")
add(h2("Responsibilities of each store"))
add(table([
    ["Store", "Responsibility", "Why this choice"],
    ["SQLite (single user) / PostgreSQL (LAN), SQLAlchemy + Alembic", "System of record: users, sessions, projects, datasets and versions, records (raw + normalized JSON), entities, relationships, documents, investigations, workflows, reports, audit", "Transactions, constraints and migrations; SQLite needs no server and backs up online"],
    [f"{C('search_index')} (FTS5 / tsvector)", "Full-text search over records, entities, documents, reports and investigations with access tags", "Built in, no extra service; BM25 ranking and snippets"],
    ["Parquet per dataset version", "Columnar copy of normalized records for analytics, SQL and workflows", "Fast scans with pandas, DuckDB and Arrow; immutable per version, so reproducible"],
    ["DuckDB (in memory, per query)", "Read-only SQL console", "Isolated: only permitted tables loaded, external access disabled"],
    ["NetworkX (in memory, per request)", "Graph algorithms over relationships", "Adequate to about 10<super>5</super> edges on a workstation"],
    [f"Filesystem ({C('files/')}, {C('exports/')})", "Uploaded originals (never modified), report exports with manifests", "Originals stay byte-identical; SHA-256 recorded"],
], [0.27, 0.43, 0.30], font_size=8.6))
add(h2("Life of a request"))
para("Every API call passes through the same sequence. A middleware adds security headers (CSP, frame denial, no-referrer, "
     f"COOP, permissions policy and {C('Cache-Control: no-store')} for API responses). The router validates the payload with "
     f"Pydantic. Dependencies in {C('api/deps.py')} resolve the bearer token to a session, enforce the per-user rate limit, "
     "load the caller's global role and project membership, and check the permission the route declares. Non-members of a "
     "project receive 404 for every project URL, so the existence of a project is never revealed, and the denial is "
     "audited. The domain service then runs inside a SQLAlchemy session, and any security-relevant action appends an audit "
     "event in its own transaction — denials are recorded even when the request fails. Errors are returned in one "
     f"shape: {C('{&quot;error&quot;: {&quot;code&quot;, &quot;message&quot;, &quot;details&quot;}}')}.")
add(h2("Background jobs"))
para(f"Long operations (imports, entity resolution, document processing, embeddings, workflow runs, demo creation) are "
     f"persisted in the {C('jobs')} table and executed by a small thread pool, or inline when {C('ATLAS_JOBS_INLINE=true')}. "
     "Because SQLite allows one writer, live progress is kept in memory and persisted when the job ends; clients follow it "
     f"over server-sent events at {C('/api/jobs/{id}/events')} or by polling. Jobs support cancellation and retry, and jobs "
     "interrupted by a restart are marked failed and retryable. Imports are atomic, so a retry always starts cleanly.")
add(h2("Deployment profiles"))
para("The same code serves three profiles. Startup validation refuses unsafe combinations: a non-loopback binding without "
     "LAN opt-in, a LAN production deployment without TLS, a non-local AI endpoint in offline mode, or telemetry.")
addl(figure(D.deployment_profiles(), "The three supported deployment profiles."))
add(h2("Technology stack"))
add(table([
    ["Layer", "Components (minimum versions from the manifests)"],
    ["Web/API", "FastAPI 0.115, uvicorn 0.30, Pydantic 2.7, python-multipart"],
    ["Persistence", "SQLAlchemy 2.0, Alembic 1.13, SQLite FTS5; psycopg 3 for the optional PostgreSQL profile"],
    ["Data", "pandas 2.2, PyArrow 16, DuckDB 1.0, openpyxl 3.1, tzdata"],
    ["Graph & matching", "NetworkX 3.3, RapidFuzz 3.9"],
    ["Documents & reports", "pypdf 4.2, python-docx 1.1, ReportLab 4.2 with bundled DejaVu fonts"],
    ["Security", "argon2-cffi 23.1, cryptography 42 (AES-256-GCM, scrypt), httpx 0.27 for the local model runtime"],
    ["Frontend", "React 18.3, TypeScript 5.6, Vite 5.4, Tailwind CSS 3.4, React Router 6.28, TanStack Query 5.59, Zustand 5"],
    ["Visualization", "ECharts 5.5, Cytoscape.js 3.30, MapLibre GL 4.7 with a bundled GeoJSON basemap, React Flow (@xyflow/react 12)"],
    ["Testing", "pytest 8, Vitest 2.1 with Testing Library and jsdom, Playwright (Chromium) end-to-end"],
    ["Packaging", "setuptools wheel with the UI bundled, offline wheelhouse bundle, PyInstaller desktop app"],
], [0.2, 0.8], bold_first=True, font_size=8.8))
add(h2("Desktop shell decision"))
para("Tauri requires WebKitGTK/WebView2 toolchains and Electron adds roughly 150 MB and a second runtime. The shipped "
     "desktop shell is therefore a PyInstaller bundle (Python, all dependencies and the UI) that starts atlas-api on a random "
     "loopback port with offline mode on and opens a chromeless Edge, Chrome or Chromium window (falling back to the default "
     "browser). This keeps one runtime and one security boundary; a native wrapper remains a future option.")

# ================================================================================================ 5 codebase
chapter("05", "Codebase Tour",
        "The repository holds a Python backend, a React frontend, packaging and deployment assets, scripts, synthetic "
        "sample data and documentation — about 21,000 lines of first-party code and tests.")
add(code_block("""
project-atlas/
├── backend/project_atlas/  api, core, security, database (+ migrations), ingestion,
│                           ontology, entities, graph, search, documents, temporal,
│                           geospatial, analytics, ai, workflows, reporting, audit,
│                           backup, demo, cli, desktop
├── backend/tests/          pytest suite (11 modules, 111 tests)
├── frontend/               React UI: src/app, components, features/*, services, types
├── desktop/                PyInstaller spec, launcher, icons
├── deployment/             offline installers, nginx and systemd examples
├── scripts/                sample data, acceptance scenario, benchmark, builds
├── sample-data/            SYNTHETIC demo data + expected_results.json
└── docs/                   architecture, install, offline, security, data model,
                            user guide, backup, API, release notes, engineering report
"""))
add(Spacer(1, 6))
addl(figure(hbar_chart([
    ("api (14 routers)", 3745), ("database + migrations", 1944), ("ingestion", 1305), ("core", 641),
    ("top-level (cli, desktop, retention…)", 622), ("reporting", 579), ("workflows", 578), ("documents", 475),
    ("entities", 418), ("demo generator", 385), ("backup", 353), ("ai", 346), ("analytics", 344), ("search", 254),
    ("graph", 243), ("security", 202), ("geospatial", 187), ("audit", 159), ("temporal", 134), ("ontology", 109),
], label_w=170, bar_h=9.5, gap=4), "Backend size by package (lines of Python, total ≈ 13,000). The API layer is the "
    "largest because each router carries its own validation, permission checks and response shaping."))
add(h2("Backend packages"))
add(table([
    ["Package", "Responsibility", "Notable files"],
    ["api", "HTTP routers, request models, dependencies (auth, permission, project scoping)", f"{C('deps.py')}, {C('entities.py')}, {C('data.py')}"],
    ["core", "Settings and validation, application context, job runner, network guard, errors", f"{C('config.py')}, {C('jobs.py')}, {C('netguard.py')}"],
    ["security", "Argon2id passwords, TOTP, RBAC tables, rate limiting", f"{C('rbac.py')}, {C('passwords.py')}"],
    ["database", "ORM models (≈ 50 tables) and Alembic migrations 0001–0004", f"{C('models.py')}, {C('migrations/')}"],
    ["ingestion", "Parsers, normalization, quality checks, import pipeline", f"{C('parsers.py')}, {C('quality.py')}"],
    ["ontology / entities", "Type definitions; matching algorithm, review, merge and revert", f"{C('matching.py')}, {C('service.py')}"],
    ["graph", "Neighbourhoods, algorithms (own PageRank), exports", f"{C('graph/service.py')}"],
    ["search / documents", "Query parser and FTS; extraction, language, keywords, chunks, assistant", f"{C('text.py')}"],
    ["temporal / geospatial", "Event queries, clustering, comparison; geometry, radius, joins", f"{C('service.py')}"],
    ["analytics", "Analysis kinds, run recording and reproduction, SQL sandbox", f"{C('sql.py')}"],
    ["ai", "Local model client, registry health, grounded generation, embeddings", f"{C('ai/service.py')}"],
    ["workflows / reporting", "Node catalog and executor; report sections and five renderers", f"{C('engine.py')}"],
    ["audit / backup", "Hash-chained log and checkpoints; archive, verify, restore, scheduler", f"{C('backup/service.py')}"],
    ["demo", "Deterministic synthetic Northwind Harbor generator and loader", f"{C('generator.py')}"],
], [0.19, 0.55, 0.26], bold_first=True, font_size=8.6))
add(h2("Frontend structure"))
para(f"The UI (≈ 4,400 lines of TypeScript) is organized by feature. {C('src/app')} holds the shell ({C('Layout.tsx')} with "
     f"navigation, top bar, tabs and keyboard shortcuts), routing and the Zustand store for UI state (theme, tabs, panel "
     f"sizes, recent projects). {C('src/services/api.ts')} wraps fetch with the bearer token kept in {C('sessionStorage')}; "
     f"server state is cached with TanStack Query. {C('src/components')} contains the shared component layer (tables, "
     f"charts, dialogs and toasts, the command palette) and {C('src/features/*')} holds one folder per module. Light and "
     "dark themes use CSS variables; the build is served by atlas-api from the same origin under a strict CSP.")
add(h2("Scripts and tooling"))
add(table([
    ["Script", "Purpose"],
    [C("scripts/generate_sample_data.py"), "Regenerates the synthetic dataset deterministically (seed 20251027)"],
    [C("scripts/acceptance_scenario.py"), "14-step release scenario, including a phase inside a network namespace with loopback only"],
    [C("scripts/benchmark.py"), "Performance measurements at configurable scale (100,000 rows / 5,000 people in the report)"],
    [C("scripts/build_release.sh"), "Offline bundle: project wheel with UI, dependency wheelhouse, installers, SHA256SUMS"],
    [C("scripts/build_desktop.sh"), "PyInstaller desktop application for the current OS"],
    [C("scripts/generate_api_docs.py"), "Regenerates docs/api.md and openapi.json from the running application"],
], [0.38, 0.62], font_size=8.8))

# ================================================================================================ 6 data model
chapter("06", "Data Model and Provenance",
        "The schema is the system of record for everything Atlas knows, including how it came to know it. Provenance is "
        "not a feature bolted on top; it is part of the primary keys and foreign keys.")
addl(figure(D.data_model_map(), "Functional areas of the schema (source of truth: backend/project_atlas/database/models.py)."))
add(h2("Conventions"))
addl(bullets([
    f"Primary keys are stable prefixed UUIDs — {C('prj_…')}, {C('dst_…')}, {C('rec_…')}, {C('ent_…')}, "
    f"{C('mrg_…')} — so an identifier tells you what it refers to.",
    "The audit log uses an integer sequence instead, so the hash chain has a total order.",
    "JSON columns hold flexible payloads: raw and normalized records, entity attributes with per-value provenance, match "
    "evidence, workflow definitions, report manifests.",
    "Indexes cover the filters that matter: foreign keys, (project, entity type), (project, event time), "
    "(dataset version, row index), identity keys and audit actions.",
    "Alembic migrations are applied automatically at startup and restores migrate older backups forward: "
    "0001 initial schema, 0002 search index and audit append-only triggers, 0003 indexed FTS rowid map (performance), "
    "0004 saved views, watches and notifications.",
]))
add(h2("Key tables"))
add(table([
    ["Table", "What it stores"],
    [C("datasets / dataset_versions"), "Name, owner, access policy, retention policy; immutable versions with schema, import mapping, record count, quality summary, ingestion report, content SHA-256, origin (import or workflow) and parent version"],
    [C("records"), "Raw source values and normalized values as separate JSON, row index and row hash"],
    [C("entities"), f"Type, display name, deterministic {C('identity_key')}, attributes as {C('{field: [{value, normalized, record_id, dataset_version_id}]}')}, status active/merged"],
    [C("relationships"), "Source and target, type, assertion (observed / inferred / model_suggested / manual), status (active / unverified / rejected), confidence (null unless measured), evidence, valid_from/to"],
    [C("match_candidates / merge_history"), "Scored pairs with evidence and review status; merge snapshots for exact reversal"],
    [C("analysis_runs"), "Kind, parameters, inputs (version ids and hashes, or a graph-state hash), algorithm and software version, result and result SHA-256"],
    [C("evidence / findings"), "Verbatim excerpts with location and revision history; findings with a status state machine and supporting/contradicting links"],
], [0.25, 0.75], font_size=8.6))
add(h2("Provenance and lineage"))
para("Every derived object can be traced back to bytes on disk: versions record the file hash and mapping, records their "
     "row hash, attributes their source record, relationships their evidence, analyses their input hashes, and report "
     "manifests everything a report was built from.")
addl(figure(D.lineage(), "The provenance chain from source file to report. Workflow-materialized versions also record their "
            "parent version and workflow run."))
add(h2("Deletion and retention policy"))
addl(bullets([
    f"Dataset contents (records, versions, quality issues, derived events, observed relationships, search entries) are "
    f"deleted only by <i>Delete dataset</i> ({C('dataset.delete')} plus typing the name); entities still supported elsewhere remain.",
    "Project deletion cascades and is limited to system administrators who administer the project (typed confirmation). "
    "Merges are never destructive, audit events are never changed, and evidence survives document deletion.",
    f"Retention policies ({C('indefinite')}, {C('until_case_closed')}, {C('1y')}, {C('3y')}, {C('7y')}) are enforced from "
    "0.2: superseded versions past retention are purged (tombstones keep lineage); current versions are never auto-deleted.",
]))

# ================================================================================================ 7 ingestion
chapter("07", "Ingestion and Data Quality",
        "Data enters Atlas through one controlled pipeline. Nothing is written until the user has seen a dry run over the "
        "whole file, and the commit is all-or-nothing.")
addl(figure(D.ingestion_pipeline(), "The import pipeline and what a commit writes."))
add(h2("Supported formats"))
add(table([
    ["Format", "Handling"],
    ["CSV / TSV", "Encoding detection (UTF-8, cp1252, latin-1 with mojibake detection), delimiter sniffing, duplicate header renaming, extra-column detection"],
    ["XLSX", "Sheet selection via openpyxl; ZIP magic-byte check"],
    ["JSON / JSONL", "Record path selection and flattening of nested objects into dotted columns"],
    ["XML", "Record element selection; DTD and ENTITY declarations rejected to prevent entity-expansion attacks"],
    ["SQLite", f"Opened read-only ({C('mode=ro')}); table names validated against the catalog"],
    ["Parquet", "Magic-byte check; read through PyArrow"],
    ["PDF, DOCX, TXT, Markdown, EML", "Processed as documents rather than tabular data (Chapter 10)"],
], [0.24, 0.76], bold_first=True, font_size=8.8))
add(h2("Inspection, mapping and normalization"))
para("Inspection reports the detected format, encoding, delimiter, inferred column types and a preview. The mapping step "
     "turns source columns into typed target fields. Supported types are string, identifier, integer, float (with unit "
     "suffix detection), boolean, date, datetime (with a source time zone and optional format), e-mail, phone, latitude and "
     "longitude. Each field can be marked <i>required</i> or <i>sensitive</i>, given a case rule or a validation pattern, and "
     "configurable null tokens are recognized. Atlas suggests a mapping automatically, and with a local model can propose "
     "names, types and sensitivity, which are validated before being applied.")
para("Crucially, the <b>original value is stored separately from the normalized value</b>. The catalog lets anyone toggle "
     "between the two, so a reviewer can always see exactly what the source said. Datetimes are converted to UTC while the "
     "original text and zone are kept; daylight-saving transitions are handled through the IANA database.")
add(h2("Deriving entities, links, events and map points"))
para("The same mapping can declare that each row produces entities (for example a <i>Person</i> keyed by "
     f"{C('person_id')} and an <i>Organization</i> keyed by {C('employer_id')}), relationships between them (<i>works for</i>, "
     "<i>transacted with</i> valid from an event time), timeline events and map points. Rows with invalid coordinates "
     "produce no map point — Atlas never invents coordinates. Event titles use simple field substitution only, never "
     "format-string attribute access.")
add(h2("The 13 quality checks"))
add(table([
    ["Check", "Severity", "What it detects"],
    [C("parse_error"), "error", "Row could not be parsed"],
    [C("extra_columns"), "warning", "Row has more values than header columns"],
    [C("encoding"), "warning", "Replacement characters or mojibake such as “Ã©”"],
    [C("invalid_format"), "error", "Value does not match its declared type or pattern (e.g. a malformed e-mail)"],
    [C("timestamp_error"), "error / warning", "Unparseable date or time, a timestamp in the future, or before a minimum year"],
    [C("coordinate_error"), "error / warning", "Latitude/longitude out of range, (0, 0) “null island”, or only one of the pair"],
    [C("unexpected_type"), "error", "Numeric or boolean field holds text"],
    [C("missing_required"), "error", "A required field is empty"],
    [C("duplicate_row"), "warning", "Exact duplicate of an earlier row (by row hash)"],
    [C("duplicate_key"), "warning", "Unique key value already used by another row"],
    [C("referential_integrity"), "error", "Value not found in a referenced dataset (e.g. an unknown organization id)"],
    [C("inconsistent_units"), "warning", "Mixed unit suffixes within one numeric column"],
    [C("schema_drift"), "warning", "Fields added, removed or changed type compared with the previous version"],
], [0.25, 0.15, 0.60], font_size=8.6))
para("Each issue records the row, field, check, severity, message and the offending value (capped at 500 issues per check "
     "for large files). The summary includes per-field completeness and the number of rows with errors. Every check has a "
     "deterministic plain-language explanation — what it means, likely causes and what to do — shown with or "
     "without AI; a local model can optionally add a prioritized summary.")
addl(screenshot_pair((shot("01-ingest-dryrun.png"), "Dry run over the transactions file: planted timestamp and coordinate errors are reported before anything is written."),
                     (shot("26-quality-explained.png"), "Quality explanations in the Data Catalog: meaning, likely causes and recommended action per check."),
                     "Ingestion dry run and plain-language quality explanations."))
add(h2("Versions, lineage and jobs"))
para("Re-importing a dataset creates a new immutable version; schema drift is reported against the previous one. The catalog "
     "shows lineage from source file hash through mapping to derived entities and relationships, plus the full ingestion "
     "report. Commits run as background jobs in a single transaction with batched inserts; failure or cancellation rolls "
     "everything back and <i>Retry</i> re-runs the import from the start. Data engineers can switch datasets to "
     f"<i>restricted</i>; project administrators can delete them.")

# ================================================================================================ 8 entities
chapter("08", "Ontology and Entity Resolution",
        "Entity resolution decides which records describe the same real-world person or organization. Atlas treats it as "
        "a decision support problem: the algorithm explains itself, and a person makes every merge.")
add(h2("A configurable ontology"))
para("Each project starts with a default ontology that data engineers can extend. Entity types define fields with a type, an "
     "<i>identifier</i> flag (used for deterministic matching), a <i>sensitive</i> flag (drives redaction), a <i>required</i> "
     "flag and an optional pattern; the type carries a schema version. Relationship types declare direction and the "
     "permitted source and target types.")
add(table([
    ["Default entity types", "Identifier fields (sensitive in italics)"],
    ["person", "<i>email</i>, <i>phone</i>, <i>national_id</i> (also sensitive: <i>date_of_birth</i>)"],
    ["organization", "registration_number"],
    ["account", "<i>account_number</i>"],
    ["transaction", "transaction_id (plus amount, currency, event_time)"],
    ["location · event · document · asset · device · project", "document_id, serial_number, device_id, code"],
], [0.42, 0.58], bold_first=True, font_size=8.8))
add(Spacer(1, 4))
add(P("Default relationship types: <i>works for</i> (person → organization), <i>located in</i>, <i>owns</i>, "
      "<i>transacted with</i>, <i>associated with</i> (undirected), <i>participated in</i>, <i>mentioned in</i>, "
      "<i>sent payment</i> and <i>received payment</i>.", "small", textColor=MUTED, spaceAfter=8))
add(h2("Algorithm er-1.1"))
addl(figure(D.er_flow(), "Entity resolution: deterministic candidate generation and scoring, then human decision."))
addl(bullets([
    "<b>Normalization</b> — Unicode decomposition, accents and punctuation removed, lower-cased; honorifics (Dr, Mr, "
    "Prof…) dropped for people and legal suffixes (Ltd, GmbH, Inc…) for organizations.",
    "<b>Blocking</b> — candidate pairs must share a normalized name token or an identifier value; oversized blocks "
    "(more than 250 members) are skipped to bound the work.",
    "<b>Name similarity</b> — the larger of RapidFuzz token-sort ratio and 0.95 × token-set ratio.",
    "<b>Identifiers</b> — exact overlap of normalized values (1 or 0). <b>Other attributes</b> — equality, or fuzzy "
    "similarity counted only when ≥ 0.9.",
    "<b>Missing data is never agreement</b> — a field missing on either side is listed as “not compared”.",
    "<b>Bands</b> — <i>strong</i> needs a score ≥ 0.90, at least one agreeing identifier and no conflicting identifier; "
    "otherwise <i>ambiguous</i> if the score ≥ 0.75. Matches resting on names and descriptive attributes alone can never "
    "be strong. Scores are similarity measures, not calibrated probabilities.",
]))
add(h2("Worked example: the Northwind Harbor demo"))
add(table([
    ["Pair", "Outcome", "Why"],
    ["Dr. Amelia Okafor ↔ Amelia Okafor", "strong", "Same e-mail identifier; honorific removed before name comparison"],
    ["Jon Mercer ↔ Jonathan Mercer", "strong", "Same phone identifier outweighs the shortened first name"],
    ["Lena Fisher ↔ Lena Fischer", "ambiguous", "Similar names only — needs human judgement"],
    ["Rafael Ortiz ↔ Rafael Ortiz (contact)", "not strong", "Phone identifiers conflict, so identical names cannot make it strong"],
    ["Gunnar Thorsen", "no match", "No other record shares a token or identifier"],
], [0.38, 0.14, 0.48], font_size=8.8))
add(Spacer(1, 4))
para("These are exactly the outcomes recorded in <i>sample-data/expected_results.json</i>, and the test suite asserts them "
     "(2 strong, 1 ambiguous, the conflict not strong, no false match, no duplicate candidates on re-run).")
add(h2("Review, merge and revert"))
para("Each candidate card lists the compared features with per-feature similarity and method, the conflicting fields and "
     "the fields not compared. A reviewer chooses which entity survives and records a reason (audited), or rejects the "
     "pair. A merge moves attributes, sources and relationships to the survivor and stores a complete snapshot in "
     f"{C('merge_history')}; <i>Revert</i> restores attributes, sources and relationships exactly, and the UI offers "
     "<i>Undo</i> straight from the confirmation toast. Users can also <b>watch</b> an entity and be notified when a later "
     "import adds source records about it.")
addl(screenshot(shot("02-match-review.png"), "Match review: compared features, similarities, conflicts and not-compared fields, "
                "with merge and reject actions.", width=CONTENT_W * 0.74))

# ================================================================================================ 9 graph
chapter("09", "Knowledge Graph",
        "The graph is where resolved entities and their relationships become explorable. Its defining feature is "
        "honesty about where every edge came from.")
add(h2("Every edge has a basis"))
add(table([
    ["Assertion basis", "Meaning", "Line style", "Default visibility"],
    ["observed", "Stated directly by a source record (e.g. employer_id on a person row)", "solid", "shown"],
    ["inferred", "Deterministic inference from data, e.g. a mapping rule", "dashed", "shown"],
    ["model_suggested", "Hypothesis proposed by a local model from a document; quote verified", "dotted", f"hidden until verified ({C('unverified')})"],
    ["manual", "Created by a user, with the user recorded", "long dash", "shown"],
], [0.17, 0.43, 0.13, 0.27], bold_first=True, font_size=8.8))
add(Spacer(1, 4))
para("Relationships also carry a status (active, unverified, rejected), evidence (record ids and excerpts), optional validity "
     "dates and a confidence that is left <b>null unless it was actually measured</b>. Reviewers verify or reject "
     "hypotheses; verification keeps the original provenance.")
add(h2("Exploration at scale"))
para(f"The overview loads the best-connected nodes first, ranking degrees in SQL instead of materializing the whole graph "
     f"(this change cut the overview from 6.6 s to 0.9 s on 99,767 edges). Users double-click to focus a node, choose a depth, "
     f"filter by entity type, relationship type and basis, and opt in to unverified hypotheses. Node limits are capped by "
     f"{C('ATLAS_GRAPH_NODE_LIMIT')} (default 2,000) and the UI reports “showing N of M nodes”.")
add(table([
    ["Algorithm", "Implementation notes"],
    ["Degree centrality", "From the filtered subgraph"],
    ["PageRank", "Dependency-free power iteration (α = 0.85), verified against NetworkX's reference implementation; removed a SciPy dependency"],
    ["Betweenness centrality", "Exact on small graphs; sampled with k = 500 above 2,000 nodes"],
    ["Communities", "Louvain modularity"],
    ["Connected components", "Weak components over the undirected view"],
    ["Shortest path", "Between two shift-selected nodes"],
], [0.26, 0.74], bold_first=True, font_size=8.8))
add(Spacer(1, 4))
para("Every algorithm run is stored like an analysis, with a hash of the graph state it ran on, so results can be cited and "
     "reproduced. Users can save <b>snapshots</b> (node and edge ids, layout and filters) and export subgraphs as GraphML, "
     "GEXF or JSON for other tools.")
addl(screenshot(shot("07-graph.png"), "Knowledge Graph module: filters by relationship type and basis, algorithm buttons and "
                "the legend encoding basis by line style and entity type by colour.", width=CONTENT_W * 0.92))
add(h2("Explain connection"))
para("Selecting two nodes and choosing <i>Explain connection</i> returns the shortest paths between them with, for every hop, "
     "the relationships involved, their basis and a redacted sample of the source evidence. The answer is framed carefully: "
     "a path shows recorded links only and does not establish intent or wrongdoing.")
addl(screenshot(shot("25-explain-connection.png"), "Explain connection: per-hop relationships, basis and source evidence "
                "between two selected entities.", width=CONTENT_W * 0.92))

# ================================================================================================ 10 search & documents
chapter("10", "Search and Document Intelligence",
        "Search reaches everything a user is allowed to see. Document intelligence turns PDFs, Word files and e-mails "
        "into page-level evidence that can be quoted, cited and linked to entities.")
add(h2("Unified full-text search"))
para(f"Records, entities, documents, reports and investigations are indexed into {C('search_index')} — an SQLite FTS5 "
     "virtual table (or a PostgreSQL tsvector table) — with document type, project, parent and an access tag. Results are "
     "ranked with BM25 and returned with snippets. The query language is parsed by Atlas and re-emitted, never passed "
     "through raw, which closes FTS injection.")
add(table([
    ["Syntax", "Example", "Meaning"],
    ["Phrase", C('"Bluefjord Freight"'), "Exact phrase"],
    ["Prefix", C("Okaf*"), "Words starting with Okaf"],
    ["Boolean", C("Mercer AND payment"), "Both terms (also OR, NOT, parentheses)"],
    ["Type filter", C("type:entity Okafor"), "Only entities"],
    ["Field filter", C("amount>50000"), "Numeric and date comparisons on indexed fields"],
    ["Scope", "active project / all my projects", "Global search is limited to projects you are a member of"],
], [0.18, 0.36, 0.46], font_size=8.8))
add(Spacer(1, 4))
para("Restricted datasets are visible only to roles with restricted access, and sensitive fields are excluded from the index "
     "entirely. Searches can be saved; recent queries are kept for 90 days and can be cleared.")
add(h2("Document processing pipeline"))
add(table([
    ["Stage", "What happens"],
    ["Extraction", "PDF via pypdf (per page), DOCX via python-docx (per section), EML (per message part), TXT and Markdown; image-only PDF pages use tesseract + pdftoppm when installed, otherwise the document reports OCR required"],
    ["Language", "Stop-word heuristic for English, Spanish, French, German, Italian, Portuguese and Dutch, with a confidence; others are “undetermined”"],
    ["Classification", "Keyword rules; a label needs at least two cues"],
    ["Keywords", "Top terms per document"],
    ["Entity candidates", "E-mails, phones, dates, money amounts, proper names and gazetteer matches against known entities — always unverified candidates"],
    ["Chunking", "≈ 900-character passages keeping page/section numbers and character offsets"],
    ["Duplicates & similarity", "5-word shingles with Jaccard similarity for near-duplicates; TF-IDF cosine for “similar documents”"],
    ["Injection screening", "Passages resembling embedded instructions are flagged at ingestion and shown to the user"],
], [0.2, 0.8], bold_first=True, font_size=8.6))
add(h2("The grounded document assistant"))
para("The assistant answers questions only from retrieved passages. Without a local model it works extractively: it ranks "
     "passages, quotes them and cites document and page. With a model, passages are wrapped in delimited "
     f"{C('&lt;passage&gt;')} blocks, the system prompt forbids following instructions inside them, and any answer without "
     "valid citations to retrieved passages is withheld. Answers are labelled (for example <i>direct evidence</i>), and when "
     "the corpus holds no evidence the assistant declines instead of guessing.")
addl(screenshot(shot("21-document-assistant.png"), "Document assistant answering “Who approved the large payments?” by "
                "quoting the synthetic harbor audit report, page 2.", width=CONTENT_W * 0.92))
add(callout("Prompt-injection test built into the sample data",
            "<i>synthetic_suspicious_note.txt</i> contains embedded instructions aimed at an AI assistant. Atlas flags the document "
            "at ingestion, marks the passage in answers and does not follow it; the test suite checks both behaviours.", "hypo"))

# ================================================================================================ 11 time space analytics
chapter("11", "Timeline, Maps and Analytics",
        "Atlas answers when, where and how much — and records enough about every analysis that anyone can re-run it "
        "and get the same answer.")
add(h2("Timeline"))
para("Events are stored in UTC together with the source time text and zone, the record's own created time, when it was "
     "ingested and when it was modified — so “when did it happen” is never confused with “when did we "
     "learn about it”. The Timeline displays events in the user's chosen time zone, clusters them by a configurable "
     "gap, lists relationships active in a time window and compares two entities' activity. Temporal proximity is "
     "explicitly described as descriptive, not proof of interaction.")
add(h2("Offline maps and spatial operations"))
para("Maps use MapLibre GL with a bundled Natural Earth 1:110m country layer — no tile, glyph or font URLs are "
     "referenced. Features are stored as GeoJSON with bounding-box columns for fast filtering. Supported operations: layer "
     "toggles, heatmap and grid clustering, time filters, bounding-box queries, radius search and distance measurement "
     "(haversine), GeoJSON layer import, annotations and point-in-polygon spatial joins.")
addl(screenshot(shot("09-geo.png"), "Geospatial Explorer over the offline basemap with synthetic transaction points and district "
                "polygons.", width=CONTENT_W * 0.74))
add(h2("Analysis kinds"))
add(table([
    ["Kind", "Method and output"],
    ["describe", "Count, missing, mean, standard deviation, quantiles and distinct values per field"],
    ["frequency", "Value counts with shares"],
    ["trend", "Counts or sums over time buckets"],
    ["correlation", "Pearson r with 95% confidence intervals via the Fisher z-transform; states that correlation is not causation"],
    ["outliers", "Tukey fences (k = 1.5 by default) ranked by robust z (median/MAD); always carries the not-evidence-of-wrongdoing disclaimer"],
    ["missing", "Missing-value counts and shares per field"],
    ["timeseries", "Resampled series for a numeric field over time"],
], [0.17, 0.83], bold_first=True, font_size=8.8))
add(h2("Reproducibility by design"))
addl(figure(D.reproducibility(), "Each analysis run records its exact inputs and a SHA-256 of the canonical result; reproduction "
            "re-executes and compares."))
para("In the acceptance scenario the outlier analysis on the synthetic transactions flags the two planted payments "
     "(T-5007 and T-5023) and reproduction returns an identical hash. If an input version has changed, reproduction "
     "reports it instead of silently producing a different number.")
addl(screenshot(shot("20-analysis-outliers.png"), "Outlier analysis with method, bounds, ranked results and the disclaimer.",
                width=CONTENT_W * 0.74))
add(h2("The sandboxed SQL console"))
para("Analysts can query current dataset versions with read-only SQL, for example "
     f"{C('select receiver_org_id, count(*), sum(amount) from transactions group by 1')}. Four independent layers make this "
     "safe even if one fails; a test proves that file access is blocked with the validator deliberately bypassed.")
addl(figure(D.sql_layers(), "Defence in depth around the SQL console (analytics/sql.py)."))

# ================================================================================================ 12 AI
chapter("12", "Optional Local AI",
        "Every Atlas feature works without a language model. When one is run locally, Atlas applies strict rules: local "
        "endpoint only, grounded inputs, enforced citations and a human decision on every output.")
add(h2("Rules enforced in code"))
addl(bullets([
    f"AI is used only when {C('ATLAS_AI_ENABLED=true')} and a registered, enabled, healthy model exists; the UI shows AI "
    "features only then and only to roles with <i>ai.use</i>.",
    f"{C('ATLAS_AI_BASE_URL')} must be loopback, private or {C('localhost')} in offline mode (checked at startup and on every "
    "call). There is <b>no fallback to any hosted API</b>.",
    "Outputs are labelled as model output. Generated SQL is validated and never executed automatically; relationship "
    "suggestions are stored as <i>model_suggested / unverified</i> and hidden until a reviewer verifies them.",
]))
add(h2("Assistants"))
add(table([
    ["Assistant", "Where", "Guardrail"],
    ["Grounded Q&amp;A, semantic search", "Documents", "Answers withheld without valid citations; local embeddings, no external vector store"],
    ["Ask your data", "Analytics", "Model drafts SQL → user reviews and runs it → deterministic table → model describes it"],
    ["Schema-mapping suggestions", "Ingestion", "Names, types and sensitivity validated before applying; marked AI"],
    ["Quality prioritization, document summary", "Catalog, Documents", "Labelled model output; deterministic explanations always shown"],
    ["Relationship hypotheses", "Documents", "Quote verification; stored unverified; reviewer verifies or rejects"],
    ["Investigation and report summaries", "Investigations, Reports", "Cite evidence [E#] or confirmed findings [F#]; invalid citations flagged; inserted only explicitly"],
], [0.27, 0.17, 0.56], bold_first=True, font_size=8.8))
addl(figure(D.ask_data(), "“Ask your data” keeps computation deterministic: the model drafts and describes, Atlas "
            "computes, and the user decides."))
add(callout("Testing status",
            "All AI paths are tested against a mock Ollama-compatible runtime — citation enforcement, SQL drafts validated and "
            "never executed (including a model-proposed DROP TABLE), unverified hypotheses, embeddings, 503 when disabled — "
            "but have not yet been exercised against a real model.", "warn"))

# ================================================================================================ 13 investigations workflows reports
chapter("13", "Investigations, Workflows and Reports",
        "The final stages turn exploration into accountable output: evidence that cannot drift from its source, findings "
        "that another person must confirm, repeatable pipelines and reports that carry their own provenance.")
add(h2("Investigations"))
para("An investigation records an objective, a scope or authorization basis and a classification. It is visible only to its "
     "owner, collaborators and project administrators. Datasets, entities and graph snapshots can be linked as items, and "
     "notes capture reasoning. <b>Evidence</b> is captured from records or document passages; excerpts must be verbatim "
     "(the API checks them against the source), carry their location (page or row), classification and provenance, and "
     "every edit creates a revision.")
addl(figure(D.finding_states(), "Findings state machine. A finding links supporting and contradicting evidence and keeps its history."))
add(h2("Workflows"))
para("Workflows are typed, versioned pipelines built visually with React Flow. Each node declares input and output port "
     "types, parameters, whether it has side effects or writes data, and the permission it requires.")
add(table([
    ["Node", "Output", "Notes"],
    ["Dataset input", "table", "A specific dataset version"],
    ["Filter rows · Select columns · Normalize text", "table", "Row predicates, projection, trimming and case"],
    ["Join tables · Remove duplicates", "table", "Inner/left joins on keys; dedupe on chosen keys"],
    ["Quality check", "quality", "Required violations and duplicate rows"],
    ["Statistics · Timeline analysis", "analysis", "Any analysis kind; recorded as a reproducible run"],
    ["Build graph", "graph", "Ephemeral graph from table columns (not persisted)"],
    ["Entity resolution · Document retrieval · Embedding generation", "candidates / passages / embeddings", "Reuse platform services"],
    ["Export CSV · Export report", "artifact", "Side effect: requires confirmation"],
    ["Save as dataset version", "dataset", f"Writes data: requires {C('workflow.write_data')}; lineage-linked to the run"],
], [0.42, 0.2, 0.38], font_size=8.6))
addl(figure(D.workflow_example(), "A typical workflow: filter large transactions, join organization data, then analyse and "
            "materialize."))
para("<i>Validate</i> rejects cycles, unknown nodes, missing inputs and mismatched port types. <i>Save</i> creates a new "
     "version. <i>Preview</i> executes on at most 200 rows per input, skips side-effecting nodes and persists nothing. "
     "<i>Run</i> requires confirmation for side effects, reports node results and logs, and rolls back data writes if any "
     "node fails.")
add(h2("Reports"))
para("Reports are composed from typed sections — summary, methodology, free text, dataset table, analysis, graph "
     "snapshot, timeline, map, findings, evidence register, limitations and appendix — previewed, then exported. Charts "
     "and diagrams are rendered as vector graphics; PDFs embed DejaVu fonts so any Unicode text renders, and long tables "
     "repeat their headers across pages.")
add(table([
    ["Format", "Notes"],
    ["PDF", "ReportLab; vector charts, graph diagrams and scatter plots; page numbers and manifest appendix"],
    ["HTML", "Self-contained; inline SVG charts"],
    ["XLSX", "One sheet per table plus a manifest sheet; formula-injection protection"],
    ["CSV", f"Tables only; values starting with {C('= + - @')} are prefixed with an apostrophe"],
    ["JSON", "Full structured content with the manifest"],
], [0.12, 0.88], bold_first=True, font_size=8.8))
add(Spacer(1, 4))
para("Every export includes a <b>manifest</b> — dataset versions and hashes, analysis parameters, software versions, "
     "timestamps and any redactions applied — and its own SHA-256. In the acceptance run, the bytes downloaded for a PDF "
     "report matched the manifest hash exactly. Users without <i>sensitive.export</i> receive redacted exports, and the "
     "redaction is recorded in the manifest.")

# ================================================================================================ 14 security
chapter("14", "Security Model",
        "Security is enforced in the backend for every request, with defence in depth where input is untrusted. The "
        "threat model is explicit about what Atlas does and does not protect against.")
add(h2("Threat model"))
para("Atlas protects analytical data and evidence on a workstation or private LAN against unauthorized users and roles, "
     "cross-project access, privilege escalation, injection through queries, uploads and imported content (including prompt "
     "injection), accidental external data egress, and undetected tampering with the audit trail. It does <b>not</b> protect "
     "against an attacker with full administrative control of the host.")
add(h2("Authentication"))
add(table([
    ["Control", "Implementation"],
    ["Password hashing", "Argon2id (t = 3, m = 64 MiB, p = 4); automatic rehash on login when parameters change"],
    ["Password policy", "≥ 12 characters, 3 of 4 character classes, must not contain the username, small common-password list"],
    ["Initial administrator", "No default account; one-time random setup token (0600) deleted after use, or atlas create-admin on the host"],
    ["Sessions", "256-bit random bearer tokens, only SHA-256 stored; sliding expiry (default 8 h); revocation per session and on password change, reset or disable"],
    ["Brute force", "10 attempts/min per IP and per username; 15-minute lockout after 5 failures; constant-work verification for unknown users; identical errors; 600 API requests/min per user"],
    ["MFA", "Optional TOTP (RFC 6238, SHA-1, 30 s, ±1 step); administrators can reset a lost authenticator"],
    ["Recovery", "Admin-issued one-time 1-hour reset tokens (stored hashed) delivered out of band; redeeming revokes all sessions"],
], [0.22, 0.78], bold_first=True, font_size=8.7))
add(Spacer(1, 4))
para(f"The UI keeps the token in {C('sessionStorage')} and sends it as an Authorization header — there are no cookies, "
     "so CSRF does not apply. XSS exposure is reduced by a strict CSP, React's escaping and serving untrusted originals "
     "only as attachments.")
add(h2("Authorization: two independent layers"))
para("<b>Global roles</b> govern platform administration: System Administrators manage users, projects, backups, settings "
     "and models; Security Administrators handle account security, session revocation and audit verification. "
     "<b>System administrators do not automatically see project data</b> — data access always comes from project "
     "membership, keeping administration and analysis duties separable. <b>Project roles</b> map to permission sets:")
y, n = CHECK, DOT
add(table([
    ["Permission", "Read-Only", "Reviewer", "Analyst", "Data Eng.", "Proj. Admin"],
    ["Read & search everything permitted", y, y, y, y, y],
    ["Review matches (entity.review)", n, y, n, y, y],
    ["Review findings (finding.review)", n, y, n, n, y],
    ["Run analyses and SQL", n, y, y, y, y],
    ["Investigations, evidence, findings", n, "evidence", y, y, y],
    ["Reports, workflows, local AI (ai.use)", n, n, y, y, y],
    ["Import, ontology, entity resolution", n, n, n, y, y],
    ["Read restricted datasets", n, n, n, y, y],
    ["Workflows that write data", n, n, n, y, y],
    ["Read / export sensitive fields", n, n, n, n, y],
    ["Manage members, delete datasets", n, n, n, n, y],
], [0.36, 0.128, 0.128, 0.128, 0.128, 0.128], font_size=8.6,
    col_align={1: 1, 2: 1, 3: 1, 4: 1, 5: 1}))
add(h2("Resource-level rules"))
add(table([
    ["Resource", "Rule"],
    ["Projects", "Non-members get 404 for every project URL (existence not revealed); attempts audited as denied"],
    ["Datasets", "Restricted datasets visible only with dataset.read_restricted — applied to catalog, records, search, SQL, analytics, timeline, geo, workflows and reports"],
    ["Fields", "Sensitive fields redacted as [restricted] in records, entity attributes, match evidence, quality values, analytics frames and SQL tables; excluded from search; redacted in exports without sensitive.export"],
    ["Investigations", "Owner, collaborators and project admins only; reviewers cannot review their own findings"],
    ["Exports", "report.export; every export and download audited with format, hash and redactions"],
], [0.18, 0.82], bold_first=True, font_size=8.7))
add(h2("Input handling"))
addl(bullets([
    "<b>Uploads</b> — extension allow-list, magic-byte checks (PDF, ZIP-based Office, SQLite, Parquet), NUL-byte rejection "
    "for text, size limit, filename sanitization, random storage ids with 0600 permissions, and every stored path resolved "
    "and checked to stay inside the workspace.",
    "<b>XML</b> DTD/ENTITY declarations rejected; <b>SQLite</b> sources read-only; <b>exports</b> protected against formula "
    "injection; <b>queries</b> parsed or sandboxed (Chapter 11); all database access parameterized through SQLAlchemy.",
    "<b>Prompt injection</b> — imported documents are untrusted: delimited passages, a system prompt forbidding embedded "
    "instructions, no tool or action capability, citation enforcement and flagging (Chapter 12).",
]))
add(h2("HTTP hardening and secrets"))
para("Every response carries a strict Content Security Policy (" + C("script-src 'self'; connect-src 'self'; "
     "frame-ancestors 'none'; object-src 'none'") + "), X-Frame-Options: DENY, nosniff, no-referrer, COOP and a "
     "Permissions-Policy; HSTS is added behind TLS. No credentials are committed: the setup token and checkpoint key are "
     "generated at runtime (0600), logs and audit details scrub secrets, and backup passphrases are never stored.")
add(callout("Security limitations, stated plainly",
            "Host administrators can read the database and files or rewrite the audit log with its key; data at rest is not "
            "encrypted by Atlas (only backups); rate-limit state lives in memory; sensitive protection depends on labelling; no "
            "independent penetration test has been done. Use disk encryption, account separation and off-host checkpoints.",
            "warn"))

# ================================================================================================ 15 audit backup offline
chapter("15", "Audit, Backup and Offline Assurance",
        "Three mechanisms let an organization trust Atlas after the fact: an audit trail that reveals tampering, backups "
        "that are verified before they are needed, and evidence that the process really stayed offline.")
add(h2("Hash-chained audit log"))
addl(figure(D.hash_chain(), "Each event's hash covers the previous hash and the canonical JSON of the event."))
para("Audited actions cover authentication, setup, permission and membership changes, uploads and imports, dataset "
     "changes, merges and match decisions, relationship changes, analyses and SQL (including denials), workflow runs, "
     "assistant use, exports, backups, restores and AI operations. A test drops the trigger, edits a row and confirms "
     "verification reports the exact sequence number.")
add(h2("Backups"))
add(table([
    ["Archive member", "Content"],
    [C("manifest.json"), "Format and software version, schema revision, row counts per table, SHA-256 of every member, encryption flag"],
    [C("database.sqlite3"), "Consistent snapshot via SQLite's online-backup API while Atlas runs; integrity-checked before archiving"],
    [C("workspace/files, derived, exports"), "Uploaded originals, Parquet copies of dataset versions, report and workflow exports"],
    [C("audit-checkpoints.jsonl"), "Signed audit checkpoints"],
    [C("audit-checkpoint.key"), "Checkpoint HMAC key — included in encrypted backups only"],
], [0.3, 0.7], font_size=8.7))
add(Spacer(1, 4))
para("Encrypted backups derive an AES-256-GCM key with scrypt (N = 2<super>15</super>, r = 8, p = 1) from a passphrase of at "
     "least 12 characters; the whole archive is authenticated, so tampering or a wrong passphrase is detected. Backups can "
     "be created from the UI, the CLI or the API, or scheduled with "
     f"{C('ATLAS_BACKUP_INTERVAL_HOURS')} (newest 10 kept; encrypted via {C('ATLAS_BACKUP_PASSPHRASE_FILE')}). "
     "<b>Verification</b> checks decryption, safe paths, every member hash, PRAGMA integrity_check and row counts.")
add(h3("Restore procedure"))
addl(bullets([
    "<b>Preview</b> runs full verification and shows the manifest (counts, schema revision, creation time).",
    "Restore refuses while jobs are running. The current database and workspace are <b>moved aside</b> to "
    f"{C('.pre-restore-&lt;timestamp&gt;/')} — nothing is deleted.",
    "The archive is extracted, the schema migrated forward if older, live row counts compared with the manifest, and the "
    "restore appended to the restored audit chain.",
    "Tested automatically: backup → delete a dataset → restore → identical counts, working search and SQL, valid "
    "audit chain; corruption and wrong-passphrase detection too.",
]))
add(table([
    ["Scenario", "Procedure"],
    ["Workstation loss", "Install from the offline bundle, start once, create a temporary admin, restore the latest archive (its users replace the temporary one)"],
    ["Corrupted database", "Stop Atlas, keep the damaged files, restore the most recent verified backup, re-import newer data (source hashes reveal duplicates)"],
    ["Bad import or deletion", "Restore into a separate workspace to recover specific data, or in place if losing later changes is acceptable"],
    ["Suspected tampering", "Audit verification reports the first broken sequence; compare with externally stored checkpoints and backups"],
], [0.22, 0.78], bold_first=True, font_size=8.7))
add(h2("Offline operation"))
add(table([
    ["Mechanism", "Detail"],
    ["No external assets", "UI bundle contains all JS, CSS and fonts; bundled basemap; no tile, glyph or font URLs; CSP connect-src 'self'"],
    ["No telemetry", f"None is implemented; {C('ATLAS_TELEMETRY_ENABLED=true')} is rejected at startup"],
    ["Network guard", "Socket connect and DNS resolution patched in the atlas-api process; only loopback and private ranges reachable"],
    ["Local AI only", "AI endpoint must be loopback, private or localhost in offline mode; no hosted fallback"],
    ["Loopback binding", f"Default {C('ATLAS_HOST=127.0.0.1')}; LAN binding requires explicit opt-in"],
], [0.22, 0.78], bold_first=True, font_size=8.7))
addl(figure(D.netguard(), "The in-process network guard (core/netguard.py)."))
para(f"<b>Verification mode</b> (Administration → System &amp; offline, {C('GET /api/system/offline-check')} or "
     f"{C('atlas offline-check')}) reports offline mode, telemetry, bind address, AI endpoint locality, guard installation, "
     "blocked attempts and a live probe. The guard covers only the atlas-api process, so air-gap assurance still needs "
     "OS and network controls.")

# ================================================================================================ 16 deployment & ops
chapter("16", "Deployment and Operations",
        "Atlas installs the same way on a developer laptop, an air-gapped workstation and a LAN server. Configuration is a "
        "set of validated environment variables.")
add(h2("Installation paths"))
add(h3("Development checkout"))
add(code_block("""
cd project-atlas
python3 -m pip install -e backend          # Python 3.11+
(cd frontend && npm ci && npm run build)   # Node 20+; builds frontend/dist
cp .env.example .env
atlas serve                                # http://127.0.0.1:8000
"""))
add(h3("Air-gapped workstation"))
add(code_block("""
scripts/build_release.sh                   # connected host, same OS/arch/Python
tar xzf project-atlas-0.2.0-linux_x86_64-py313.tar.gz
cd project-atlas-0.2.0-linux_x86_64-py313
./install.sh /opt/project-atlas            # checks SHA256SUMS, pip --no-index
/opt/project-atlas/atlas offline-check
/opt/project-atlas/atlas serve
"""))
add(h3("Desktop and LAN"))
para(f"{C('scripts/build_desktop.sh')} produces a PyInstaller app that stores data in the platform's user data directory, "
     "starts on a random loopback port and prints the location of the setup token on first run (Linux verified; Windows "
     "and macOS must be built on those systems). For a LAN server, keep atlas-api on loopback behind the TLS reverse proxy "
     f"in {C('deployment/nginx-atlas.conf')}, run it with {C('deployment/atlas-api.service')}, set "
     f"{C('ATLAS_ENV=production')} and {C('ATLAS_TLS_TERMINATED=true')}, and point {C('ATLAS_DATABASE_URL')} at PostgreSQL "
     "(preview). On first start, the server writes a one-time setup token; enter it in the browser to create the first "
     f"System Administrator, or run {C('atlas create-admin')}.")
add(h2("Configuration reference"))
add(table([
    ["Variable", "Default", "Purpose"],
    [C("ATLAS_ENV"), "development", "development | test | production"],
    [C("ATLAS_OFFLINE_MODE"), "true", "Install the outbound network guard"],
    [C("ATLAS_HOST / ATLAS_PORT"), "127.0.0.1 / 8000", "Bind address; non-loopback needs ATLAS_ALLOW_LAN"],
    [C("ATLAS_ALLOW_LAN / ATLAS_TLS_TERMINATED"), "false / false", "LAN opt-in; TLS required for LAN production"],
    [C("ATLAS_DATABASE_URL"), "empty (SQLite)", "SQLAlchemy URL, e.g. PostgreSQL via psycopg"],
    [C("ATLAS_STORAGE_DIR / ATLAS_BACKUP_DIR"), "./atlas-workspace / ./atlas-backups", "Workspace files and backup archives"],
    [C("ATLAS_AI_ENABLED / ATLAS_AI_BASE_URL"), "false / empty", "Optional local model runtime (e.g. Ollama on 127.0.0.1:11434)"],
    [C("ATLAS_MODEL_DIR"), "./models", "Where registered model files must live"],
    [C("ATLAS_SESSION_TTL_MINUTES"), "480", "Sliding session lifetime"],
    [C("ATLAS_MAX_UPLOAD_MB"), "200", "Upload size limit"],
    [C("ATLAS_QUERY_TIMEOUT_SECONDS / _ROW_LIMIT"), "20 / 5000", "SQL console limits"],
    [C("ATLAS_GRAPH_NODE_LIMIT"), "2000", "Maximum nodes per graph view"],
    [C("ATLAS_BACKUP_INTERVAL_HOURS / _RETENTION"), "0 / 10", "Scheduled backups (0 disables) and how many to keep"],
    [C("ATLAS_BACKUP_PASSPHRASE_FILE"), "empty", "0600 file used to encrypt scheduled backups"],
    [C("ATLAS_RETENTION_ENFORCE_HOURS"), "0", "Periodic retention sweep (0 = on demand)"],
    [C("ATLAS_JOBS_INLINE"), "false", "Run jobs inline (tests, constrained machines)"],
    [C("ATLAS_TELEMETRY_ENABLED"), "false", "Must stay false; telemetry is not implemented"],
    [C("ATLAS_LOG_LEVEL / ATLAS_FRONTEND_DIST"), "INFO / bundled UI", "Logging; override the UI location"],
], [0.4, 0.23, 0.37], font_size=8.4))
add(h2("Command-line interface"))
add(table([
    ["Command", "Purpose"],
    [C("atlas serve"), "Run atlas-api and serve the UI"],
    [C("atlas create-admin &lt;name&gt;"), "Create the initial System Administrator on the host"],
    [C("atlas backup [--encrypt]"), "Create a backup archive"],
    [C("atlas verify-backup &lt;file&gt;"), "Verify an archive"],
    [C("atlas offline-check"), "Exit code 0 when offline mode is on and the live probe is blocked"],
    [C("atlas migrate"), "Apply database migrations"],
    [C("atlas-desktop"), "Start the desktop experience from an installed package"],
], [0.36, 0.64], font_size=8.8))
add(h2("Common operational issues"))
add(table([
    ["Symptom", "Cause and fix"],
    ["Startup fails with ConfigError", "An unsafe combination (LAN without opt-in or TLS, telemetry, non-local AI endpoint); the message names the variable"],
    ["Project “not found”", "You are not a member; Atlas does not reveal whether it exists"],
    ["Values show [restricted]", "The field is sensitive and your role lacks sensitive.read"],
    ["“database is locked”", "A second instance holds the SQLite file; run one instance per workspace"],
    ["offline-check shows blocked attempts", "Something in the process tried to reach a non-local address; targets are listed"],
], [0.3, 0.7], bold_first=True, font_size=8.6))

# ================================================================================================ 17 walkthrough
chapter("17", "Guided Tour: the Northwind Harbor Demo",
        "The fastest way to understand Atlas is the synthetic demo workspace. This chapter follows the same path the user "
        "guide and the acceptance scenario take.")
add(h2("The synthetic dataset"))
add(table([
    ["File", "Contents and planted defects"],
    [C("synthetic_people.csv"), "33 rows / 32 unique people: 1 exact duplicate row, 1 missing and 1 invalid e-mail, 1 null-token phone; each person works for one organization"],
    [C("synthetic_organizations.csv"), "8 organizations (Northwind Harbor Logistics Ltd, Saltmarsh Consulting, Halcyon Trading GmbH, Bluefjord Freight AS …)"],
    [C("synthetic_contacts.csv"), "5 contacts known by name only — the source of the resolution test cases"],
    [C("synthetic_transactions.csv"), "60 transactions: 1 invalid timestamp, 1 latitude out of range, 1 null-island point, 2 statistical outliers (T-5007, T-5023)"],
    ["Documents (5)", "Harbor audit report (PDF, 2 pages), meeting minutes (DOCX), shipment e-mail (EML), cold-storage memo and a prompt-injection note (TXT)"],
    [C("synthetic_districts.geojson"), "4 district polygons for spatial joins"],
], [0.34, 0.66], font_size=8.6))
add(h2("Step by step"))
steps = [
    ("Sign in", "Paste the setup token from atlas-workspace/setup-token.txt, choose a username and a strong password. The top bar "
     "shows the project, global search, jobs, alerts, the green <i>Offline</i> badge and AI status."),
    ("Create the demo", "<i>Projects → Create demo workspace</i> builds the project through the normal audited pipelines in "
     "seconds: 4 datasets, 106 records, 5 documents, district polygons and match candidates, with live progress."),
    ("Navigate", "Press Ctrl/⌘ K to jump to any page, dataset, document or entity, run actions, or save the current page as "
     "a view. <i>g</i> followed by a letter jumps between modules; <i>?</i> lists shortcuts."),
    ("Inspect quality", "The Data Catalog shows the planted defects: duplicate row and key, invalid e-mail, timestamp and "
     "coordinate errors — each with an explanation."),
    ("Resolve entities", "Entity Explorer → Match review shows 2 strong candidates and 1 ambiguous one; merge Dr. Amelia "
     "Okafor with Amelia Okafor and note the reason."),
    ("Explore the graph", "Northwind Harbor Logistics Ltd has 4 <i>works for</i> edges; run PageRank or communities, then "
     "explain the connection between two people."),
    ("Analyse", "Run outlier detection on <i>amount</i>: T-5007 and T-5023 are flagged with the disclaimer; reproduce the run "
     "and compare hashes."),
    ("Read documents", "Ask “Who approved the large payments?” — the assistant quotes the audit report, page 2; ask "
     "about something absent and it declines."),
    ("Report and audit", "Build a report with findings and an evidence register, export to PDF, check the manifest hash, then "
     "verify the audit chain in the Audit Center."),
]
rows = [["#", "Step", "What to do and what you should see"]]
for i, (s, t) in enumerate(steps, 1):
    rows.append([str(i), s, t])
add(table(rows, [0.05, 0.17, 0.78], font_size=8.6, bold_first=False))
addl(screenshot(shot("23-demo-home.png"), "Atlas Home after creating the demo workspace: KPI tiles, events over time, "
                "relationships by basis, most-connected entities and data quality, all computed locally.", width=CONTENT_W * 0.95))
addl(screenshot_pair((shot("24-command-palette.png"), "Command palette (Ctrl/⌘ K): pages, datasets, documents, entities, saved views and actions."),
                     (shot("18-dataset-quality.png"), "Data Catalog quality tab listing issues by row, field, check and severity."),
                     "Navigation and catalog views from the demo."))

# ================================================================================================ 18 API
chapter("18", "API Reference Overview",
        "Everything the UI does goes through a documented REST API, so Atlas can be scripted, integrated and tested "
        "without the browser.")
add(h2("Conventions"))
addl(bullets([
    f"Base path {C('/api')}; interactive documentation at {C('/api/docs')} and the machine-readable spec in "
    f"{C('docs/openapi.json')} (regenerated by {C('scripts/generate_api_docs.py')}).",
    f"Authentication: {C('Authorization: Bearer &lt;token&gt;')} from {C('POST /api/auth/login')} or {C('/api/auth/setup')}.",
    f"Project-scoped routes live under {C('/api/projects/{project_id}/…')} and return 404 to non-members.",
    f"Errors share one shape, {C('{&quot;error&quot;: {&quot;code&quot;, &quot;message&quot;, &quot;details&quot;}}')}, with HTTP "
    "400, 401, 403, 404, 409, 422, 429 or 503 (AI disabled).",
    f"Long-running work returns a job id; follow it via {C('GET /api/jobs/{id}')} or the SSE stream.",
]))
addl(figure(hbar_chart([
    ("entities + graph", 19), ("administration", 16), ("analytics, SQL, timeline, geo", 16), ("ai", 14),
    ("projects", 13), ("investigations", 13), ("workspace (0.2)", 13), ("auth", 12), ("data", 12), ("workflows", 9),
    ("documents", 8), ("reports", 8), ("search", 6), ("jobs", 5), ("system", 2), ("health", 1),
], label_w=170, bar_h=10, gap=4.5), "167 API operations by group."))
add(h2("Selected endpoints"))
add(table([
    ["Method & path", "Purpose"],
    ["POST /api/projects/{p}/ingest/inspect", "Detect format, encoding, delimiter and types; preview"],
    ["POST /api/projects/{p}/ingest/preview", "Dry run over the full file — validation, quality checks, transformed preview; writes nothing"],
    ["POST /api/projects/{p}/ingest/commit", "Start the import job"],
    ["POST /api/projects/{p}/entities/resolve", "Run entity resolution as a job"],
    ["POST /api/projects/{p}/match-candidates/{id}/review", "Accept (with survivor and reason) or reject a candidate"],
    ["POST /api/projects/{p}/merges/{id}/revert", "Revert a merge from its snapshot"],
    ["GET  /api/projects/{p}/graph/explain", "Shortest paths with per-hop relationships and evidence"],
    ["POST /api/projects/{p}/analyses/{id}/reproduce", "Re-execute a run and compare result hashes"],
    ["POST /api/projects/{p}/sql", "Sandboxed read-only SQL"],
    ["POST /api/projects/{p}/documents/ask", "Grounded document assistant"],
    ["POST /api/projects/{p}/reports/{id}/export", "Export PDF/HTML/XLSX/CSV/JSON with manifest"],
    ["POST /api/admin/audit/verify", "Verify the audit hash chain"],
    ["POST /api/admin/backups/restore", "Preview (confirm=false) or perform (confirm=true) a restore"],
    ["GET  /api/system/offline-check", "Offline verification report"],
], [0.52, 0.48], font_size=8.4, mono_cols=(0,)))
add(h2("Example: run and reproduce an analysis"))
add(code_block("""
POST /api/projects/prj_…/analyses
{"kind": "outliers", "dataset_id": "dst_…", "params": {"field": "amount"}}

→ 200 {"id": "anr_…", "kind": "outliers", "result_sha256": "580dfffb10e2…",
       "result": {"method": "Tukey fences (k=1.5) with robust z (median/MAD) for ranking",
                  "outlier_count": 2, "disclaimer": "…not evidence of wrongdoing…"}}

POST /api/projects/prj_…/analyses/anr_…/reproduce
→ 200 {"identical": true, "result_sha256": "580dfffb10e2…"}
"""))
add(P("Field names in the example are abbreviated for illustration; the full schemas are in docs/openapi.json.", "small",
      textColor=MUTED))

# ================================================================================================ 19 testing & performance
chapter("19", "Testing, Validation and Performance",
        "Claims in this document are backed by automated suites, a scripted release scenario that includes running with "
        "the network removed, and measured benchmarks.")
add(h2("Test suites (release 0.2.0)"))
add(table([
    ["Suite", "Command", "Result"],
    ["Backend unit, integration and security", C("cd backend && python -m pytest"), "111 passed"],
    ["Frontend unit (Vitest)", C("cd frontend && npm test"), "11 passed"],
    ["Frontend type check", C("npx tsc -b"), "clean"],
    ["UI end-to-end (Playwright, real server)", C("frontend/tests/e2e/smoke.mjs"), "passed; no console or page errors across all modules"],
    ["Release acceptance scenario", C("scripts/acceptance_scenario.py"), "all 14 steps passed (≈ 12 s)"],
    ["Offline install from release bundle", "install + offline-check + serve inside unshare -rn", "passed (install 20.8 s)"],
    ["Packaged desktop app (Linux)", "started inside unshare -rn", "passed (startup 2.5 s)"],
], [0.32, 0.38, 0.30], font_size=8.5))
add(h2("What the backend tests cover"))
add(table([
    ["Area", "Examples of what is asserted"],
    ["Authentication", "Setup token required and consumed; weak passwords rejected; lockout; identical errors; session revocation; TOTP; single-use reset tokens"],
    ["Authorization", "404 for non-members on every project route; cross-project ids unusable; read-only blocked from writes; no self-escalation; restricted and sensitive data hidden"],
    ["Injection & malformed input", "FTS injection strings; 14 unsafe SQL variants; sandbox with validator bypassed; forbidden types; magic-byte mismatch; XML entity expansion; path traversal; CSV formula injection; prompt injection"],
    ["Ingestion", "Inference; dry run writes nothing; quality counts match planted defects; all formats; cp1252 and mojibake; DST conversion; failed job leaves no partial data"],
    ["Entities & graph", "Ground-truth matches; merge/revert restores exactly; PageRank checked against NetworkX; snapshots and exports; hypotheses hidden until verified"],
    ["Analytics, time, geo", "Planted outliers; reproducibility and changed-input detection; geo never invents coordinates; joins, radius, clustering"],
    ["Case work & reports", "Verbatim evidence; finding state machine; workflow validation, preview, rollback; five report formats with manifests; Unicode PDFs"],
    ["Platform", "Audit tamper detection at the exact sequence; backup → change → restore; encrypted backup failure modes; network guard; 7 unsafe configurations"],
], [0.22, 0.78], bold_first=True, font_size=8.5))
add(h2("Release acceptance scenario"))
add(table([
    ["#", "Step", "Recorded outcome"],
    ["1–3", "Install, initial administrator, workspace", "Package importable; wrong token refused (403); real token consumed and file deleted; project created"],
    ["4–5", "Import and dry run", "8 + 33 + 5 + 60 records; dry run reports 1 timestamp and 2 coordinate errors, writes nothing"],
    ["6–7", "Resolve and explore", "3 candidates, 2 strong as expected, merge accepted; 4 works_for edges on Northwind Harbor Logistics"],
    ["8–9", "Evidence and analysis", "Row hash and source-file SHA-256 match; 2 outliers, reproduction hash identical"],
    ["10–12", "Report, restart, persistence", "PDF bytes match manifest hash; new process; counts identical; audit chain valid over 32 events"],
    ["13–14", "Disable network, repeat", "Network namespace with loopback only; login, imports, resolution, merge, analysis, assistant, PDF and offline-check all pass"],
], [0.08, 0.27, 0.65], font_size=8.5))
add(h2("Performance measurements"))
para("Measured with <i>scripts/benchmark.py --rows 100000 --people 5000</i> on Linux x86-64, 4 vCPU, 15 GB RAM, Python 3.13, "
     "SQLite, single run. The workload produced 205,000 records, 5,499 entities and 99,767 relationships in a 623 MB "
     "database; peak memory of the whole benchmark process was 1.29 GB.")
addl(figure(hbar_chart([
    ("Import 100k rows with entities, links, events, geo", 109.4), ("Betweenness (sampled, k = 500)", 46.5),
    ("Backup (623 MB → 161 MB archive)", 46.2), ("Entity resolution, 5,499 people", 29.8),
    ("Backup verification", 18.8), ("Import 100k rows, plain", 15.8), ("Import 5,000 people with entities", 12.6),
    ("Louvain communities", 8.7), ("PageRank", 6.1), ("PDF report, 2,000-row table", 2.9),
    ("Graph overview (top 300 nodes)", 0.88), ("Describe, 100k rows", 0.51), ("SQL aggregate, 100k rows", 0.50),
    ("Outliers, 100k rows", 0.41), ("Geo radius query", 0.39), ("Timeline query, 2,000 events", 0.20),
], label_w=228, bar_h=9.5, gap=4, value_fmt=lambda v: (f"{v:.1f}" if v >= 1 else f"{v:.2f}"), unit=" s"),
    "Benchmark timings in seconds (linear scale). Full-text search over ≈ 205,000 indexed rows: p50 166 ms, p95 374 ms."))
para("The measurements drove concrete improvements before release: full import throughput rose from ≈ 350 to "
     "≈ 900 rows/s by batching dependent inserts, deduplicating attribute provenance and adding an indexed FTS rowid map "
     "(migration 0003); the graph overview fell from 6.6 s to 0.9 s by ranking degrees in SQL; and a missing SciPy dependency "
     "for PageRank was replaced with a verified power iteration. Plain imports run at ≈ 6,300 rows/s.")
add(callout("Sizing guidance (extrapolated, not a certification)",
            "4 cores and 8 GB RAM handle projects of a few hundred thousand records and about 10<super>5</super> relationships "
            "comfortably. Exact betweenness and Louvain on much larger graphs take minutes — use filters or sampling. Budget "
            "roughly 3 KB of database per indexed record plus Parquet copies; no GPU is needed for non-AI features.", "info"))

# ================================================================================================ 20 status & roadmap
chapter("20", "Status, Limitations and Roadmap",
        "Atlas documents its own gaps. This chapter consolidates what is complete, what is partial, what was deferred "
        "and the risks an adopter should weigh.")
add(h2("Completed and tested"))
para("Identity and access · projects and membership · permitted data sources · ingestion of 8 formats with "
     "inspection, mapping, normalization, dry runs, cancel/retry and progress · 13 quality checks · catalog with "
     "versions, lineage, access and retention · ontology editing · entity resolution with review and reversible merges "
     "· knowledge graph · unified search · document intelligence and grounded assistant · timeline · offline "
     "maps · reproducible analytics · sandboxed SQL · investigations and findings · workflows · reports with "
     "manifests · hash-chained audit · backup, verify and restore · offline verification · Linux offline bundle "
     "and desktop app · UI for all modules · synthetic dataset with ground truth · 0.2 usability features.")
add(h2("Partial"))
add(table([
    ["Area", "What exists", "What is missing"],
    ["Local AI", "All assistants with citation and validation checks", "Not run against a real model; rerankers unused"],
    ["OCR", "tesseract/pdftoppm path for image-only PDF pages", "Untested here; no OCR for standalone images"],
    ["Language detection", "Stop-word heuristic for 7 languages", "Other languages report “undetermined”"],
    ["Tabs", "Route tabs, saved views, snapshots, command palette", "Tabs are page history, not independent workspaces"],
    ["Resumable processing", "Atomic, idempotent retry from the start", "No mid-file resume"],
    ["Field-level permissions", "Sensitive flag with role-based redaction", "No per-user or per-field grants"],
    ["Model permissions", "Global admin.models; AI use per project role", "No per-project model allow-lists"],
    ["Workflow editor", "Typed nodes, validation, preview, runs, versions", "Complex parameters edited as JSON"],
    ["Retention", "Superseded versions purged; owners notified", "Current versions never deleted automatically (by design)"],
    ["Geospatial", "Points, polygons, bbox, radius, joins, clustering", "Planar point-in-polygon; no line/polygon intersection; 1:110m basemap"],
    ["Account recovery", "Administrator-issued one-time tokens", "No self-service recovery (deliberate, offline)"],
], [0.2, 0.42, 0.38], bold_first=True, font_size=8.4))
add(h2("Deferred, and implemented but untested"))
addl(bullets([
    "<b>Deferred:</b> native Tauri/Electron shell; Windows .exe/MSI and macOS builds (must be produced on those systems); a "
    "dedicated graph database, external search engine or vector database (not justified at measured scale); multi-process "
    "job workers.",
    "<b>Implemented but untested:</b> PostgreSQL deployment (migrations, tsvector search, connection), the PowerShell installer, "
    "Windows/macOS desktop launcher behaviour, the nginx/systemd LAN examples and the OCR path.",
]))
add(h2("Outstanding risks"))
add(table([
    ["#", "Risk", "Mitigation"],
    ["1", "Host administrators can read data and rewrite the audit log with its key", "Disk encryption, OS account separation, off-host checkpoints and backups"],
    ["2", "Network guard is process-local and allows private ranges", "OS firewall rules, removed interfaces, physical isolation"],
    ["3", "PostgreSQL untested", "Validate before multi-user production use"],
    ["4", "SQLite allows one writer; long imports block other writes", "Single-user and small teams; PostgreSQL once validated"],
    ["5", "Rate limits and lockouts reset on restart", "Reverse-proxy rate limiting on LAN deployments"],
    ["6", "Entity resolution is heuristic; name blocking can miss matches", "Identifier blocking; human review of every merge"],
    ["7", "In-memory graph algorithms slow beyond 10<super>5</super> edges", "Filters and sampled betweenness"],
    ["8", "Sensitive protection depends on labelling", "Ontology defaults mark common sensitive fields"],
    ["9", "No independent penetration test", "Commission one before high-assurance deployment"],
    ["10", "Dependencies pinned by minimum version only", "Release bundles freeze exact versions; rebuild and re-test on update"],
], [0.05, 0.5, 0.45], font_size=8.4))
add(h2("Suggested roadmap"))
para("The following priorities follow directly from the partial, deferred and risk items above. They are recommendations "
     "drawn from the engineering report, not commitments recorded in the repository.")
add(table([
    ["Horizon", "Focus"],
    ["Next release", "Validate PostgreSQL end to end and add it to CI; run the AI assistants against a real local model; test the OCR path; build and test Windows and macOS packages"],
    ["Following", "Independent penetration test; per-project model allow-lists; finer-grained field permissions; workflow parameter forms instead of JSON"],
    ["Later", "Multi-process job workers; mid-file resumable imports; polygon intersection operations and higher-detail offline basemaps; optional native desktop shell"],
], [0.18, 0.82], bold_first=True, font_size=8.8))

# ================================================================================================ appendix
chapter("A", "Glossary", "Terms used throughout this document and the product.", kicker="Appendix A")
add(table([
    ["Term", "Definition"],
    ["Assertion basis", "Where a relationship came from: observed, inferred, model_suggested or manual"],
    ["Blocking", "Restricting entity comparisons to pairs that share a name token or identifier, to keep matching tractable"],
    ["Candidate (match)", "A pair of entities proposed by the matcher with a score, band and evidence, awaiting review"],
    ["Checkpoint", "An HMAC-signed record of the audit chain head written outside the database"],
    ["Dataset version", "An immutable import of a dataset with its mapping, schema, quality summary and content hash"],
    ["Dry run", "Full-file validation and quality checking that writes nothing"],
    ["Evidence", "A verbatim excerpt from a record or document passage with location and revisions, attached to an investigation"],
    ["Finding", "A statement in an investigation that moves through draft, review and confirmation with linked evidence"],
    ["Identity key", "A deterministic key derived from identifier fields, used to merge records describing the same entity at import"],
    ["Manifest", "The provenance record attached to every report export: inputs, versions, parameters, software and redactions"],
    ["Network guard", "The in-process patch on socket connections and DNS that enforces offline mode"],
    ["Normalized value", "The typed, cleaned value derived from a raw source value; both are stored"],
    ["Ontology", "The project's configurable entity and relationship types and their fields"],
    ["Restricted dataset", "A dataset visible only to roles with restricted access"],
    ["Sensitive field", "A field redacted for roles without sensitive.read and excluded from search"],
    ["Snapshot (graph)", "Saved node and edge ids, layout and filters for a graph view"],
    ["Synthetic data", f"Fictional demonstration data marked {C('record_origin=SYNTHETIC')}"],
    ["Workspace", "A project: its data, members, ontology and work products; also the on-disk storage directory"],
], [0.22, 0.78], bold_first=True, font_size=8.8))
add(Spacer(1, 10))
add(callout("Source documents in the repository",
            "README.md · docs/architecture.md · data-model.md · security.md · offline-operation.md · "
            "installation.md · backup-recovery.md · user-guide.md · troubleshooting.md · api.md and openapi.json "
            "· engineering-report.md · release-notes.md · sample-data/expected_results.json. This overview is "
            "regenerated with docs/overview/source/build_pdf.py.", "neutral"))


# ================================================================================================ appendix B
chapter("B", "Frequently Asked Questions", "Short answers to the questions evaluators ask most often.", kicker="Appendix B")
faqs = [
    ("Does Atlas need internet access?",
     "No. It installs from an offline bundle and runs with an in-process network guard that blocks every non-local "
     "connection. The acceptance scenario repeats the core workflow inside a Linux network namespace with loopback only."),
    ("Can it run without a GPU or a language model?",
     "Yes. Every feature works without AI. A local Ollama-compatible model is optional and only adds assistants whose "
     "output is labelled, cited and confirmed by a person."),
    ("How does Atlas decide two records are the same person?",
     "It does not decide \u2014 it proposes. Algorithm er-1.1 blocks on shared name tokens or identifiers, scores only the "
     "features both records have, and marks a pair strong only when an identifier agrees and none conflicts. A reviewer "
     "accepts or rejects every candidate, and merges can be reverted."),
    ("Can an administrator see all project data?",
     "No. System administrators manage the platform but see project data only if they are project members. Restricted "
     "datasets and sensitive fields are further limited by project role and enforced by the backend."),
    ("What stops someone editing the audit log?",
     "Triggers reject updates and deletes, each event is hash-chained to the previous one, and HMAC-signed checkpoints "
     "live outside the database; verification reports the first broken sequence number."),
    ("Is the SQL console safe to give analysts?",
     "It accepts single read-only statements, loads only permitted tables into an in-memory DuckDB, disables external "
     "access and locks configuration before the query runs, and applies row, memory, thread and time limits."),
    ("Can results be reproduced months later?",
     "Yes. Every analysis records the dataset versions and their content hashes, parameters and software versions, plus a "
     "hash of the result. Reproduce re-runs it and either confirms an identical hash or reports changed inputs."),
    ("How large a dataset can it handle?",
     "On 4 vCPU, 100,000 rows imported in 15.8 s (plain) or 109 s (with entities, links, events and geo), and search "
     "over 205,000 rows ran at p95 374 ms. A few hundred thousand records are comfortable on 4 cores and 8 GB."),
    ("Which databases and operating systems are supported?",
     "SQLite is the tested default. PostgreSQL is implemented for LAN servers but untested. Linux builds are verified; "
     "Windows and macOS packages must be built and tested on those systems."),
    ("Is the sample data real?",
     "No. Every person, organization, document and coordinate in sample-data/ is synthetic, generated deterministically "
     "with seed 20251027 and marked record_origin=SYNTHETIC; expected results are documented in expected_results.json."),
]
for q, a in faqs:
    add(KeepTogether([P(q, "h3", spaceBefore=6), P(a)]))


# ================================================================================================ build
def build():
    doc = AtlasDoc(str(OUT))
    doc.multiBuild(story)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
