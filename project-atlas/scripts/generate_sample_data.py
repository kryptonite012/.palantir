#!/usr/bin/env python3
"""Generate the deterministic SYNTHETIC demonstration dataset into sample-data/ (see project_atlas.demo.generator)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from project_atlas.demo.generator import generate  # noqa: E402

out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "sample-data"
generate(out)
print(f"Wrote synthetic sample data to {out}")
