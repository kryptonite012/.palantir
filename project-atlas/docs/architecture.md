# Architecture

Project Atlas is a **modular monolith**: one Python process (`atlas-api`) serves the REST API, runs
background jobs and serves the built React UI. Additional services are introduced only where they are
required (an optional local model runtime such as Ollama; PostgreSQL for multi-user LAN deployments).

```
 Browser / desktop window (React UI, same origin, CSP 'self')
        │  HTTPS (LAN, via reverse proxy) or HTTP on loopback (desktop)
        ▼
 ┌──────────────────────────── atlas-api (FastAPI, uvicorn) ───────────────────────────┐
 │ api/        routers: auth, admin, projects, data, entities+graph, search, documents,│
 │             analysis (analytics/SQL/timeline/geo), investigations, workflows,       │
 │             reports, ai, system                                                    │
 │ security/   Argon2id, sessions, TOTP, RBAC, rate limiting                           │
 │ core/       config validation, context, job runner, network guard                   │
 │ domain      ingestion · ontology · entities · graph · search · documents · temporal │
 │             geospatial · analytics · ai · workflows · reporting · audit · backup    │
 └─────┬──────────────┬───────────────┬────────────────┬───────────────┬──────────────┘
       │              │               │                │               │ (optional, loopback/LAN only)
  SQLite/PostgreSQL  FTS5 index   Parquet per dataset  Files on disk   Ollama-compatible runtime
  (system of record) (search)     version (DuckDB/     (originals,     (chat + embedding models)
                                   pandas analytics)    exports)
```

## Responsibilities of each store

| Store | Responsibility | Why |
|---|---|---|
| SQLite (single user) / PostgreSQL (LAN) via SQLAlchemy + Alembic | System of record: users, sessions, projects, datasets/versions, records (raw + normalized JSON), entities, relationships, documents/chunks, investigations, workflows, reports, audit log, backups | Transactions, constraints, migrations; SQLite needs no server and backs up with the online-backup API |
| `search_index` (SQLite FTS5 / PostgreSQL tsvector) | Full-text search over records, entities, documents, reports, investigations with access tags | Built-in, no extra service; BM25 ranking and snippets |
| Parquet file per dataset version (`atlas-workspace/derived/datasets/`) | Columnar copy of normalized records for analytics, SQL and workflows | Fast scans with pandas/DuckDB/Arrow; immutable per version ⇒ reproducibility |
| DuckDB (in-memory, per query) | Read-only SQL console | Isolated: only permitted tables are loaded, external access disabled |
| NetworkX (in-memory, per request) | Graph algorithms over relationships | Adequate to ~10⁵ edges on a workstation; a graph database is not justified at that scale |
| Filesystem (`atlas-workspace/files`, `exports`) | Uploaded originals (never modified), report exports with manifests | Originals stay byte-identical; SHA-256 recorded |

## Key flows

**Ingestion** — `upload → inspect → map → dry run → commit job`. The commit runs in one database
transaction: records (raw + normalized), quality issues, search index rows, entities, relationships,
events and geo features, plus a Parquet copy. Failure or cancellation rolls everything back.

**Entity resolution** — blocking on name tokens and identifier values; weighted comparison over
features present on both sides; candidates stored with evidence and algorithm version; reviewers
accept or reject; merges store a snapshot and can be reverted.

**Analytics** — each run stores dataset version ids and content hashes, parameters, algorithm and
software versions, duration and a SHA-256 of the canonical result. Reproduction re-executes on the
recorded inputs and compares hashes.

**Jobs** — persisted in `jobs`; a small thread pool (or inline mode) runs handlers; progress is kept in
memory during long imports (SQLite permits one writer) and persisted at the end; SSE stream at
`/api/jobs/{id}/events`; cancellation and retry; jobs interrupted by a restart are marked failed and
retryable.

**Audit** — every security-relevant action appends a hash-chained event in its own transaction (denials
are recorded even when the request fails).

## Deployment profiles

| Profile | Binding | Database | Notes |
|---|---|---|---|
| Standalone desktop | 127.0.0.1, random port | SQLite in the user data dir | `atlas-desktop` / packaged `Project Atlas` app |
| Air-gapped workstation | 127.0.0.1 | SQLite | Installed from the offline bundle; see offline-operation.md |
| Private LAN server | `ATLAS_HOST=0.0.0.0` + `ATLAS_ALLOW_LAN=true` behind TLS proxy (`ATLAS_TLS_TERMINATED=true` required in production) | PostgreSQL recommended | Example nginx + systemd files in `deployment/` |

The same code serves all profiles; startup validation refuses unsafe combinations (non-loopback
binding without LAN opt-in, LAN production without TLS, non-local AI endpoints in offline mode,
telemetry).

## Frontend

React 18 + TypeScript + Vite, Tailwind CSS (custom component layer, light/dark themes via CSS
variables), React Router, TanStack Query, Zustand, ECharts, Cytoscape.js, MapLibre GL with a bundled
GeoJSON basemap, React Flow. The session token is kept in `sessionStorage`; UI preferences in
`localStorage`. The production build is served by atlas-api from the same origin under a strict CSP.

## Desktop shell decision

Tauri requires WebKitGTK/WebView2 toolchains and Electron adds ~150 MB plus a second runtime. The
shipped desktop shell is a PyInstaller bundle (Python + all dependencies + UI) that starts atlas-api on
loopback and opens a chromeless Edge/Chrome/Chromium window (`--app`) or the default browser. This keeps
one runtime and one security boundary. A native Tauri wrapper remains a possible future option.
