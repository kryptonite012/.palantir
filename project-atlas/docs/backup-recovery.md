# Backup, restore and disaster recovery

## What a backup contains

`atlas-backup-<UTC timestamp>.tar.gz[.enc]` in `ATLAS_BACKUP_DIR`:

| Member | Content |
|---|---|
| `manifest.json` | format version, software version, schema revision, **row counts per table**, SHA-256 of every member, encryption flag |
| `database.sqlite3` | consistent snapshot taken with SQLite's online-backup API while Atlas keeps running (integrity-checked before archiving) |
| `workspace/files/…` | uploaded originals |
| `workspace/derived/…` | Parquet copies of dataset versions |
| `workspace/exports/…` | report and workflow exports with manifests |
| `workspace/audit-checkpoints.jsonl` | signed audit checkpoints |
| `workspace/audit-checkpoint.key` | checkpoint HMAC key — **encrypted backups only** |

Encrypted backups (passphrase ≥ 12 characters) use scrypt (N=2¹⁵, r=8, p=1) to derive an AES-256-GCM key;
the whole archive is authenticated, so tampering or a wrong passphrase is detected. Passphrases are never
stored — losing one means losing that backup. Archives are written with mode 0600.

## Creating backups

* UI: *Administration → Backup & restore → Back up now* (optional passphrase).
* CLI: `atlas backup` or `atlas backup --encrypt`.
* API: `POST /api/admin/backups {"passphrase": …}` (system administrators).
* Scheduled: `ATLAS_BACKUP_INTERVAL_HOURS=24` runs unencrypted backups in the background; the newest
  `ATLAS_BACKUP_RETENTION` (default 10) scheduled archives are kept, older ones deleted. Manual backups are
  never deleted automatically. Copy archives to separate, preferably offline, media.

## Verifying

`atlas verify-backup <file>` / *Verify* in the UI / `POST /api/admin/backups/verify` checks: archive
readability (and decryption), safe member paths, SHA-256 of every member against the manifest, missing
members, `PRAGMA integrity_check` on the database snapshot and per-table row counts. A successful check is
recorded (`verified_at`).

## Restoring

1. *Restore preview* (or `POST /api/admin/backups/restore` with `confirm=false`) runs the full verification
   and shows the manifest (counts, schema revision, creation time).
2. Ensure no jobs are running (restore refuses otherwise).
3. *Restore* (`confirm=true`): the current database and workspace directories are **moved aside** to
   `<ATLAS_STORAGE_DIR>/.pre-restore-<timestamp>/` (nothing is deleted), the archive is extracted, the
   schema is migrated forward if the backup is older, and live row counts are compared with the manifest.
   The restore itself is then appended to the (restored) audit chain.
4. Sign in again if needed; verify via *Audit Center → Verify chain* and spot-check datasets.

Tested automatically (`tests/test_platform.py::test_backup_verify_restore`): backup → delete a dataset →
restore → counts identical, search and SQL over restored Parquet work, audit chain valid. Corruption and
wrong-passphrase detection are tested too.

## Disaster-recovery procedure

| Scenario | Procedure |
|---|---|
| Workstation loss | Install Atlas on the replacement (offline bundle), copy the latest archive into `ATLAS_BACKUP_DIR`, start Atlas once (creates an empty workspace), create a temporary admin, restore the archive; the backup's users replace the temporary one. |
| Corrupted database | Stop Atlas; keep the damaged files; restore the most recent verified backup; re-import data received since then (source files are hashed, so duplicates are recognisable). |
| Bad import / mistaken deletion | Restore into a **separate** workspace (`ATLAS_STORAGE_DIR` elsewhere) to recover specific data, or restore in place if losing later changes is acceptable. |
| Suspected audit tampering | `audit verify` reports the first broken sequence; compare with externally stored checkpoints and backups. |

## PostgreSQL deployments

The automated backup covers SQLite. For PostgreSQL, schedule `pg_dump -Fc atlas_prod` together with a copy
of `atlas-workspace/` (files, derived, exports, checkpoints) taken at the same time, and restore with
`pg_restore` + the directory copy. This path is documented but **not automated or tested** in this release.

## Recovery objectives

RPO equals the backup interval (scheduled) or the time since the last manual backup. Measured backup and
verification times are in `docs/engineering-report.md`; on the test machine a 42 000-record workspace
backed up in ~8.6 s (31 MB archive) and verified in ~3 s.
