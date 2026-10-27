# API reference (atlas-api)

Generated from the application by `scripts/generate_api_docs.py`; the machine-readable spec is
[`openapi.json`](openapi.json) and the interactive docs are served at `/api/docs`.

146 operations.

Authentication: `Authorization: Bearer <token>` from `POST /api/auth/login` (or `/api/auth/setup`).
Errors: `{"error": {"code", "message", "details"}}` with HTTP 400/401/403/404/409/422/429/503.
Project-scoped routes return 404 to non-members.

## administration

| Method | Path | Summary |
|---|---|---|
| GET | `/api/admin/audit` | List Audit |
| POST | `/api/admin/audit/checkpoint` | Checkpoint |
| GET | `/api/admin/audit/export` | Export Audit |
| POST | `/api/admin/audit/verify` | Verify Audit |
| GET | `/api/admin/backups` | Backups |
| POST | `/api/admin/backups` | Make Backup |
| POST | `/api/admin/backups/restore` | Preview (confirm=false) shows the manifest and verification; confirm=true performs the restore. |
| POST | `/api/admin/backups/verify` | Verify |
| GET | `/api/admin/users` | List Users |
| POST | `/api/admin/users` | Create User |
| GET | `/api/admin/users/directory` | Minimal user listing so project admins can add members. |
| PATCH | `/api/admin/users/{user_id}` | Patch User |
| POST | `/api/admin/users/{user_id}/reset-token` | Secure offline account recovery: an administrator issues a one-time, 1-hour token delivered out-of-band. |
| POST | `/api/admin/users/{user_id}/revoke-sessions` | Revoke All |

## ai

| Method | Path | Summary |
|---|---|---|
| POST | `/api/ai/models` | Register Model |
| PATCH | `/api/ai/models/{model_id}` | Toggle Model |
| POST | `/api/ai/models/{model_id}/check` | Check Model |
| GET | `/api/ai/status` | Ai Status |
| POST | `/api/projects/{project_id}/ai/documents/{document_id}/relationship-hypotheses` | Stores model suggestions as *unverified* relationships that reviewers must verify or reject. |
| POST | `/api/projects/{project_id}/ai/documents/{document_id}/summary` | Summarize |
| POST | `/api/projects/{project_id}/ai/embeddings` | Embed Docs |
| GET | `/api/projects/{project_id}/ai/semantic-search` | Semantic |
| POST | `/api/projects/{project_id}/ai/sql-draft` | Sql Draft |

## analytics

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects/{project_id}/analyses` | List Analyses |
| POST | `/api/projects/{project_id}/analyses` | Run Analysis |
| GET | `/api/projects/{project_id}/analyses/{run_id}` | Get Analysis |
| POST | `/api/projects/{project_id}/analyses/{run_id}/reproduce` | Reproduce |
| GET | `/api/projects/{project_id}/geo/clusters` | Geo Clusters |
| GET | `/api/projects/{project_id}/geo/distance` | Geo Distance |
| GET | `/api/projects/{project_id}/geo/features` | Geo Features |
| POST | `/api/projects/{project_id}/geo/features` | Geo Add |
| GET | `/api/projects/{project_id}/geo/join` | Geo Join |
| GET | `/api/projects/{project_id}/geo/layers` | Geo Layers |
| POST | `/api/projects/{project_id}/geo/layers` | Geo Import |
| GET | `/api/projects/{project_id}/geo/radius` | Geo Radius |
| POST | `/api/projects/{project_id}/sql` | Run Sql |
| GET | `/api/projects/{project_id}/sql/tables` | Sql Tables |
| GET | `/api/projects/{project_id}/timeline` | Timeline |
| GET | `/api/projects/{project_id}/timeline/compare` | Timeline Compare |

## auth

| Method | Path | Summary |
|---|---|---|
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Me |
| POST | `/api/auth/mfa/activate` | Mfa Activate |
| POST | `/api/auth/mfa/disable` | Mfa Disable |
| POST | `/api/auth/mfa/enroll` | Mfa Enroll |
| POST | `/api/auth/password` | Change Password |
| POST | `/api/auth/password-reset/redeem` | Account recovery: redeem a one-time token issued by a security/system administrator. |
| GET | `/api/auth/sessions` | My Sessions |
| DELETE | `/api/auth/sessions/{session_id}` | Revoke Session |
| POST | `/api/auth/setup` | Initial Setup |
| GET | `/api/auth/setup-status` | Setup Status |

## data

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects/{project_id}/datasets` | List Datasets |
| DELETE | `/api/projects/{project_id}/datasets/{dataset_id}` | Explicit deletion: removes records, derived events/geo features and search entries. |
| GET | `/api/projects/{project_id}/datasets/{dataset_id}` | Dataset Detail |
| PATCH | `/api/projects/{project_id}/datasets/{dataset_id}` | Patch Dataset |
| GET | `/api/projects/{project_id}/datasets/{dataset_id}/quality` | Dataset Quality |
| GET | `/api/projects/{project_id}/datasets/{dataset_id}/records` | Dataset Records |
| GET | `/api/projects/{project_id}/files` | List Files |
| POST | `/api/projects/{project_id}/files` | Upload File |
| POST | `/api/projects/{project_id}/ingest/commit` | Commit Import |
| POST | `/api/projects/{project_id}/ingest/inspect` | Inspect File |
| POST | `/api/projects/{project_id}/ingest/preview` | Dry run over the full file: validation, quality checks and transformed preview. Writes nothing. |
| GET | `/api/projects/{project_id}/records/{record_id}` | Record Detail |

## documents

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects/{project_id}/documents` | List Documents |
| POST | `/api/projects/{project_id}/documents` | Process |
| POST | `/api/projects/{project_id}/documents/ask` | Ask |
| DELETE | `/api/projects/{project_id}/documents/{document_id}` | Delete Document |
| GET | `/api/projects/{project_id}/documents/{document_id}` | Document Detail |
| GET | `/api/projects/{project_id}/documents/{document_id}/original` | Original |
| GET | `/api/projects/{project_id}/documents/{document_id}/pages/{page}` | Document Page |
| GET | `/api/projects/{project_id}/documents/{document_id}/similar` | Similar |

## entities

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects/{project_id}/entities` | List Entities |
| POST | `/api/projects/{project_id}/entities` | Create Entity |
| POST | `/api/projects/{project_id}/entities/merge` | Manual Merge |
| POST | `/api/projects/{project_id}/entities/resolve` | Start Resolution |
| GET | `/api/projects/{project_id}/entities/{entity_id}` | Entity Detail |
| GET | `/api/projects/{project_id}/graph` | Get Graph |
| POST | `/api/projects/{project_id}/graph/analyze` | Analyze Graph |
| POST | `/api/projects/{project_id}/graph/export` | Export Graph |
| GET | `/api/projects/{project_id}/graph/snapshots` | List Snapshots |
| POST | `/api/projects/{project_id}/graph/snapshots` | Create Snapshot |
| GET | `/api/projects/{project_id}/graph/snapshots/{snapshot_id}` | Get Snapshot |
| GET | `/api/projects/{project_id}/match-candidates` | List Candidates |
| POST | `/api/projects/{project_id}/match-candidates/{candidate_id}/review` | Review Candidate |
| GET | `/api/projects/{project_id}/merges` | List Merges |
| POST | `/api/projects/{project_id}/merges/{merge_id}/revert` | Revert |
| POST | `/api/projects/{project_id}/relationships` | Create Relationship |
| GET | `/api/projects/{project_id}/relationships/{rel_id}` | Relationship Detail |
| PATCH | `/api/projects/{project_id}/relationships/{rel_id}` | Reviewers verify (activate) or reject relationships, e.g. model-suggested hypotheses. |

## investigations

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects/{project_id}/investigations` | List Investigations |
| POST | `/api/projects/{project_id}/investigations` | Create Investigation |
| GET | `/api/projects/{project_id}/investigations/{inv_id}` | Get Investigation |
| PATCH | `/api/projects/{project_id}/investigations/{inv_id}` | Patch Investigation |
| PUT | `/api/projects/{project_id}/investigations/{inv_id}/collaborators/{user_id}` | Add Collaborator |
| POST | `/api/projects/{project_id}/investigations/{inv_id}/evidence` | Add Evidence |
| PATCH | `/api/projects/{project_id}/investigations/{inv_id}/evidence/{evidence_id}` | Edit Evidence |
| GET | `/api/projects/{project_id}/investigations/{inv_id}/evidence/{evidence_id}/revisions` | Evidence Revisions |
| POST | `/api/projects/{project_id}/investigations/{inv_id}/findings` | Add Finding |
| POST | `/api/projects/{project_id}/investigations/{inv_id}/findings/{finding_id}/evidence` | Link Evidence |
| POST | `/api/projects/{project_id}/investigations/{inv_id}/findings/{finding_id}/status` | Finding Status |
| POST | `/api/projects/{project_id}/investigations/{inv_id}/items` | Add Item |
| POST | `/api/projects/{project_id}/investigations/{inv_id}/notes` | Add Note |

## jobs

| Method | Path | Summary |
|---|---|---|
| GET | `/api/jobs` | List Jobs |
| GET | `/api/jobs/{job_id}` | Get Job |
| POST | `/api/jobs/{job_id}/cancel` | Cancel Job |
| GET | `/api/jobs/{job_id}/events` | Server-sent events stream of job progress until the job finishes. |
| POST | `/api/jobs/{job_id}/retry` | Retry Job |

## other

| Method | Path | Summary |
|---|---|---|
| GET | `/api/health` | Health |

## projects

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects` | List Projects |
| POST | `/api/projects` | Create Project |
| GET | `/api/projects/{project_id}` | Get Project |
| GET | `/api/projects/{project_id}/members` | List Members |
| PUT | `/api/projects/{project_id}/members` | Upsert Member |
| DELETE | `/api/projects/{project_id}/members/{user_id}` | Remove Member |
| GET | `/api/projects/{project_id}/ontology` | Get Ontology |
| PUT | `/api/projects/{project_id}/ontology/entity-types` | Upsert Entity Type |
| PUT | `/api/projects/{project_id}/ontology/relationship-types` | Upsert Relationship Type |
| GET | `/api/projects/{project_id}/overview` | Locally computed statistics for the home dashboard (all zeros when empty). |
| GET | `/api/projects/{project_id}/sources` | List Sources |
| POST | `/api/projects/{project_id}/sources` | Create Source |
| PATCH | `/api/projects/{project_id}/sources/{source_id}` | Set Source Permitted |

## reports

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects/{project_id}/reports` | List Reports |
| POST | `/api/projects/{project_id}/reports` | Create Report |
| GET | `/api/projects/{project_id}/reports/section-types` | Section Types |
| GET | `/api/projects/{project_id}/reports/{report_id}` | Get Report |
| PUT | `/api/projects/{project_id}/reports/{report_id}` | Update Report |
| POST | `/api/projects/{project_id}/reports/{report_id}/export` | Export |
| GET | `/api/projects/{project_id}/reports/{report_id}/exports/{export_id}` | Download |
| POST | `/api/projects/{project_id}/reports/{report_id}/preview` | Preview |

## search

| Method | Path | Summary |
|---|---|---|
| GET | `/api/search` | Run Search |
| DELETE | `/api/search/history` | Clear History |
| GET | `/api/search/history` | History |
| GET | `/api/search/saved` | List Saved |
| POST | `/api/search/saved` | Save Query |
| DELETE | `/api/search/saved/{saved_id}` | Delete Saved |

## system

| Method | Path | Summary |
|---|---|---|
| GET | `/api/system/offline-check` | Verification mode: reports the configuration and runtime evidence relevant to offline operation. |
| GET | `/api/system/status` | Status |

## workflows

| Method | Path | Summary |
|---|---|---|
| GET | `/api/projects/{project_id}/workflows` | List Workflows |
| POST | `/api/projects/{project_id}/workflows` | Create |
| GET | `/api/projects/{project_id}/workflows/catalog` | Node Catalog |
| POST | `/api/projects/{project_id}/workflows/validate` | Validate |
| GET | `/api/projects/{project_id}/workflows/{workflow_id}` | Get |
| PUT | `/api/projects/{project_id}/workflows/{workflow_id}` | Save Version |
| POST | `/api/projects/{project_id}/workflows/{workflow_id}/preview` | Execute on at most 200 rows per input; side-effecting nodes are skipped; nothing is persisted. |
| POST | `/api/projects/{project_id}/workflows/{workflow_id}/runs` | Run |
| GET | `/api/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}` | Get Run |
