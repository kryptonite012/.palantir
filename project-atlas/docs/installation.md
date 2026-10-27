# Installation

Project Atlas runs on Python 3.11+ (tested on 3.13, Linux x86-64). The UI is prebuilt into release
artifacts; Node.js is needed only to build from source.

## 1. Standalone desktop

### Packaged app (no Python needed on the target)
On a build machine of the **same OS**: `pip install pyinstaller && scripts/build_desktop.sh`.
Copy `release/desktop/Project Atlas/` (or the `.tar.gz`) to the workstation and run `Project Atlas`
(`Project Atlas.exe` on Windows). It:

* stores data in `%LOCALAPPDATA%\Project Atlas` (Windows), `~/Library/Application Support/Project Atlas`
  (macOS) or `~/.local/share/project-atlas` (Linux);
* starts atlas-api on a random loopback port with offline mode on;
* opens a chromeless Edge/Chrome/Chromium window (falls back to the default browser);
* prints the location of the one-time setup token on first run.

Tested: Linux x86-64 bundle built and started inside a network namespace without external
connectivity (see engineering report). **Windows and macOS bundles were not built in this
environment** — the spec and launcher are cross-platform but untested there.

### From the Python package
```bash
pip install project-atlas            # or: pip install --no-index --find-links wheelhouse project-atlas
atlas-desktop                        # same behaviour as the packaged app
```

## 2. Air-gapped workstation (offline bundle)

On a **connected** build machine with the same OS/architecture/Python minor version as the target:
```bash
scripts/build_release.sh             # → release/project-atlas-<ver>-<platform>-py<XY>.tar.gz
```
The bundle contains the project wheel (UI included), every dependency wheel, sample data, docs,
installers and `SHA256SUMS`. Transfer it through your controlled media process, then on the target:

```bash
tar xzf project-atlas-0.1.0-linux_x86_64-py313.tar.gz
cd project-atlas-0.1.0-linux_x86_64-py313
./install.sh /opt/project-atlas      # verifies SHA256SUMS, creates venv, installs with --no-index
/opt/project-atlas/atlas offline-check
/opt/project-atlas/atlas serve       # http://127.0.0.1:8000
```
Windows: build the bundle on Windows (the wheels are platform-specific), then
`powershell -ExecutionPolicy Bypass -File install.ps1 -Dest "C:\Project Atlas"` and run `atlas.cmd serve`.

Verified in this environment: the Linux bundle installed and served the UI from inside an isolated
network namespace (no route to the internet). The PowerShell installer is untested.

Optional components to provision separately on air-gapped machines:
* **OCR**: `tesseract` and `pdftoppm` (poppler) on `PATH` enable OCR of image-only PDF pages.
* **Local AI**: an Ollama (or compatible) runtime with model files copied in; register the models under
  *Administration → AI models*, with SHA-256 checksums for integrity checking.

## 3. Private LAN server

1. Install as in §2 (or `pip install project-atlas[postgres]` where a package mirror exists).
2. Create a PostgreSQL database (`atlas_prod`) and set
   `ATLAS_DATABASE_URL=postgresql+psycopg://atlas:<secret>@db.internal/atlas_prod`.
3. Keep atlas-api on loopback and put a TLS-terminating reverse proxy on the LAN address
   (`deployment/nginx-atlas.conf`); set `ATLAS_ENV=production` and `ATLAS_TLS_TERMINATED=true`.
   Binding atlas-api itself to a LAN address requires `ATLAS_ALLOW_LAN=true`, and in production also TLS.
4. Run as a service (`deployment/atlas-api.service`).
5. Back up PostgreSQL with `pg_dump` plus the `atlas-workspace/` directory (see backup-recovery.md).

> **Status:** the PostgreSQL code paths (migrations, tsvector search, row access) are implemented but
> **untested** in this release; all automated tests run on SQLite. Treat PostgreSQL as preview.

## Building from source

```bash
cd project-atlas
python3 -m pip install -e "backend[test]"
(cd frontend && npm ci && npm run build)
cp .env.example .env
atlas serve
```

Development with hot reload: `atlas serve` (API on :8000) and `cd frontend && npm run dev` (Vite on
:5173 proxying `/api`).

## Initial administrator

No default credentials exist. On first start, atlas-api writes a random one-time token to
`<ATLAS_STORAGE_DIR>/setup-token.txt` (mode 0600). Either paste it into the setup screen or run
`atlas create-admin <username>` on the host. The token is deleted once the first user exists.

## Configuration

All settings are `ATLAS_*` variables read from the process environment, overlaid on `./.env` (or the
file named by `ATLAS_ENV_FILE`). See `.env.example` for every option. Invalid or unsafe combinations
stop startup with a clear error.
