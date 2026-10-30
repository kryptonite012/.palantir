#!/usr/bin/env python3
"""Generate docs/api.md (endpoint reference) and docs/openapi.json from the live FastAPI application."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from project_atlas.core.config import load_settings  # noqa: E402
from project_atlas.main import create_app  # noqa: E402

tmp = Path(tempfile.mkdtemp())
app = create_app(load_settings({"ATLAS_STORAGE_DIR": str(tmp / "ws"), "ATLAS_BACKUP_DIR": str(tmp / "bk"),
                                "ATLAS_LOG_LEVEL": "WARNING", "ATLAS_FRONTEND_DIST": str(tmp / "none")}))
spec = app.openapi()
(ROOT / "docs" / "openapi.json").write_text(json.dumps(spec, indent=1))
lines = ["# API reference (atlas-api)", "",
         "Generated from the application by `scripts/generate_api_docs.py`; the machine-readable spec is",
         "[`openapi.json`](openapi.json) and the interactive docs are served at `/api/docs`.", "",
         "Authentication: `Authorization: Bearer <token>` from `POST /api/auth/login` (or `/api/auth/setup`).",
         "Errors: `{\"error\": {\"code\", \"message\", \"details\"}}` with HTTP 400/401/403/404/409/422/429/503.",
         "Project-scoped routes return 404 to non-members.", ""]
by_tag: dict[str, list] = {}
for path, ops in spec["paths"].items():
    for method, op in ops.items():
        by_tag.setdefault((op.get("tags") or ["other"])[0], []).append((path, method.upper(), op))
for tag in sorted(by_tag):
    lines += [f"## {tag}", "", "| Method | Path | Summary |", "|---|---|---|"]
    for path, method, op in sorted(by_tag[tag]):
        summary = (op.get("description") or op.get("summary") or "").split("\n")[0].replace("|", "\\|")
        lines.append(f"| {method} | `{path}` | {summary} |")
    lines.append("")
n = sum(len(v) for v in by_tag.values())
lines[4] = f"\n{n} operations.\n"
(ROOT / "docs" / "api.md").write_text("\n".join(lines))
print(f"wrote docs/api.md with {n} operations")
