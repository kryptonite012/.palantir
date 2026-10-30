# Security

## Threat model (summary)

Atlas protects analytical data and evidence on a local workstation or private LAN against:
unauthorized users and roles, cross-project access, privilege escalation, injection through queries,
uploads and imported content (including prompt injection), accidental external data egress, and
undetected tampering with the audit trail. It does **not** protect against an attacker with full
administrative control of the host (see *Limitations*).

## Authentication

| Control | Implementation |
|---|---|
| Password hashing | Argon2id (`argon2-cffi` defaults: t=3, m=64 MiB, p=4); automatic rehash on login when parameters change |
| Password policy | ≥ 12 characters, 3 of 4 character classes, not containing the username, small common-password list |
| Initial admin | No default account. One-time random setup token in the workspace (0600), deleted after use; or `atlas create-admin` on the host |
| Sessions | 256-bit random bearer tokens; only SHA-256 stored; sliding expiry (`ATLAS_SESSION_TTL_MINUTES`, default 8 h); revocation per session, all sessions on password change/reset/disable |
| Brute force | 10 login attempts / minute per IP and per username; account lockout for 15 min after 5 failures; constant-work verification for unknown users; identical error responses |
| MFA | Optional TOTP (RFC 6238, SHA-1, 30 s, ±1 step), enrolled per user |
| Recovery | Security/system admins issue one-time 1-hour reset tokens (stored hashed) delivered out of band; redeeming revokes all sessions |
| API rate limit | 600 requests / minute per user (in-process) |

The UI keeps the token in `sessionStorage` (cleared when the window closes) and sends it as a
`Authorization: Bearer` header — no cookies, so CSRF does not apply. XSS exposure is reduced by a
strict CSP (`script-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`),
React's escaping, and serving untrusted originals only as attachments.

## Authorization

Two independent layers, enforced in the backend for every request:

* **Global roles** — *System Administrator* (users, projects, backups/restore, settings, models, audit) and
  *Security Administrator* (user security operations, session revocation, audit read/verify).
  System administrators **do not** automatically see project data.
* **Project roles** — *Project Administrator, Data Engineer, Analyst, Reviewer, Read-Only*, each mapping
  to a permission set in `security/rbac.py` (e.g. `dataset.write`, `entity.review`, `query.sql`,
  `report.export`, `sensitive.read`, `sensitive.export`, `workflow.write_data`).

Resource-level rules:

| Resource | Rule |
|---|---|
| Projects | Non-members receive 404 for every project URL (existence not revealed); attempts are audited as denied |
| Datasets | `access_policy=restricted` visible only with `dataset.read_restricted` (Data Engineer, Project Admin) — applied to catalog, records, search, SQL, analytics, timeline, geo, workflows, reports |
| Fields | Ontology/mapping `sensitive` fields are redacted (`[restricted]`) in records, entity attributes, match evidence, quality values, analytics frames and SQL tables without `sensitive.read`; excluded from the search index entirely; redacted in exports without `sensitive.export` (recorded in the report manifest) |
| Investigations | Visible to owner, collaborators and project admins only; reviewers cannot review their own findings; confirmation requires supporting evidence |
| Queries | SQL: read-only validation + sandbox (below); search: user syntax is parsed and re-emitted, never passed raw |
| Workflows | Each node declares a permission; side-effecting nodes need `confirm=true`; data-writing nodes need `workflow.write_data` |
| Models | Registration/health/toggle need `admin.models`; model files must live under `ATLAS_MODEL_DIR` |
| Exports | `report.export`; every export and download is audited with format, hash and redactions |

## Input handling

* **Uploads** — extension allow-list, magic-byte checks (PDF, ZIP-based Office, SQLite, Parquet), NUL-byte
  rejection for text formats, size limit (`ATLAS_MAX_UPLOAD_MB`), filename sanitization (no path
  components), storage under random ids inside the workspace with 0600 permissions; all stored paths are
  resolved and checked to stay inside the workspace.
* **XML** — DTD/ENTITY declarations rejected (entity-expansion attacks).
* **SQLite sources** — opened read-only (`mode=ro`); table names validated against the catalog.
* **Spreadsheet exports** — values starting with `= + - @` are prefixed with `'` (formula injection).
* **Templates** — event titles use `{field}` substitution only (no format-string attribute access).
* **SQL console** — single statement; must start with `SELECT`/`WITH`; deny-list of statements and
  file/extension/config functions; then defence in depth: permitted tables are loaded into an in-memory
  DuckDB from Arrow, `enable_external_access=false` and `lock_configuration=true` are set **before** the
  user query runs, plus memory/thread limits, row limit and a wall-clock interrupt. A test proves file
  access fails even when the validator is bypassed.
* **ORM** — all database access is parameterized through SQLAlchemy; dynamic SQL fragments use only
  internally generated placeholders.

## Prompt injection and AI safety

Imported documents are untrusted. The assistant wraps passages in delimited `<passage>` blocks, the
system prompt forbids following instructions inside them, model output is plain text with no tool or
action capability, answers without valid citations to retrieved passages are withheld, passages
resembling injected instructions are flagged to the user, and documents with such patterns are marked at
ingestion. Generated SQL is validated and never executed automatically. Model-suggested relationships are
stored as `model_suggested` / `unverified` and hidden from the default graph until a reviewer verifies
them; verification keeps the original provenance.

## Secrets

No credentials, keys or production databases are committed. The setup token and audit checkpoint key are
generated at runtime with 0600 permissions. Logs and audit details scrub password/token/secret/passphrase
fields. Backup passphrases are never stored; encrypted backups use scrypt (N=2¹⁵, r=8, p=1) + AES-256-GCM.

## Audit trail

Append-only `audit_events` (database triggers reject UPDATE/DELETE) with a SHA-256 hash chain over
canonical JSON; HMAC-signed checkpoints of the chain head in `audit-checkpoints.jsonl`; verification
endpoint reports the first broken sequence number. Audited: authentication (success/denied), setup,
permission and membership changes, uploads, imports, dataset updates/deletes, entity merges/reverts and
match decisions, relationship changes, analyses and SQL (including denied queries), workflow runs,
document assistant use, exports/downloads, backups/restores, AI operations, project access denials.

## Network exposure

Loopback by default; LAN requires `ATLAS_ALLOW_LAN=true` and, in production, TLS
(`ATLAS_TLS_TERMINATED=true` behind a reverse proxy, HSTS emitted). Security headers on every response:
CSP, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP,
`Permissions-Policy`, and `Cache-Control: no-store` for API responses.

## Limitations

* A user with administrator/root access to the machine can read the SQLite database and workspace files,
  change code, or rewrite the audit log **and** its checkpoint key. Mitigations: full-disk encryption,
  OS account separation, exporting audit checkpoints to separate media, encrypted backups stored offline.
* Data at rest is not encrypted by Atlas itself (only backups); rely on OS/disk encryption.
* Rate limiting and lockout state are in process memory (reset on restart; per process).
* The network guard is process-local (see offline-operation.md).
* Sensitive-field protection depends on fields being marked sensitive in the mapping or ontology.
* Security testing was automated (see tests) but no independent penetration test has been performed.
