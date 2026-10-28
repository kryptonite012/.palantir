# Release notes

## 0.2.0 — usability and assistants (2026-10-28)

### New
* **One-click demo workspace** — *Projects → Create demo workspace* builds the synthetic Northwind Harbor
  project (4 datasets, 5 documents, district polygons, match candidates) through the normal audited
  pipelines, with live progress. The generator now ships inside the package (`project_atlas.demo`).
* **Command palette** (`Ctrl/⌘ K`) — jump to pages, datasets, documents, entities and saved views, or run
  actions (import, new investigation, save current view, switch theme, offline check).
* **Saved views** — save any page with its filters (`Ctrl K → Save current view…`); views are per user.
* **Entity watchlists and notifications** — watch an entity and get an in-app alert when an import brings
  new source records about it; job completions/failures and retention notices also arrive as notifications
  (top bar *Alerts*, plus toasts with an *Open* link).
* **Home dashboard** — events over time, entities by type, most-connected entities, data quality by check,
  a recent-activity feed (no audit details exposed), your watchlist and running jobs.
* **Explain connection** — select two graph nodes to see the shortest paths with every hop's
  relationships, their basis and a redacted sample of the source evidence.
* **Quality explanations** — every quality check is explained (meaning, likely causes, what to do) without
  AI; with a local model, an optional prioritised summary.
* **Local-AI assistants** (optional, citation/validation enforced): *Ask your data* (model drafts SQL →
  you review → you run it in the sandbox → the model describes the result table), schema-mapping suggestions
  in the import wizard, investigation summaries citing evidence `[E#]` (invalid citations flagged), and report
  executive-summary drafts citing reviewed facts `[F#]` that you insert explicitly.
* **Retention enforcement** — *Administration → Retention* previews and applies policies: superseded
  versions past 1y/3y/7y are purged (tombstones keep lineage); expired current versions notify owners;
  optional periodic sweeps (`ATLAS_RETENTION_ENFORCE_HOURS`).
* **Encrypted scheduled backups** via `ATLAS_BACKUP_PASSPHRASE_FILE` (file must be mode 600).
* **Project lifecycle** — archive/unarchive (project admins) and permanent delete with typed confirmation
  (system administrators who administer the project).
* In-app dialogs and toasts replace browser `alert/prompt/confirm`; merges offer *Undo* from the toast.

### Changed
* Schema migration `0004` (saved views, watches, notifications).
* Retention policy values are validated (`indefinite`, `until_case_closed`, `1y`, `3y`, `7y`).
* Backend tests: 111 (from 97); frontend unit tests: 11; UI end-to-end test covers the new features.


## 0.1.0 — first release (2026-10-27)

First complete vertical release of PROJECT ATLAS: an offline-first intelligence and data operations
platform covering ingestion through auditable reporting. See `engineering-report.md` for test results,
measurements and the full status matrix.

### Highlights
* atlas-api (FastAPI modular monolith) with 146 API operations, SQLite + Alembic migrations (0001–0003).
* React analytical workstation UI with all 16 navigation modules, light/dark themes, tabs, resizable
  panels, saved searches and keyboard shortcuts.
* Ingestion of CSV, TSV, XLSX, JSON, JSONL, XML, SQLite and Parquet with dry runs and 13 quality checks;
  documents from PDF, DOCX, TXT, Markdown and EML.
* Explainable entity resolution with review and reversible merges; knowledge graph with typed assertion
  bases and algorithms; timeline; offline maps; reproducible analytics; sandboxed SQL.
* Optional local AI (Ollama-compatible) with grounding, citation enforcement and unverified hypotheses.
* Investigations with evidence revisions and a reviewed findings workflow; versioned visual workflows;
  PDF/HTML/CSV/JSON/XLSX reports with manifests.
* Hash-chained audit log, encrypted backups with verification and restore, outbound network guard and
  offline verification report.
* Offline release bundle (wheelhouse + installers + checksums) and a PyInstaller desktop app (Linux build
  verified; Windows/macOS builds must be produced on those platforms).
* Synthetic "Northwind Harbor" demonstration dataset with documented ground truth.

### Changes made during release validation
* Import throughput roughly doubled: dependent rows are batch-inserted after their source records,
  entity attribute provenance is deduplicated per value (count + sampled record ids, full provenance in
  `entity_sources`), and FTS deletes use an indexed rowid map (migration 0003).
* PageRank no longer depends on SciPy (dependency-free power iteration, verified against NetworkX's
  reference implementation).
* Graph overview computes node degrees in SQL instead of materializing the whole graph.
* Administrators can reset a user's MFA (lost authenticator recovery).
* Offline-mode address checks now use explicit RFC 1918 / ULA / link-local ranges (documentation ranges
  such as TEST-NET are treated as external).

### Known limitations
See *Limitations and outstanding risks* in `engineering-report.md`. In short: PostgreSQL support is
untested preview; OCR requires external tesseract; automatic retention expiry, a native Tauri/Electron
shell and Windows/macOS packaged builds are deferred; local AI paths are tested against a mock runtime
only.
