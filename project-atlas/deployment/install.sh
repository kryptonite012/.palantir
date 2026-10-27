#!/usr/bin/env bash
# Offline installer for Project Atlas (Linux/macOS). Requires Python 3.11+ only; no network access.
#   ./install.sh [install-dir]     (default: ~/project-atlas)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/project-atlas}"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
if [ -f "$HERE/SHA256SUMS" ]; then
  echo "==> Verifying bundle checksums"
  (cd "$HERE" && sha256sum --quiet -c SHA256SUMS)
fi
echo "==> Creating virtual environment in $DEST/venv"
mkdir -p "$DEST"
"$PY" -m venv "$DEST/venv"
"$DEST/venv/bin/python" -m pip install --quiet --no-index --find-links "$HERE/wheelhouse" project-atlas
[ -f "$DEST/.env" ] || sed -e "s#^ATLAS_STORAGE_DIR=.*#ATLAS_STORAGE_DIR=$DEST/atlas-workspace#" \
                           -e "s#^ATLAS_BACKUP_DIR=.*#ATLAS_BACKUP_DIR=$DEST/atlas-backups#" \
                           -e "s#^ATLAS_MODEL_DIR=.*#ATLAS_MODEL_DIR=$DEST/models#" "$HERE/.env.example" > "$DEST/.env"
cat > "$DEST/atlas" <<LAUNCH
#!/usr/bin/env bash
cd "$DEST" && exec "$DEST/venv/bin/atlas" "\$@"
LAUNCH
chmod +x "$DEST/atlas"
cp -r "$HERE/sample-data" "$DEST/" 2>/dev/null || true
echo "==> Installed. Verify offline readiness:  $DEST/atlas offline-check"
echo "    Start:                               $DEST/atlas serve   (then open http://127.0.0.1:8000)"
echo "    The one-time setup token is written to $DEST/atlas-workspace/setup-token.txt on first start."
