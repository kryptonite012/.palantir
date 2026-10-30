# Data model

Schema source of truth: `backend/project_atlas/database/models.py`; migrations:
`backend/project_atlas/database/migrations/versions/` (Alembic, applied automatically at startup).
Primary keys are stable prefixed UUIDs (`prj_…`, `dst_…`, `rec_…`, `ent_…`); the audit log uses an
integer sequence so the hash chain has a total order. JSON columns hold flexible payloads.

## Tables

| Area | Table | Purpose / key columns |
|---|---|---|
| Identity | `users` | username (unique), Argon2 hash, `global_role`, MFA secret/flag, lockout counters |
| | `sessions` | SHA-256 of token, expiry, revocation |
| | `password_reset_tokens` | hashed one-time recovery tokens, issuer, expiry, used_at |
| Projects | `projects`, `project_members` | workspace + role per user (unique per project) |
| | `settings` | key/value platform settings |
| Data | `data_sources` | permitted import sources per project |
| | `files` | uploaded originals: stored path (relative), SHA-256, size, detected format |
| | `datasets` | name (unique per project), owner, `access_policy`, `retention_policy`, current version, synthetic flag |
| | `dataset_versions` | immutable versions: schema, import config (mapping), record count, quality summary, ingestion report, content SHA-256, origin (`import`/`workflow`), parent version |
| | `records` | `raw` (original source values) and `normalized` (mapped + typed) JSON, row index, row hash |
| | `quality_issues` | row, field, check, severity, message, value |
| | `jobs` | background jobs: kind, status, progress, params, result, error, attempts, cancel flag |
| Ontology | `entity_types` | fields (type, identifier, sensitive, required, pattern) + schema version |
| | `relationship_types` | directed flag, allowed source/target types |
| Entities | `entities` | type, display name, `identity_key` (deterministic id match), attributes `{field: [{value, normalized, record_id, dataset_version_id}]}`, status (`active`/`merged`), `merged_into_id` |
| | `entity_sources` | entity ↔ source record links (provenance) |
| | `relationships` | source/target entity, type, `assertion` (`observed`/`inferred`/`model_suggested`/`manual`), status (`active`/`unverified`/`rejected`), confidence (null unless measured), evidence JSON, record, valid_from/to, created_by |
| | `match_candidates` | entity pair, score, band, evidence (features, matching/conflicting/not-compared fields, sources), algorithm version, review status/note |
| | `merge_history` | survivor, merged entity, snapshot for reversal, performed/reverted by/at |
| | `graph_snapshots` | node and edge ids, layout, filters |
| Documents | `documents` | file, title, media type, language (+confidence), page count, SHA-256, classification, keywords, entity candidates, duplicate/near-duplicate links, OCR status, metadata |
| | `document_chunks` | page (or section/message), chunk index, text, char offset |
| | `embeddings` | chunk, model, float32 vector (optional AI) |
| Time & space | `events` | event_time (UTC), end_time, source time text & zone, record_created_time, ingested_at, modified_at, entity, record, coordinates |
| | `geo_features` | layer, kind (`data`/`annotation`/`layer`), GeoJSON geometry, bbox columns, feature time, record/entity links |
| Search | `search_index` | FTS5 virtual table (SQLite) / tsvector table (PostgreSQL) with doc type, ref id, project, parent id, access tag |
| | `saved_queries`, `query_history` | per user and project; history retention 90 days |
| Analysis | `analysis_runs` | kind, params, inputs (dataset versions + hashes / graph state hash), algorithm & software version, result, result SHA-256, duration, reproduced_from |
| Investigations | `investigations`, `investigation_collaborators`, `investigation_items`, `notes` | scope, status, classification; linked items by type/id |
| | `evidence`, `evidence_revisions` | source type/ref, verbatim excerpt, location (page/row), classification, provenance, revision history |
| | `findings`, `finding_evidence` | statement, status state machine, basis, history; supporting/contradicting evidence links |
| Workflows | `workflows`, `workflow_versions`, `workflow_runs` | versioned definitions; runs with node results and logs |
| Reports | `reports`, `report_exports` | definition (sections); exports with path, SHA-256, size, manifest |
| Platform | `audit_events` | seq, event id, ts, actor, action, resource, project, outcome, details, prev_hash, hash (append-only triggers) |
| | `model_registry` | name, version, kind, runtime model name, file path, SHA-256, quantization, license, RAM, health |
| | `backup_manifests` | archive filename, SHA-256, size, encrypted, per-table counts, verified_at |

Indexes cover foreign keys used in filters, `(project_id, entity_type)`, `(project_id, event_time)`,
`(dataset_version_id, row_index)`, identity keys and audit actions.

## Deletion policy

* Records, versions, quality issues, derived events/geo features, observed relationships and search
  entries are deleted only through the explicit *Delete dataset* action (requires `dataset.delete` and
  typing the dataset name). Entities that lose all source records are removed with it; entities still
  supported by other datasets remain.
* Deleting a project cascades to everything in it (`ON DELETE CASCADE`); there is no UI action for it in
  this release.
* Documents are deleted with their chunks and embeddings; evidence captured from them is kept (evidence is
  independent from sources).
* Merges are never destructive: merged entities stay as `status=merged` and can be restored.
* Audit events are never deleted or updated.
* `retention_policy` is recorded per dataset for governance; **automatic expiry is not implemented**
  (deferred) — retention actions are manual.

## Provenance and lineage

Source file (SHA-256) → dataset version (mapping, pipeline version, content hash) → records (raw +
normalized, row hash) → entities (`entity_sources`, attribute-level record ids) → relationships (evidence
record ids) → analyses (dataset version ids + hashes) → reports (manifest). Workflow-materialized
versions record their parent version and workflow run.
