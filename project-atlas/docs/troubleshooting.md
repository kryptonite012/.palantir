# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Startup fails with `ConfigError` | A setting is invalid or unsafe, e.g. non-loopback `ATLAS_HOST` without `ATLAS_ALLOW_LAN=true`, LAN production without `ATLAS_TLS_TERMINATED=true`, `ATLAS_TELEMETRY_ENABLED=true`, a non-local `ATLAS_AI_BASE_URL` in offline mode. The message names the variable. |
| "Invalid setup token" | Use the current contents of `<ATLAS_STORAGE_DIR>/setup-token.txt`; it is regenerated only while no users exist. Or run `atlas create-admin <name>` on the host. |
| Cannot sign in after several attempts | Lockout for 15 minutes after 5 failures, or rate limit (10/min). An administrator can issue a reset token (*Administration → Users*). |
| Lost MFA device | A security or system administrator uses *Administration → Users → Reset MFA* (audited; revokes the user's sessions). The user signs in with the password and re-enrols. |
| Project "not found" | You are not a member; Atlas does not reveal whether it exists. Ask a project administrator. |
| Dataset missing from catalog/search | It is *restricted* and your role lacks restricted access. |
| Values show `[restricted]` | The field is marked sensitive; requires *Project Administrator* (`sensitive.read`). |
| Upload rejected | Unsupported extension, content not matching the extension, binary data in a text format, file larger than `ATLAS_MAX_UPLOAD_MB`, or an XML file with a DTD. |
| Garbled characters | Re-inspect with an encoding override (cp1252/latin-1); the `encoding` quality check flags mojibake. |
| Import job failed | Open *Jobs* for the error; nothing was written (single transaction). Fix the mapping and *Retry*. Jobs interrupted by a restart are marked failed and can be retried. |
| PDF pages without text | Image-only pages need OCR: install `tesseract` and `pdftoppm`; the document shows `ocr_required_unavailable` otherwise. |
| SQL "Disallowed keyword" | Only single read-only `SELECT`/`WITH` statements are allowed; file, extension and settings functions are blocked. |
| SQL "time limit" / truncated | Increase `ATLAS_QUERY_TIMEOUT_SECONDS` / `ATLAS_QUERY_ROW_LIMIT` or aggregate. |
| Graph shows "showing N of M nodes" | Increase *Node limit* (max `ATLAS_GRAPH_NODE_LIMIT`) or focus on an entity. |
| Map is blank or very coarse | The bundled basemap is Natural Earth 1:110m (coarse at city scale). Data points still render; add local higher-detail GeoJSON (see offline-operation.md). |
| AI shows "off" | AI is optional. Set `ATLAS_AI_ENABLED=true` and `ATLAS_AI_BASE_URL` to the local runtime, register models and run *Check*. |
| `offline-check` reports blocked attempts | Some code in the Atlas process tried to reach a non-local address; the targets are listed. Report it — nothing should do this. |
| Restore refused | Jobs are running, or the archive failed verification (hash mismatch, wrong passphrase). |
| "database is locked" | Another process holds the SQLite file (e.g. a second Atlas instance on the same workspace). Run one instance per workspace; use PostgreSQL for multi-user servers. |
| Desktop app opens the default browser instead of a window | No Edge/Chrome/Chromium found; install one or use the browser tab. |

Logs: atlas-api logs to stdout/stderr (`ATLAS_LOG_LEVEL`). Secrets are never logged; audit details scrub
password/token fields.
