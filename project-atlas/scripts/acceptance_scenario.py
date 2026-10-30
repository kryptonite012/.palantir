#!/usr/bin/env python3
"""Project Atlas release acceptance scenario (spec §24), driven over HTTP against real server processes.

Steps:
 1. Install            — uses the installed `project_atlas` package (verify import + CLI)
 2. Initial admin      — one-time setup token written by the server
 3. Workspace          — create project
 4. Import             — synthetic datasets
 5. Map & validate     — explicit mapping + dry run with quality checks
 6. Resolve & review   — entity resolution; accept a strong candidate
 7. Explore graph      — neighborhood + centrality
 8. Inspect evidence   — record + document passage captured as evidence
 9. Reproducible run   — analysis + reproduction with identical hash
10. Report             — build, export PDF, verify manifest hash
11. Restart            — stop and start a new server process
12. Persistence/audit  — compare counts, verify hash chain
13. Network disabled   — re-run the server inside a Linux network namespace with loopback only
14. Repeat workflow    — import, resolve, analyse, export while offline

Usage:  python scripts/acceptance_scenario.py [--workdir DIR] [--report FILE]
Writes a JSON report with timings for every step.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample-data"
PW = "Acceptance-Passw0rd!"
RESULTS: list[dict] = []


def log(step: str, ok: bool, detail: str = "", t0: float | None = None):
    rec = {"step": step, "ok": ok, "detail": detail, "seconds": round(time.perf_counter() - t0, 3) if t0 else None}
    RESULTS.append(rec)
    print(f"[{'PASS' if ok else 'FAIL'}] {step}: {detail}" + (f" ({rec['seconds']}s)" if rec["seconds"] is not None else ""), flush=True)
    if not ok:
        raise SystemExit(1)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Server:
    def __init__(self, workdir: Path, port: int):
        self.workdir, self.port, self.proc = workdir, port, None
        self.base = f"http://127.0.0.1:{port}"

    def start(self):
        env = {**os.environ, "ATLAS_STORAGE_DIR": str(self.workdir / "atlas-workspace"), "ATLAS_BACKUP_DIR": str(self.workdir / "atlas-backups"),
               "ATLAS_PORT": str(self.port), "ATLAS_LOG_LEVEL": "WARNING", "ATLAS_OFFLINE_MODE": "true", "ATLAS_ENV": "production"}
        self.proc = subprocess.Popen([sys.executable, "-m", "project_atlas", "serve"], env=env, cwd=str(self.workdir),
                                     stdout=open(self.workdir / f"server-{self.port}.log", "w"), stderr=subprocess.STDOUT)
        for _ in range(120):
            try:
                if httpx.get(f"{self.base}/api/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        raise RuntimeError("server did not start; see " + str(self.workdir / f"server-{self.port}.log"))

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=20)


class Client:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base, timeout=120, trust_env=False)
        self.token = None

    def h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def req(self, method, url, expect=200, **kw):
        r = self.c.request(method, url, headers=self.h(), **kw)
        if r.status_code != expect:
            raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:500]}")
        return r.json() if "json" in r.headers.get("content-type", "") else r

    def wait_job(self, job):
        for _ in range(600):
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(0.2)
            job = self.req("GET", f"/api/jobs/{job['id']}")
        raise RuntimeError("job timeout")

    def upload(self, pid, path: Path):
        with open(path, "rb") as f:
            return self.req("POST", f"/api/projects/{pid}/files", files={"file": (path.name, f)})


PEOPLE = {"dataset_name": "people", "is_synthetic": True, "mapping": {
    "person_id": {"target": "person_id", "type": "identifier"}, "full_name": {"target": "full_name", "type": "string", "required": True},
    "email": {"target": "email", "type": "email", "sensitive": True}, "phone": {"target": "phone", "type": "phone", "sensitive": True},
    "date_of_birth": {"target": "date_of_birth", "type": "date", "sensitive": True}, "city": {"target": "city", "type": "string"},
    "employer_id": {"target": "employer_id", "type": "identifier"}, "record_origin": {"target": "record_origin", "type": "string"}},
    "quality": {"unique": ["person_id"]},
    "entities": [{"entity_type": "person", "name_field": "full_name", "id_field": "person_id", "attributes": ["email", "phone", "date_of_birth", "city"]},
                 {"entity_type": "organization", "id_field": "employer_id", "id_namespace": "org_id"}],
    "relationships": [{"source": 0, "target": 1, "rel_type": "works_for"}]}
ORGS = {"dataset_name": "organizations", "is_synthetic": True, "entities": [{"entity_type": "organization", "name_field": "name", "id_field": "org_id", "id_namespace": "org_id"}]}
CONTACTS = {"dataset_name": "contacts", "is_synthetic": True, "mapping": {
    "name": {"target": "name", "type": "string"}, "email": {"target": "email", "type": "email", "sensitive": True},
    "phone": {"target": "phone", "type": "phone", "sensitive": True}, "city": {"target": "city", "type": "string"}},
    "entities": [{"entity_type": "person", "name_field": "name", "attributes": ["email", "phone", "city"]}]}
TXNS = {"dataset_name": "transactions", "is_synthetic": True, "mapping": {
    "txn_id": {"target": "txn_id", "type": "identifier"}, "sender_id": {"target": "sender_id", "type": "identifier"},
    "receiver_org_id": {"target": "receiver_org_id", "type": "identifier"}, "amount": {"target": "amount", "type": "float"},
    "timestamp": {"target": "event_time", "type": "datetime"}, "latitude": {"target": "latitude", "type": "latitude"},
    "longitude": {"target": "longitude", "type": "longitude"}, "city": {"target": "city", "type": "string"}},
    "entities": [{"entity_type": "person", "id_field": "sender_id", "id_namespace": "person_id"},
                 {"entity_type": "organization", "id_field": "receiver_org_id", "id_namespace": "org_id"}],
    "relationships": [{"source": 0, "target": 1, "rel_type": "transacted_with", "valid_from_field": "event_time"}],
    "events": {"time_field": "event_time", "title_template": "Payment {txn_id}", "category": "payment", "entity": 0},
    "geo": {"lat_field": "latitude", "lon_field": "longitude", "label_field": "txn_id", "entity": 0}}


def import_ds(cl: Client, pid, name, cfg):
    f = cl.upload(pid, SAMPLE / name)
    job = cl.wait_job(cl.req("POST", f"/api/projects/{pid}/ingest/commit", json={"config": {"file_id": f["id"], **cfg}}))
    if job["status"] != "succeeded":
        raise RuntimeError(f"import {name} failed: {job['error']}")
    return job["result"]


def essential_workflow(cl: Client, pid: str, label: str) -> dict:
    """Import → resolve → analyse → report; used online and repeated offline."""
    out = {}
    t0 = time.perf_counter()
    for name, cfg in [("synthetic_organizations.csv", ORGS), ("synthetic_people.csv", PEOPLE),
                      ("synthetic_contacts.csv", CONTACTS), ("synthetic_transactions.csv", TXNS)]:
        out[name] = import_ds(cl, pid, name, cfg)["counts"]["records"]
    log(f"{label}: import synthetic datasets", out["synthetic_people.csv"] == 33 and out["synthetic_transactions.csv"] == 60, json.dumps(out), t0)
    t0 = time.perf_counter()
    job = cl.wait_job(cl.req("POST", f"/api/projects/{pid}/entities/resolve", json={"entity_type": "person"}))
    cands = cl.req("GET", f"/api/projects/{pid}/match-candidates", params={"band": "strong"})["candidates"]
    pairs = [{c["entity_a"]["display_name"], c["entity_b"]["display_name"]} for c in cands]
    ok = {"Dr. Amelia Okafor", "Amelia Okafor"} in pairs and {"Jon Mercer", "Jonathan Mercer"} in pairs
    log(f"{label}: entity resolution", ok and job["status"] == "succeeded", f"{job['result']['candidates_created']} candidates; strong={len(cands)}", t0)
    c = next(c for c in cands if {c["entity_a"]["display_name"], c["entity_b"]["display_name"]} == {"Dr. Amelia Okafor", "Amelia Okafor"})
    t0 = time.perf_counter()
    rev = cl.req("POST", f"/api/projects/{pid}/match-candidates/{c['id']}/review", json={"decision": "accept", "note": "same e-mail (acceptance)"})
    log(f"{label}: review & merge", rev["status"] == "accepted", f"merge {rev['merge_id']}", t0)
    out["merged_entity"] = c["entity_a"]["id"]  # survivor (default when no survivor_id is given)
    ds = {d["name"]: d for d in cl.req("GET", f"/api/projects/{pid}/datasets")}
    t0 = time.perf_counter()
    run = cl.req("POST", f"/api/projects/{pid}/analyses", json={"kind": "outliers", "dataset_version_id": ds["transactions"]["latest"]["version_id"],
                                                               "params": {"field": "amount"}})
    rep = cl.req("POST", f"/api/projects/{pid}/analyses/{run['id']}/reproduce")
    log(f"{label}: reproducible analysis", rep["identical_result"] and run["result"]["outlier_count"] == 2,
        f"outliers={run['result']['outlier_count']} sha={run['result_sha256'][:12]} reproduced identical={rep['identical_result']}", t0)
    out["run_id"] = run["id"]
    out["datasets"] = ds
    return out


def bring_up_loopback():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    flags = struct.unpack("16sH", fcntl.ioctl(s, 0x8913, struct.pack("16sH", b"lo", 0))[:18])[1]
    fcntl.ioctl(s, 0x8914, struct.pack("16sH", b"lo", flags | 1))


def offline_phase(workdir: Path):
    """Runs inside an isolated network namespace (only loopback)."""
    bring_up_loopback()
    t0 = time.perf_counter()
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=2)
        external = "reachable"
    except OSError as exc:
        external = f"unreachable ({exc.strerror})"
    log("13 network disabled", external.startswith("unreachable"), f"namespace: external network {external}", t0)
    srv = Server(workdir, free_port())
    t0 = time.perf_counter()
    srv.start()
    cl = Client(srv.base)
    cl.token = cl.req("POST", "/api/auth/login", json={"username": "admin", "password": PW})["token"]
    pid = cl.req("POST", "/api/projects", json={"name": "Offline repeat"})["id"]
    log("14 offline: server start + login + new workspace", True, srv.base, t0)
    out = essential_workflow(cl, pid, "14 offline")
    t0 = time.perf_counter()
    f = cl.upload(pid, SAMPLE / "synthetic_harbor_audit_report.pdf")
    cl.wait_job(cl.req("POST", f"/api/projects/{pid}/documents", json={"file_id": f["id"]}))
    ans = cl.req("POST", f"/api/projects/{pid}/documents/ask", json={"question": "Who approved the large payments?"})
    rpt = cl.req("POST", f"/api/projects/{pid}/reports", json={"title": "Offline report", "definition": {"sections": [
        {"type": "summary", "body": "Generated with networking disabled."}, {"type": "analysis", "analysis_run_id": out["run_id"]}]}})
    ex = cl.req("POST", f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "pdf"})
    chk = cl.req("GET", "/api/system/offline-check")
    log("14 offline: documents, assistant, PDF report, offline-check", "Jonathan Mercer" in (ans["answer"] or "") and ex["size_bytes"] > 1000
        and chk["all_required_ok"], f"assistant={ans['mode']}; pdf={ex['size_bytes']}B; offline checks ok={chk['all_required_ok']}", t0)
    srv.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir")
    ap.add_argument("--report", default=str(ROOT / "docs" / "acceptance-results.json"))
    ap.add_argument("--offline-phase", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    workdir = Path(args.workdir or tempfile.mkdtemp(prefix="atlas-acceptance-"))
    if args.offline_phase:
        offline_phase(workdir)
        Path(workdir / "offline-results.json").write_text(json.dumps(RESULTS))
        return
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    t0 = time.perf_counter()
    import project_atlas

    cli = subprocess.run([sys.executable, "-m", "project_atlas", "--help"], capture_output=True, text=True)
    log("1 install", cli.returncode == 0 and "serve" in cli.stdout, f"project_atlas {project_atlas.__version__} at {Path(project_atlas.__file__).parent}", t0)
    srv = Server(workdir, free_port())
    srv.start()
    cl = Client(srv.base)
    t0 = time.perf_counter()
    st = cl.req("GET", "/api/auth/setup-status")
    token = Path(st["setup_token_location"]).read_text().strip()
    cl.req("POST", "/api/auth/setup", expect=403, json={"setup_token": "guess", "username": "admin", "display_name": "A", "password": PW})
    cl.token = cl.req("POST", "/api/auth/setup", json={"setup_token": token, "username": "admin", "display_name": "Administrator", "password": PW})["token"]
    log("2 initial administrator", not Path(st["setup_token_location"]).exists(), "setup token required, consumed and deleted", t0)
    t0 = time.perf_counter()
    pid = cl.req("POST", "/api/projects", json={"name": "Acceptance — Northwind Harbor", "classification": "confidential"})["id"]
    log("3 workspace", True, pid, t0)
    t0 = time.perf_counter()
    f = cl.upload(pid, SAMPLE / "synthetic_transactions.csv")
    insp = cl.req("POST", f"/api/projects/{pid}/ingest/inspect", json={"file_id": f["id"]})
    dry = cl.req("POST", f"/api/projects/{pid}/ingest/preview", json={"config": {"file_id": f["id"], **TXNS}})
    q = dry["quality"]["issue_counts"]
    log("5 map & validate (dry run)", q.get("timestamp_error") == 1 and q.get("coordinate_error") == 2 and not cl.req("GET", f"/api/projects/{pid}/datasets"),
        f"columns={len(insp['columns'])} issues={q}", t0)
    out = essential_workflow(cl, pid, "4/6/9 online")
    t0 = time.perf_counter()
    org = cl.req("GET", f"/api/projects/{pid}/entities", params={"entity_type": "organization", "q": "Northwind"})["entities"][0]
    nb = cl.req("GET", f"/api/projects/{pid}/graph", params={"center": org["id"], "depth": 1, "rel_type": "works_for"})
    cent = cl.req("POST", f"/api/projects/{pid}/graph/analyze", json={"algorithm": "degree_centrality", "params": {"top": 5}})
    log("7 explore graph", len(nb["edges"]) == 4 and len(cent["result"]["ranking"]) == 5,
        f"{org['display_name']}: {len(nb['edges'])} works_for edges; top={cent['result']['ranking'][0]['label']}", t0)
    t0 = time.perf_counter()
    det = cl.req("GET", f"/api/projects/{pid}/entities/{out['merged_entity']}")
    rec = det["source_records"][0]["record_id"]
    inv = cl.req("POST", f"/api/projects/{pid}/investigations", json={"title": "Acceptance investigation", "objective": "Verify provenance"})
    ev = cl.req("POST", f"/api/projects/{pid}/investigations/{inv['id']}/evidence", json={"source_type": "record", "source_ref": rec})
    raw = cl.req("GET", f"/api/projects/{pid}/records/{rec}")
    log("8 inspect source evidence", ev["provenance"]["row_hash"] == raw["row_hash"] and raw["source_file"]["sha256"],
        f"record {rec} from {raw['dataset']['name']} v{raw['dataset']['version']} file sha256 {raw['source_file']['sha256'][:12]}", t0)
    t0 = time.perf_counter()
    rpt = cl.req("POST", f"/api/projects/{pid}/reports", json={"title": "Acceptance report", "definition": {"sections": [
        {"type": "summary", "body": "Synthetic acceptance run."}, {"type": "analysis", "analysis_run_id": out["run_id"]},
        {"type": "dataset_table", "dataset_id": out["datasets"]["people"]["id"]}, {"type": "evidence", "investigation_id": inv["id"]},
        {"type": "limitations", "body": "Synthetic data only."}]}})
    ex = cl.req("POST", f"/api/projects/{pid}/reports/{rpt['id']}/export", params={"fmt": "pdf"})
    pdf = cl.c.get(f"/api/projects/{pid}/reports/{rpt['id']}/exports/{ex['id']}", headers=cl.h()).content
    log("10 report export", hashlib.sha256(pdf).hexdigest() == ex["sha256"] and pdf.startswith(b"%PDF"),
        f"{len(pdf)} bytes, manifest lists {len(ex['manifest']['dataset_versions'])} dataset versions", t0)
    before = cl.req("GET", f"/api/projects/{pid}/overview")
    audit_before = cl.req("GET", "/api/admin/audit")["total"]
    t0 = time.perf_counter()
    srv.stop()
    srv2 = Server(workdir, free_port())
    srv2.start()
    log("11 restart", True, "new server process started", t0)
    t0 = time.perf_counter()
    cl2 = Client(srv2.base)
    cl2.token = cl2.req("POST", "/api/auth/login", json={"username": "admin", "password": PW})["token"]
    after = cl2.req("GET", f"/api/projects/{pid}/overview")
    ver = cl2.req("POST", "/api/admin/audit/verify")
    audit_after = cl2.req("GET", "/api/admin/audit")["total"]
    same = {k: before[k] for k in ("datasets", "records", "entities", "relationships")} == {k: after[k] for k in ("datasets", "records", "entities", "relationships")}
    log("12 persistence & audit", same and ver["valid"] and audit_after > audit_before,
        f"counts identical={same}; audit chain valid over {ver['events_checked']} events", t0)
    t0 = time.perf_counter()
    bk = cl2.req("POST", "/api/admin/backups", json={})
    vb = cl2.req("POST", "/api/admin/backups/verify", json={"filename": bk["filename"]})
    log("backup + verify", vb["valid"], f"{bk['filename']} {bk['size_bytes']} bytes", t0)
    srv2.stop()
    # 13-14: same workspace, server re-run inside a network namespace without external connectivity
    if shutil.which("unshare"):
        r = subprocess.run(["unshare", "-rn", sys.executable, __file__, "--offline-phase", "--workdir", str(workdir)])
        offline = workdir / "offline-results.json"
        if offline.exists():
            RESULTS.extend(json.loads(offline.read_text()))
        if r.returncode != 0:
            log("13/14 offline phase", False, f"exit {r.returncode}")
    else:
        log("13 network disabled", False, "unshare not available; run steps 13-14 manually with networking disabled")
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "python": sys.version.split()[0],
              "platform": sys.platform, "total_seconds": round(time.perf_counter() - started, 2), "steps": RESULTS,
              "all_passed": all(r["ok"] for r in RESULTS)}
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(f"\nAll steps passed: {report['all_passed']} in {report['total_seconds']}s. Report: {args.report}")


if __name__ == "__main__":
    main()
