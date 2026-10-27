# Engineering report — PROJECT ATLAS 0.1.0

Date: 2026-10-27. Build/test machine: Linux x86-64 (kernel 6.18), 4 vCPU, 15 GB RAM, Python 3.13.17,
Node 22.22. All figures below were measured in this environment; nothing is estimated unless stated.

## 1. Test outcomes

| Suite | Command | Result |
|---|---|---|
| Backend unit/integration/security | `cd backend && python -m pytest` | **97 passed** (52.8 s) |
| Frontend unit (Vitest) | `cd frontend && npm test` | **8 passed** |
| Frontend type check | `npx tsc -b` | clean |
| UI end-to-end (Playwright/Chromium, real server) | `frontend/tests/e2e/smoke.mjs` | **passed**, no browser console/page errors across all 16 modules |
| Release acceptance scenario (§24, 14 steps) | `scripts/acceptance_scenario.py` | **all steps passed** (11 s); results in `acceptance-results.json` |
| Offline install from release bundle | install + `offline-check` + serve inside `unshare -rn` | **passed** (install 20.8 s) |
| Packaged desktop app (Linux) | started inside `unshare -rn` | **passed** (startup 2.5 s, UI + setup flow served) |
| Stale identifier scan | `scripts/check_identifiers.sh` | no hits |

### What the backend tests cover

* **Authentication** — setup token required/consumed, weak passwords rejected, lockout after 5 failures,
  identical responses for unknown user vs bad password, logout/session revocation, password change
  revokes other sessions, TOTP enrolment and login, reset-token recovery (single use), admin MFA reset,
  disabled users lose sessions, security headers.
- **Authorization** — non-members get 404 on every project route (and are audited), IDs from other
  projects unusable, global search scoped to membership, read-only role blocked from writes/SQL/
  investigations, privilege escalation via self-patch refused, last admin protections, restricted datasets
  invisible to analysts in catalog/search, sensitive fields redacted in records, raw values, entities,
  SQL and search, sensitive export redaction with manifest note, read-only cannot export.
- **Injection & malformed input** — FTS query injection strings, 14 unsafe SQL variants rejected, SQL
  sandbox blocks file access even with the validator disabled, row limit and timeout, forbidden file types,
  magic-byte mismatches, empty/binary files, XML entity expansion, invalid JSON, path traversal in file
  names, invalid mappings/time zones/entity types, CSV formula injection, prompt-injection document flagged
  and not followed, model answers without valid citations withheld, model SQL `DROP TABLE` rejected and
  never executed.
- **Ingestion** — schema/encoding/delimiter inference, dry run writes nothing, quality counts match the
  planted defects, originals vs normalized, versions and schema drift, JSONL/JSON/TSV/XML/XLSX/SQLite/
  Parquet, cp1252 and mojibake, referential integrity, time-zone conversion incl. DST, failed job leaves no
  partial data and retry works, dataset deletion with confirmation and orphan cleanup.
- **Entities & graph** — resolution matches ground truth (2 strong, 1 ambiguous, conflict not strong, no
  false match), no duplicate candidates on re-run, merge/revert restores attributes/sources/relationships
  exactly, role checks on review, neighbourhood/components/centrality/communities/paths/PageRank
  (checked against NetworkX's reference implementation), snapshots and three export formats, unverified
  hypotheses hidden until verified with provenance preserved.
- **Search & documents** — parser, Boolean/phrase/prefix/field/numeric/date filters, history, saved
  queries, PDF/DOCX/EML/TXT processing, language, classification, entity candidates, duplicates,
  page-level evidence, similarity, entity↔document linking, grounded extractive answers with page citations,
  refusal without evidence.
- **Analytics, time, geo** — outliers match planted transactions with disclaimer, all analysis kinds,
  reproducibility (identical hash) and detection of changed inputs, timeline counts/clustering/windows/
  comparison, geospatial counts never invent coordinates, spatial join, radius, distance, clustering, bbox,
  time filters, annotations, invalid geometry.
- **Investigations, workflows, reports** — collaborator visibility, verbatim-excerpt enforcement, evidence
  revisions, finding state machine (no self-review, evidence required), workflow validation errors (cycles,
  ports, types), preview without side effects, confirmed run producing a lineage-linked dataset, failure
  rollback, permission for data-writing nodes, versioning; reports in five formats with manifests and
  hashes, Unicode in PDF, repeated table headers on long tables, XLSX/HTML structure.
- **Platform** — audit chain verification and tamper detection (triggers block UPDATE/DELETE; an edit after
  dropping the trigger is detected at the exact sequence), coverage of key audit actions, backup → change →
  restore with identical counts and working search/SQL/audit afterwards, encrypted backups (wrong
  passphrase, corruption, path traversal), persistence across a process restart, network guard blocks
  external connects and DNS while allowing loopback, configuration validation (7 unsafe cases), empty
  dashboards report zeros.
- **AI (mock local runtime)** — registry/health with checksum path rules, citation-enforced generation,
  untrusted-passage system prompt, SQL drafts validated/not executed, hypotheses stored unverified with
  quote verification, embeddings + semantic search, everything else works with AI disabled (503 for AI
  endpoints).

### End-to-end scenario (§24) — actual run

| # | Step | Outcome |
|---|---|---|
| 1 | Install | package importable, CLI available |
| 2 | Initial administrator | wrong token refused (403), real token consumed and file deleted |
| 3 | Workspace | project created (classification *confidential*) |
| 4 | Import synthetic data | 8 + 33 + 5 + 60 records |
| 5 | Map & validate | dry run reports 1 timestamp error, 2 coordinate errors, nothing written |
| 6 | Resolve & review | 3 candidates, the 2 expected strong matches; merge accepted |
| 7 | Explore graph | Northwind Harbor Logistics: 4 *works_for* edges; centrality computed |
| 8 | Inspect evidence | record captured as evidence; row hash and source-file SHA-256 match |
| 9 | Reproducible analysis | 2 outliers; reproduction hash identical |
| 10 | Report | PDF exported; downloaded bytes match manifest SHA-256 |
| 11 | Restart | new server process |
| 12 | Persistence & audit | counts identical; audit chain valid |
| — | Backup | created and verified |
| 13 | Disable network | Linux network namespace with loopback only; external connect → *Network is unreachable* |
| 14 | Repeat offline | login, new workspace, imports, resolution, merge, reproducible analysis, document assistant, PDF report, offline-check all passed |

## 2. Performance measurements

`scripts/benchmark.py --rows 100000 --people 5000` (synthetic data, SQLite, in-process, single run;
raw results in `benchmark-results.json`):

| Operation | Time |
|---|---|
| Import 5 000 people with entity mapping | 12.6 s |
| Import 100 000 transactions, plain (records + search index + Parquet) | 15.8 s (≈ 6 300 rows/s) |
| Import 100 000 transactions with 2 entity mappings, relationships, events and map points | 109.4 s (≈ 910 rows/s) |
| Full-text search over ~205 000 indexed rows (7 query shapes × 5) | p50 166 ms, p95 374 ms |
| SQL aggregate over 100 000 rows (DuckDB, incl. loading Parquet) | 0.50 s |
| Entity resolution over 5 499 person entities | 29.8 s |
| Describe / outliers on 100 000 rows | 0.51 s / 0.41 s |
| Graph overview (top 300 of 5 499 nodes, 99 767 edges) | 0.88 s |
| PageRank / Louvain communities / betweenness (k = 500 sample) | 6.1 s / 8.7 s / 46.5 s |
| Timeline query (2 000 events) / geo radius query | 0.20 s / 0.39 s |
| PDF report with a 2 000-row table | 2.9 s |
| Backup (623 MB database → 161 MB archive) / verify | 46.2 s / 18.8 s |
| Peak RSS of the whole benchmark process | 1.29 GB |

Improvements made because of these measurements: full import went from ≈ 350 rows/s (20 k-row run) to
≈ 900 rows/s after batching dependent inserts, deduplicating attribute provenance and adding an indexed
FTS rowid map; graph overview went from 6.6 s to 0.9 s by ranking degrees in SQL. A missing SciPy
dependency for PageRank was found and replaced.

Hardware guidance (extrapolated from these measurements, not a certification): 4 cores / 8 GB RAM handle projects of a
few hundred thousand records and ~10⁵ relationships comfortably; exact betweenness and Louvain on much
larger graphs become slow (minutes) — use filters or the sampled betweenness. Budget ~3 KB of database per
indexed record plus Parquet copies. Local AI adds whatever the chosen model needs (registry records RAM
requirements); no GPU is required for non-AI features.

## 3. Feature status

### Completed and tested
Identity & access (Argon2id, sessions, rate limiting, lockout, TOTP MFA, recovery tokens, global + project
roles, restricted datasets, sensitive-field redaction) · projects and membership · data source registry
(permitted sources) · ingestion of CSV/TSV/XLSX/JSON/JSONL/XML/SQLite/Parquet with inspection, mapping,
normalization, dry runs, cancel/retry, progress (SSE + polling) · 13 quality checks · catalog with
versions, lineage, access and retention metadata · ontology editing · entity resolution with evidence,
review and reversible merges · knowledge graph (filters, neighbourhoods, progressive loading, paths,
components, centrality, communities, snapshots, exports, assertion bases) · unified search with saved
queries and history retention · document intelligence (PDF/DOCX/TXT/MD/EML, language, keywords, entity
candidates, deduplication, similarity, page evidence) · grounded document assistant · timeline · offline
maps and spatial operations · analytics with reproducibility · sandboxed SQL · investigations with
evidence and findings workflow · visual workflows with real execution · reports (PDF/HTML/CSV/JSON/XLSX
+ manifest) · hash-chained audit with checkpoints · backup/verify/restore (incl. encrypted) · offline
verification and network guard · offline release bundle (Linux) · desktop bundle (Linux) · UI for all
modules · synthetic dataset with ground truth.

### Partial
| Area | What exists | What is missing |
|---|---|---|
| Local AI | registry, health/checksums, grounded QA, SQL drafts, document summaries, relationship hypotheses, embeddings/semantic search — tested against a **mock** Ollama-compatible runtime | not run against a real model here; AI-assisted natural-language exploration, schema mapping, quality explanations, investigation summaries and report drafting are not implemented (deterministic schema-mapping suggestions exist); reranking models can be registered but are unused |
| OCR | tesseract/pdftoppm path for image-only PDF pages, status reported per document | untested (engine not installed here); no OCR for standalone images |
| Language detection | stop-word heuristic for en/es/fr/de/it/pt/nl | other languages report "undetermined" |
| Saved views / tabs | route tabs, remembered panel sizes and filters per page, saved searches, graph snapshots with layout | no generic saved views for every module; tabs are page history, not independent workspaces |
| Resumable processing | failed/interrupted jobs retry from the start (atomic, idempotent) | no mid-file resume |
| Field-level permissions | sensitive-field flag with role-based redaction | no per-user/per-field grants |
| Model permissions | global `admin.models`; AI use per project role | no per-project model allow-lists |
| Workflow editor | typed nodes, validation, preview, runs, versions | complex parameters edited as JSON |
| Retention | policy recorded per dataset | no automatic expiry |
| Geospatial | points, polygons, bbox, radius, joins, clustering, heatmap | planar point-in-polygon; no line/polygon intersection operations; basemap is 1:110m |
| Account recovery | administrator-issued one-time tokens | no self-service recovery (deliberately, offline) |

### Deferred
Native Tauri/Electron shell (PyInstaller + chromeless browser used instead) · Windows `.exe`/MSI and macOS
builds (must be produced on those OSes) · dedicated graph database (not justified at measured scale) ·
optional external search engine and vector database · scheduled encrypted backups · project deletion UI ·
multi-process job workers.

### Implemented but untested
PostgreSQL deployment (migrations, tsvector search, connection) · PowerShell installer · Windows/macOS
desktop launcher behaviour · nginx/systemd LAN examples · OCR path.

## 4. Installation summary
See `installation.md`. Development: `pip install -e backend`, `npm ci && npm run build` in `frontend`,
`atlas serve`. Air-gapped: `scripts/build_release.sh` on a connected host of the same platform → copy bundle
→ `install.sh` (verifies SHA-256 sums, installs with `--no-index`) → `atlas offline-check` → `atlas serve`.
Desktop: `scripts/build_desktop.sh` → run `Project Atlas`.

## 5. Limitations and outstanding risks

1. **Host administrator trust** — anyone with full control of the machine can read the SQLite database and
   files (no at-rest encryption by Atlas) and could rewrite the audit log together with its checkpoint key.
   Use disk encryption, OS account separation and off-host checkpoint/backup copies.
2. **Process-local offline guard** — does not cover the browser, OS, local model runtime or tools such as
   tesseract; private-range connections are allowed. Air-gap assurance needs OS/network controls.
3. **PostgreSQL untested** — multi-user LAN deployments should be validated before production use.
4. **SQLite concurrency** — one writer at a time; long imports block other writes (reads continue).
   Suitable for single-user and small-team use; larger teams should use PostgreSQL once validated.
5. **In-memory rate limits/lockouts** reset on restart and are per process.
6. **Entity resolution is heuristic** — scores are similarity measures, not calibrated probabilities; the
   name-blocking strategy can miss matches whose names share no token (identifier blocking mitigates).
7. **Large-graph algorithms** run in memory; exact algorithms on >10⁵ edges take minutes.
8. **Sensitive-data protection depends on correct labelling** of sensitive fields at import or in the ontology.
9. **No independent penetration test** has been performed; security assurance rests on design review and
   the automated tests listed above.
10. **Third-party dependencies** (45 wheels) are pinned only by minimum version in `pyproject.toml`; release
    bundles freeze exact versions — rebuild and re-test bundles when updating.
11. The hosting Git repository is named `.palantir`; no project file, package, UI label or default uses
    that name or any other product's branding.
