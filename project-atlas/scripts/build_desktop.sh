#!/usr/bin/env bash
# Build the standalone "Project Atlas" desktop bundle with PyInstaller for the CURRENT OS.
# Run on Windows (Git Bash) to produce a Windows build, on Linux for Linux, on macOS for macOS.
#   pip install pyinstaller && scripts/build_desktop.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)
rm -rf "$ROOT/backend/project_atlas/static" && cp -r "$ROOT/frontend/dist" "$ROOT/backend/project_atlas/static"
python3 -m pip install --quiet "$ROOT/backend"
cd "$ROOT/desktop"
pyinstaller --noconfirm --clean --distpath "$ROOT/release/desktop" --workpath "$ROOT/release/desktop-build" project_atlas_desktop.spec
rm -rf "$ROOT/backend/project_atlas/static"
PLAT="$(python3 -c 'import sysconfig;print(sysconfig.get_platform())')"
tar -C "$ROOT/release/desktop" -czf "$ROOT/release/Project-Atlas-desktop-$PLAT.tar.gz" "Project Atlas"
echo "Desktop bundle: $ROOT/release/desktop/Project Atlas/ (archive: release/Project-Atlas-desktop-$PLAT.tar.gz)"
