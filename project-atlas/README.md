# PROJECT ATLAS

**Navigate the Complexity of Data.** — Offline Intelligence and Data Operations Platform

Project Atlas is an offline-first, local-control platform for importing authorized datasets and
documents, normalizing and quality-checking records, resolving entities, exploring evidence-backed
relationships, running reproducible analyses, and producing auditable reports — without any cloud
dependency. It is an original implementation built for authorized research, compliance, auditing
and organizational analysis.

| | |
|---|---|
| Short name | Atlas |
| Python distribution / import | `project-atlas` / `project_atlas` |
| API service | `atlas-api` (FastAPI, OpenAPI at `/api/docs`) |
| UI package | `project-atlas-ui` (React + TypeScript + Vite) |
| Desktop app | `Project Atlas` (PyInstaller bundle + chromeless browser window) |
| Config prefix | `ATLAS_` (see `.env.example`) |

## What works today

Everything listed here has real backend behaviour, access control and automated tests
(see [docs/engineering-report.md](docs/engineering-report.md) for test results, measurements and
the completed / partial / deferred matrix).

- **Identity & access** — Argon2id passwords, one-time setup token for the first administrator, sessions
  with sliding expiry and revocation, login rate limiting and lockout, optional TOTP MFA, admin-issued
  one-time recovery tokens, global roles (System/Security Administrator) and project roles
  (Project Administrator, Data Engineer, Analyst, Reviewer, Read-Only), restricted datasets and
  sensitive-field redaction enforced on the backend.
- **Ingestion & catalog** — CSV, TSV, XLSX, JSON, JSONL, XML, SQLite, Parquet; encoding/delimiter/type
  detection, column mapping, normalization (time zones, numbers, phones, emails, case), dry runs, 13 quality
  checks, versioned datasets with lineage, original values kept separately from normalized values.
- **Ontology & entity resolution** — configurable entity/relationship types; deterministic, explainable
  matching (algorithm `er-1.1`) with evidence, conflicts and "not compared" fields; human review; reversible merges.
- **Knowledge graph** — typed, directional relationships labelled *observed / deterministic inference /
  model hypothesis / manual*; neighbourhoods, filters, paths, components, centrality, Louvain communities,
  snapshots, GraphML/GEXF/JSON export.
- **Search & documents** — FTS5 search with Boolean/phrase/prefix/field filters and history; PDF/DOCX/TXT/MD/EML
  extraction, language detection, keywords, entity candidates, duplicate detection, page-level evidence and a
  grounded document assistant that cites passages and refuses without evidence.
- **Timeline & maps** — UTC event times with source text/zone, clustering, comparisons, time-windowed
  relationships; offline MapLibre maps (bundled Natural Earth), radius/bbox/distance, spatial joins, heatmaps,
  clustering, annotations.
- **Analytics** — descriptive stats, frequencies, trends, correlation (with CIs), outliers (with a
  not-evidence-of-wrongdoing disclaimer), missing data, time series; every run reproducible by hash;
  sandboxed read-only DuckDB SQL console.
- **Optional local AI** — model registry with checksums and health; grounded answers, SQL drafts (validated,
  never auto-executed), summaries, relationship hypotheses (stored unverified), embeddings and semantic search via
  a local Ollama-compatible endpoint. No external fallback; everything else works without a model.
- **Investigations, workflows, reports** — evidence with revisions, findings with a reviewed state machine;
  typed visual workflows with preview, confirmation for side effects and rollback on failure; reports in
  PDF/HTML/CSV/JSON/XLSX with a manifest.
- **Audit, backup, offline** — append-only, hash-chained audit log with signed checkpoints; consistent
  (optionally AES-256-GCM encrypted) backups with verification and restore; in-process outbound network guard
  and an offline verification report.

- **Usability (0.2)** — one-click synthetic demo workspace, `Ctrl/⌘ K` command palette, saved views, entity
  watchlists with in-app notifications, activity feed and insight dashboard, *explain connection* between two
  entities with per-hop evidence, plain-language quality explanations, retention enforcement, encrypted scheduled
  backups, project archive/delete.

## Quick start (development checkout)

```bash
cd project-atlas
python3 -m pip install -e backend            # Python 3.11+
(cd frontend && npm ci && npm run build)     # Node 20+; produces frontend/dist served by atlas-api
cp .env.example .env
atlas serve                                  # http://127.0.0.1:8000
```

On first start the server writes a one-time setup token to `atlas-workspace/setup-token.txt`;
enter it in the browser to create the initial System Administrator (or run `atlas create-admin <name>`).
Then choose *Projects → Create demo workspace* to explore the synthetic Northwind Harbor data, or create a
project and import your own (walkthrough in [docs/user-guide.md](docs/user-guide.md)).

Offline / air-gapped installation from a release bundle, LAN deployment and the desktop build are
described in [docs/installation.md](docs/installation.md) and [docs/offline-operation.md](docs/offline-operation.md).

## Tests

```bash
cd backend && python -m pytest                       # 111 API/unit/security tests
cd frontend && npm test                              # unit tests (Vitest)
python scripts/acceptance_scenario.py                # 14-step release scenario incl. a network-isolated phase (Linux)
ATLAS_URL=http://127.0.0.1:8000 ATLAS_SETUP_TOKEN_FILE=atlas-workspace/setup-token.txt node frontend/tests/e2e/smoke.mjs   # UI E2E
python scripts/benchmark.py                          # performance measurements
```

## Repository layout

```
project-atlas/
├── backend/project_atlas/   api, core, security, database (+ Alembic migrations), ingestion, ontology,
│                            entities, graph, search, documents, temporal, geospatial, analytics, ai,
│                            workflows, investigations*, reporting, audit, backup, cli, desktop
├── backend/tests/           pytest suite
├── frontend/                React UI (src/app, components, features/*, services, types) + tests
├── desktop/                 PyInstaller spec, launcher, icons
├── deployment/              offline installers, LAN reverse-proxy and service examples
├── scripts/                 sample-data generator, acceptance scenario, benchmark, release/desktop builds
├── sample-data/             SYNTHETIC demonstration data + expected_results.json
└── docs/                    architecture, installation, offline operation, security, data model, user guide,
                             backup & recovery, troubleshooting, API, release notes, engineering report
```

\* Investigation logic lives in `api/investigations.py` (no separate service module was needed).

## Documentation

[Architecture](docs/architecture.md) · [Installation](docs/installation.md) · [Offline operation](docs/offline-operation.md) ·
[Security](docs/security.md) · [Data model](docs/data-model.md) · [User guide](docs/user-guide.md) ·
[Backup & recovery](docs/backup-recovery.md) · [Troubleshooting](docs/troubleshooting.md) · [API](docs/api.md) ·
[Release notes](docs/release-notes.md) · [Engineering report](docs/engineering-report.md)

## License

MIT — see [LICENSE](LICENSE). Bundled DejaVu fonts and Natural Earth data keep their own licenses.
