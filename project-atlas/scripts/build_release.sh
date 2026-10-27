#!/usr/bin/env bash
# Build an offline-installable Project Atlas release bundle on a CONNECTED build machine.
#
#   scripts/build_release.sh [output-dir]
#
# Produces release/project-atlas-<version>-<platform>/ containing:
#   wheelhouse/        project-atlas wheel (with the built UI bundled) + every dependency wheel
#   sample-data/       synthetic demonstration data
#   docs/              documentation
#   install.sh / install.ps1, .env.example, SHA256SUMS
# and a .tar.gz of that directory. Wheels are platform specific: build on the target OS/arch
# (e.g. run the PowerShell equivalent on Windows) — see docs/installation.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('$ROOT/backend/project_atlas/__init__.py').read()).group(1))")"
PLAT="$(python3 -c 'import sysconfig;print(sysconfig.get_platform().replace("-","_").replace(".","_"))')-py$(python3 -c 'import sys;print(f"{sys.version_info[0]}{sys.version_info[1]}")')"
OUT="${1:-$ROOT/release}/project-atlas-$VERSION-$PLAT"

bash "$ROOT/scripts/check_identifiers.sh"
echo "==> Building UI"
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)
rm -rf "$ROOT/backend/project_atlas/static"
cp -r "$ROOT/frontend/dist" "$ROOT/backend/project_atlas/static"

echo "==> Building wheels into $OUT/wheelhouse"
rm -rf "$OUT" && mkdir -p "$OUT/wheelhouse"
python3 -m pip wheel --quiet "$ROOT/backend" -w "$OUT/wheelhouse"
rm -rf "$ROOT/backend/project_atlas/static" "$ROOT/backend/build"

cp -r "$ROOT/sample-data" "$ROOT/docs" "$OUT/"
cp "$ROOT/.env.example" "$ROOT/README.md" "$ROOT/LICENSE" "$OUT/"
cp "$ROOT/deployment/install.sh" "$ROOT/deployment/install.ps1" "$OUT/"
chmod +x "$OUT/install.sh"
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar -C "$(dirname "$OUT")" -czf "$OUT.tar.gz" "$(basename "$OUT")"
echo "==> Release bundle: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1))"
