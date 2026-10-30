# Offline operation

Project Atlas needs no internet access at install time (from a release bundle) or at run time.

## What Atlas does to stay offline

| Mechanism | Detail |
|---|---|
| No external assets | The UI bundle contains all JS/CSS/fonts; the map basemap is a bundled Natural Earth GeoJSON (`/map/ne_110m_countries.geojson`); no tile, glyph or font URLs are referenced; CSP is `connect-src 'self'`. |
| No telemetry | None is implemented. `ATLAS_TELEMETRY_ENABLED=true` is rejected at startup. |
| Network guard | With `ATLAS_OFFLINE_MODE=true` (default) the atlas-api process patches socket `connect`/`getaddrinfo`: only loopback and RFC 1918 / ULA / link-local addresses are reachable; DNS lookups of other names and all other connections raise `OfflineViolation` and are counted. |
| Local AI only | `ATLAS_AI_BASE_URL` must resolve to a loopback/private literal address or `localhost` in offline mode; there is no fallback to any hosted API. |
| Loopback binding | Default `ATLAS_HOST=127.0.0.1`; LAN binding requires an explicit opt-in. |

## Verification mode

* UI: *Administration → System & offline → Run checks*
* API: `GET /api/system/offline-check`
* CLI: `atlas offline-check` (exit code 0 when offline mode is on and the live probe is blocked)

Checks: offline mode, telemetry, bind address, AI endpoint locality, guard installed, number of
blocked external attempts since start (with the most recent targets), a live probe (a real
`connect()` to TEST-NET-1 that must be blocked by the guard), presence of all runtime
dependencies, and OCR availability (optional).

## Demonstrated without network

`scripts/acceptance_scenario.py` re-runs the essential workflow (start, login, new workspace,
import, entity resolution, review/merge, reproducible analysis, document processing and assistant,
PDF report, offline-check) inside a Linux network namespace created with `unshare -rn`, where only
loopback exists and external connections fail with *Network is unreachable*. The release bundle
install was verified the same way. Results: `docs/acceptance-results.json`.

## Limitations — read before claiming air-gap compliance

* The guard covers **only the atlas-api Python process**. It does not control the browser, the OS,
  other software, a local AI runtime, or child processes such as `tesseract`.
* Private-range connections are allowed (for LAN databases and model runtimes). Disable them by network
  policy if your environment requires loopback-only.
* Air-gap assurance requires OS/network controls (firewall rules, removed interfaces, physical
  isolation) and your organization's verification procedure. Atlas's checks are supporting evidence, not
  certification.
* The packaged desktop app launches Edge/Chrome/Chromium with background networking disabled flags, but
  browser behaviour is outside Atlas's control; use enterprise browser policies on managed machines.

## Provisioning updates offline

1. On a connected build host, build a new bundle (`scripts/build_release.sh`) and record its `SHA256SUMS`.
2. Transfer by your controlled media process; verify checksums on arrival (`install.sh` does this).
3. Back up (`atlas backup --encrypt`), install the new version into a new directory, point it at the same
   `ATLAS_STORAGE_DIR`, and start it — migrations upgrade the schema automatically.

## Higher-detail offline maps

Place additional GeoJSON (or locally served vector tiles) under the UI's `map/` directory and extend
`frontend/src/features/maps/basemap.ts`. Do not reference remote tile servers.
