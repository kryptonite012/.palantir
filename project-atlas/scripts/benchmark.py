#!/usr/bin/env python3
"""Measure Project Atlas performance on synthetic data (all generated rows are marked SYNTHETIC).

    python scripts/benchmark.py [--rows 100000] [--people 5000] [--out docs/benchmark-results.json]

Runs in-process against a temporary workspace (SQLite, inline jobs) and reports wall-clock timings,
throughput and peak RSS. Results depend on hardware; the report records the machine it ran on.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from project_atlas.core.config import load_settings  # noqa: E402
from project_atlas.main import create_app  # noqa: E402

PW = "Benchmark-Passw0rd!"
FIRST = ["Anna", "Bjorn", "Carla", "David", "Eva", "Finn", "Greta", "Hugo", "Ida", "Jonas", "Kari", "Leo", "Mia", "Nils", "Olga",
         "Per", "Rita", "Sven", "Tora", "Ulf", "Vera", "Willy", "Xenia", "Yngve", "Zara"]
LAST = ["Aas", "Berg", "Dahl", "Eide", "Foss", "Hagen", "Holm", "Lie", "Lund", "Moe", "Nes", "Ruud", "Sand", "Strand", "Vik",
        "Wold", "Bakke", "Haugen", "Kvam", "Myhre"]


def peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / 1024 if sys.platform != "darwin" else r / 1024 / 1024, 1)


def gen(tmp: Path, rows: int, people: int) -> tuple[Path, Path]:
    rng = random.Random(7)
    pf = tmp / "bench_people.csv"
    with pf.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["person_id", "name", "email", "city", "record_origin"])
        for i in range(people):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            name = f"{first} {last}"
            if i % 10 == 0:  # 10% near-duplicates without ids to exercise resolution
                w.writerow(["", name.upper() if i % 20 else name.replace("a", "aa", 1), f"{first}.{last}{i - 1}@example.invalid".lower(),
                            rng.choice(["Oslo", "Bergen"]), "SYNTHETIC"])
            else:
                w.writerow([f"BP-{i}", name, f"{first}.{last}{i}@example.invalid".lower(), rng.choice(["Oslo", "Bergen", "Tromso"]), "SYNTHETIC"])
    tf = tmp / "bench_transactions.csv"
    with tf.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["txn_id", "sender_id", "receiver_id", "amount", "timestamp", "latitude", "longitude", "memo", "record_origin"])
        for i in range(rows):
            w.writerow([f"BT-{i}", f"BP-{rng.randrange(1, people)}", f"BP-{rng.randrange(1, people)}", f"{rng.lognormvariate(6, 1):.2f}",
                        f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                        f"{59 + rng.random():.5f}", f"{10 + rng.random():.5f}", rng.choice(["freight", "storage", "customs fee", "insurance"]),
                        "SYNTHETIC"])
    return pf, tf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--people", type=int, default=5_000)
    ap.add_argument("--out", default=str(ROOT / "docs" / "benchmark-results.json"))
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="atlas-bench-"))
    results: dict = {"machine": {"platform": platform.platform(), "python": platform.python_version(), "cpus": os.cpu_count()},
                     "rows": args.rows, "people": args.people, "timings": {}}
    T = results["timings"]

    def timed(name, fn):
        t0 = time.perf_counter()
        out = fn()
        T[name] = round(time.perf_counter() - t0, 3)
        print(f"{name:45s} {T[name]:8.3f}s", flush=True)
        return out

    pf, tf = timed("generate synthetic csv", lambda: gen(tmp, args.rows, args.people))
    settings = load_settings({"ATLAS_STORAGE_DIR": str(tmp / "ws"), "ATLAS_BACKUP_DIR": str(tmp / "bk"), "ATLAS_JOBS_INLINE": "true",
                              "ATLAS_LOG_LEVEL": "WARNING", "ATLAS_FRONTEND_DIST": str(tmp / "none"), "ATLAS_MAX_UPLOAD_MB": "2000"})
    app = create_app(settings)
    with TestClient(app) as c:
        token = app.state.ctx.ensure_setup_token()
        h = {"Authorization": "Bearer " + c.post("/api/auth/setup", json={"setup_token": token, "username": "admin", "display_name": "B",
                                                                           "password": PW}).json()["token"]}
        app.state.ctx.api_limiter.max_events = 10**9
        pid = c.post("/api/projects", json={"name": "Benchmark"}, headers=h).json()["id"]

        def imp(path, cfg):
            with open(path, "rb") as f:
                fid = c.post(f"/api/projects/{pid}/files", files={"file": (path.name, f)}, headers=h).json()["id"]
            j = c.post(f"/api/projects/{pid}/ingest/commit", json={"config": {"file_id": fid, **cfg}}, headers=h).json()
            assert j["status"] == "succeeded", j
            return j

        timed(f"import people ({args.people} rows, entities)", lambda: imp(pf, {"dataset_name": "people", "mapping": {
            "person_id": {"target": "person_id", "type": "identifier"}, "name": {"target": "name", "type": "string"},
            "email": {"target": "email", "type": "email"}, "city": {"target": "city", "type": "string"}},
            "entities": [{"entity_type": "person", "name_field": "name", "id_field": "person_id", "attributes": ["email", "city"]}]}))
        timed(f"import transactions ({args.rows} rows, plain)", lambda: imp(tf, {"dataset_name": "transactions_plain"}))
        T["import_rows_per_second_plain"] = round(args.rows / T[f"import transactions ({args.rows} rows, plain)"])
        timed(f"import transactions ({args.rows} rows, entities+links+events+geo)", lambda: imp(tf, {
            "dataset_name": "transactions", "mapping": {
                "txn_id": {"target": "txn_id", "type": "identifier"}, "sender_id": {"target": "sender_id", "type": "identifier"},
                "receiver_id": {"target": "receiver_id", "type": "identifier"}, "amount": {"target": "amount", "type": "float"},
                "timestamp": {"target": "event_time", "type": "datetime"}, "latitude": {"target": "latitude", "type": "latitude"},
                "longitude": {"target": "longitude", "type": "longitude"}, "memo": {"target": "memo", "type": "string"}},
            "entities": [{"entity_type": "person", "id_field": "sender_id", "id_namespace": "person_id"},
                         {"entity_type": "person", "id_field": "receiver_id", "id_namespace": "person_id"}],
            "relationships": [{"source": 0, "target": 1, "rel_type": "transacted_with"}],
            "events": {"time_field": "event_time", "title_template": "Txn {txn_id}", "category": "payment", "entity": 0},
            "geo": {"lat_field": "latitude", "lon_field": "longitude", "label_field": "txn_id"}}))
        T["import_rows_per_second_full"] = round(args.rows / T[f"import transactions ({args.rows} rows, entities+links+events+geo)"])
        lat = []
        for q in ["storage", "Berg", '"customs fee"', "freight OR insurance", "Oslo AND Anna", "BT-4242", "amount>2000"] * 5:
            t0 = time.perf_counter()
            r = c.get("/api/search", params={"q": q, "project_id": pid, "limit": 25}, headers=h)
            assert r.status_code == 200, r.text
            lat.append((time.perf_counter() - t0) * 1000)
        T["search_latency_ms_p50"] = round(statistics.median(lat), 1)
        T["search_latency_ms_p95"] = round(sorted(lat)[int(len(lat) * 0.95) - 1], 1)
        print(f"{'search latency p50/p95 (ms)':45s} {T['search_latency_ms_p50']}/{T['search_latency_ms_p95']}")
        timed("SQL aggregate (group by over full table)", lambda: c.post(f"/api/projects/{pid}/sql", headers=h, json={
            "sql": "select memo, count(*), round(avg(amount),2) from transactions group by memo"}).json()["rows"])
        timed("entity resolution (person type)", lambda: c.post(f"/api/projects/{pid}/entities/resolve", json={"entity_type": "person"}, headers=h).json()["result"])
        ds = {d["name"]: d for d in c.get(f"/api/projects/{pid}/datasets", headers=h).json()}
        vid = ds["transactions"]["latest"]["version_id"]
        timed("analysis: describe (all fields)", lambda: c.post(f"/api/projects/{pid}/analyses", headers=h, json={"kind": "describe", "dataset_version_id": vid}).json())
        timed("analysis: outliers(amount)", lambda: c.post(f"/api/projects/{pid}/analyses", headers=h, json={"kind": "outliers", "dataset_version_id": vid, "params": {"field": "amount"}}).json())
        timed("graph: overview (top 300 nodes)", lambda: c.get(f"/api/projects/{pid}/graph", params={"limit": 300}, headers=h).json())
        timed("graph: pagerank", lambda: c.post(f"/api/projects/{pid}/graph/analyze", headers=h, json={"algorithm": "pagerank"}).json())
        timed("graph: communities (louvain)", lambda: c.post(f"/api/projects/{pid}/graph/analyze", headers=h, json={"algorithm": "communities"}).json())
        timed("graph: betweenness (sampled k=500 if >2000 nodes)", lambda: c.post(f"/api/projects/{pid}/graph/analyze", headers=h, json={"algorithm": "betweenness_centrality"}).json())
        timed("timeline query (2000 events)", lambda: c.get(f"/api/projects/{pid}/timeline", params={"limit": 2000}, headers=h).json())
        timed("geo radius query (5 km)", lambda: c.get(f"/api/projects/{pid}/geo/radius", params={"lon": 10.5, "lat": 59.5, "radius_m": 5000}, headers=h).json())
        rpt = c.post(f"/api/projects/{pid}/reports", headers=h, json={"title": "Bench", "definition": {"sections": [
            {"type": "dataset_table", "dataset_id": ds["transactions"]["id"], "limit": 2000}]}}).json()
        timed("report PDF export (2000-row table)", lambda: c.post(f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "pdf"}, headers=h).json())
        b = timed("backup (unencrypted)", lambda: c.post("/api/admin/backups", json={}, headers=h).json())
        timed("backup verify", lambda: c.post("/api/admin/backups/verify", json={"filename": b["filename"]}, headers=h).json())
        results["backup_size_mb"] = round(b["size_bytes"] / 1e6, 1)
        results["database_size_mb"] = round(Path(settings.resolved_database_url[len("sqlite:///"):]).stat().st_size / 1e6, 1)
        ov = c.get(f"/api/projects/{pid}/overview", headers=h).json()
        results["resulting_counts"] = {k: ov[k] for k in ("records", "entities", "relationships")}
    app.state.ctx.dispose()
    results["peak_rss_mb"] = peak_rss_mb()
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(json.dumps({k: results[k] for k in ("peak_rss_mb", "database_size_mb", "backup_size_mb", "resulting_counts")}, indent=1))


if __name__ == "__main__":
    main()
