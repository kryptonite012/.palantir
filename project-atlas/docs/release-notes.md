# Release notes

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
