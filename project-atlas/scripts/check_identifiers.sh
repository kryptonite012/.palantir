#!/usr/bin/env bash
# Pre-release check for stale or foreign product identifiers in tracked project files.
# Exit code 1 if any are found. Third-party dependency names are not scanned (node_modules, lockfiles).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PATTERN='(project[ _-]?aegis|\baegis\b)'
HITS=$(cd "$ROOT" && git ls-files -z | grep -zv -E '(package-lock\.json|\.ttf|\.ico|\.png|\.pdf|\.docx)$' \
       | xargs -0 grep -niIE "$PATTERN" -- 2>/dev/null | grep -v "scripts/check_identifiers.sh")
if [ -n "$HITS" ]; then
  echo "Stale identifiers found:"; echo "$HITS"; exit 1
fi
echo "No stale identifiers (pattern: $PATTERN) in tracked files."
