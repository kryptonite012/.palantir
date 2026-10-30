"""Analytics reproducibility, SQL safety, timeline and geospatial operations."""
import io
import json

import pytest

from conftest import SAMPLE, load_demo
from project_atlas.analytics.sql import validate_sql
from project_atlas.core.errors import ValidationFailed


def _ds(api, pid, name):
    return next(d for d in api.ok(api.get(f"/api/projects/{pid}/datasets")) if d["name"] == name)


def test_outliers_describe_and_reproduce(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    exp = json.loads((SAMPLE / "expected_results.json").read_text())["transactions"]
    tx = _ds(admin, pid, "transactions")
    vid = tx["latest"]["version_id"]
    out = admin.ok(admin.post(f"/api/projects/{pid}/analyses", json={"kind": "outliers", "dataset_version_id": vid,
                                                                    "params": {"field": "amount"}}))
    rows = admin.ok(admin.get(f"/api/projects/{pid}/datasets/{tx['id']}/records", params={"limit": 100}))["records"]
    by_id = {r["id"]: r["normalized"]["txn_id"] for r in rows}
    flagged = sorted(by_id[o["record_id"]] for o in out["result"]["outliers"])
    assert flagged == sorted(exp["statistical_outliers_amount"])
    assert "not evidence of fraud" in out["result"]["disclaimer"]
    assert out["inputs"]["dataset_versions"][0]["content_sha256"] == tx["latest"]["content_sha256"]
    assert out["algorithm_version"] and out["duration_ms"] >= 0
    # locale-formatted amount normalized
    r33 = next(r for r in rows if r["row_index"] == 33)
    assert r33["normalized"]["amount"] == 1250.5 and r33["raw"]["amount"] == "1 250,50"
    rep = admin.ok(admin.post(f"/api/projects/{pid}/analyses/{out['id']}/reproduce"))
    assert rep["identical_result"] is True
    for kind, params in [("describe", {}), ("frequency", {"field": "city"}), ("missing", {}),
                         ("trend", {"time_field": "event_time", "period": "M"}),
                         ("timeseries", {"time_field": "event_time"}),
                         ("correlation", {"fields": ["amount", "latitude"]})]:
        r = admin.ok(admin.post(f"/api/projects/{pid}/analyses", json={"kind": kind, "dataset_version_id": vid, "params": params}))
        assert r["result_sha256"], kind
    corr = r["result"]["pairs"][0]
    assert corr["n"] >= 50 and "causation" in r["result"]["limitations"]
    bad = admin.post(f"/api/projects/{pid}/analyses", json={"kind": "frequency", "dataset_version_id": vid, "params": {"field": "nope"}})
    assert bad.status_code == 422


def test_reproduction_detects_changed_inputs(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    ents = admin.ok(admin.get(f"/api/projects/{pid}/entities", params={"q": "Mercer"}))["entities"]
    a, b = ents[0]["id"], ents[1]["id"]
    run = admin.ok(admin.post(f"/api/projects/{pid}/analyses", json={"kind": "entity_similarity", "params": {"entity_a": a, "entity_b": b}}))
    assert run["result"]["score"] > 0.8
    admin.ok(admin.post(f"/api/projects/{pid}/entities/merge", json={"survivor_id": a, "merged_id": b, "note": "same phone"}))
    rep = admin.ok(admin.post(f"/api/projects/{pid}/analyses/{run['id']}/reproduce"))
    assert rep["identical_inputs"] is False


@pytest.mark.parametrize("sql", [
    "DELETE FROM people", "select 1; drop table people", "ATTACH 'x.db' AS x", "COPY people TO 'out.csv'",
    "select * from read_csv('/etc/passwd')", "SELECT * FROM read_parquet('x')", "INSTALL httpfs", "PRAGMA database_list",
    "SET enable_external_access=true", "select getenv('HOME')", "WITH x AS (SELECT 1) DELETE FROM people",
    "select * from glob('/*')", "CALL pragma_version()", "/* comment */ create table t as select 1",
])
def test_sql_validator_rejects_unsafe(sql):
    with pytest.raises(ValidationFailed):
        validate_sql(sql)


def test_sql_console_read_only(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    r = admin.ok(admin.post(f"/api/projects/{pid}/sql", json={
        "sql": "select receiver_org_id, count(*) n, round(sum(amount),2) total from transactions group by 1 order by n desc"}))
    assert r["columns"] == ["receiver_org_id", "n", "total"] and r["row_count"] == 8
    j = admin.ok(admin.post(f"/api/projects/{pid}/sql", json={
        "sql": "select o.name, count(*) from transactions t join organizations o on o.org_id = t.receiver_org_id group by 1"}))
    assert j["row_count"] == 8
    # string literal containing a semicolon is fine
    assert admin.ok(admin.post(f"/api/projects/{pid}/sql", json={"sql": "select 'a;b' as x"}))["rows"] == [["a;b"]]
    denied = admin.post(f"/api/projects/{pid}/sql", json={"sql": "select * from read_csv_auto('/etc/passwd')"})
    assert denied.status_code == 422
    audit = admin.ok(admin.get("/api/admin/audit", params={"action": "query.sql", "outcome": "denied"}))
    assert audit["total"] == 1


def test_sql_engine_blocks_files_even_if_validator_bypassed(monkeypatch):
    """Defence in depth: DuckDB external access is disabled before user SQL runs."""
    import re

    from project_atlas.analytics import sql as sqlx

    monkeypatch.setattr(sqlx, "_FORBIDDEN", re.compile(r"(?!x)x"))  # validator that allows everything
    with pytest.raises(ValidationFailed) as exc:
        sqlx.run_query("select * from read_text('/etc/hostname')", {}, row_limit=10, timeout_s=5)
    assert "disabled" in exc.value.message.lower() or "permission" in exc.value.message.lower()


def test_sql_row_limit_and_timeout(admin, project, app):
    pid = project["id"]
    load_demo(admin, pid)
    app.state.ctx.settings.query_row_limit = 5
    r = admin.ok(admin.post(f"/api/projects/{pid}/sql", json={"sql": "select * from range(100)"}))
    assert r["row_count"] == 5 and r["truncated"] is True
    app.state.ctx.settings.query_timeout_seconds = 1
    slow = admin.post(f"/api/projects/{pid}/sql", json={"sql": "select count(*) from range(100000000) a, range(100000) b"})
    assert slow.status_code == 422 and "time limit" in slow.json()["error"]["message"]


def test_timeline(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    tl = admin.ok(admin.get(f"/api/projects/{pid}/timeline", params={"tz": "Europe/Oslo", "cluster_gap_seconds": 86400}))
    assert len(tl["events"]) == 59  # one invalid timestamp produced no event
    e = tl["events"][0]
    assert e["event_time"] < tl["events"][-1]["event_time"]
    assert e["source_time_text"] and e["ingested_at"] and e["event_time_display"].endswith(("+01:00", "+02:00"))
    assert sum(c["size"] for c in tl["clusters"]) == 59
    win = admin.ok(admin.get(f"/api/projects/{pid}/timeline", params={"start": "2025-04-01T00:00:00Z", "end": "2025-04-30T23:59:59Z"}))
    assert all("2025-04" in x["event_time"] for x in win["events"])
    assert win["relationships_in_window"]
    person = next(x for x in tl["events"] if x["entity_id"])["entity_id"]
    other = next(x["entity_id"] for x in tl["events"] if x["entity_id"] and x["entity_id"] != person)
    cmp_ = admin.ok(admin.get(f"/api/projects/{pid}/timeline/compare", params={"entity_a": person, "entity_b": other,
                                                                             "window_seconds": 86400 * 7}))
    assert "does not establish" in cmp_["note"]
    assert admin.get(f"/api/projects/{pid}/timeline", params={"tz": "Not/AZone"}).status_code == 422


def test_geospatial(admin, project):
    pid = project["id"]
    load_demo(admin, pid)
    with open(SAMPLE / "synthetic_districts.geojson", "rb") as f:
        admin.ok(admin.post(f"/api/projects/{pid}/geo/layers", data={"layer": "districts"}, files={"file": ("d.geojson", f)}))
    layers = {l["layer"]: l for l in admin.ok(admin.get(f"/api/projects/{pid}/geo/layers"))}
    # 60 rows - 1 out-of-range latitude - 1 null-island placeholder => 58 points; coordinates never invented
    n_districts = json.loads((SAMPLE / "expected_results.json").read_text())["geo"]["districts"]
    assert layers["transactions"]["count"] == 58 and layers["districts"]["count"] == n_districts
    join = admin.ok(admin.get(f"/api/projects/{pid}/geo/join", params={"point_layer": "transactions", "polygon_layer": "districts"}))
    assert join["points"] == 58 and join["polygons"] == n_districts
    assert sum(p["point_count"] for p in join["by_polygon"]) + join["unmatched_points"] == 58
    rad = admin.ok(admin.get(f"/api/projects/{pid}/geo/radius", params={"lon": 10.7387, "lat": 59.9075, "radius_m": 5000}))
    assert rad["results"] and all(r["distance_m"] <= 5000 for r in rad["results"])
    d = admin.ok(admin.get(f"/api/projects/{pid}/geo/distance", params={"lon1": 10.7387, "lat1": 59.9075, "lon2": 10.2045, "lat2": 59.7440}))
    assert 30000 < d["distance_m"] < 36000
    cl = admin.ok(admin.get(f"/api/projects/{pid}/geo/clusters", params={"cell_deg": 0.2, "layer": "transactions"}))
    assert sum(c["count"] for c in cl["clusters"]) == 58
    bbox = admin.ok(admin.get(f"/api/projects/{pid}/geo/features", params={"bbox": "10.0,59.6,10.4,59.8", "layer": "transactions"}))
    assert all(10.0 <= f["geometry"]["coordinates"][0] <= 10.4 for f in bbox["features"])
    tf = admin.ok(admin.get(f"/api/projects/{pid}/geo/features", params={"layer": "transactions", "start": "2025-04-01T00:00:00Z",
                                                                       "end": "2025-04-30T23:59:59Z"}))
    assert 0 < len(tf["features"]) < 58
    ann = admin.ok(admin.post(f"/api/projects/{pid}/geo/features", json={"name": "Berth 7", "geometry": {"type": "Point", "coordinates": [10.74, 59.90]}}))
    assert ann["properties"]["_kind"] == "annotation"
    bad = admin.post(f"/api/projects/{pid}/geo/features", json={"geometry": {"type": "Point", "coordinates": [200, 0]}})
    assert bad.status_code == 422
    with_bad = admin.post(f"/api/projects/{pid}/geo/layers", data={"layer": "x"}, files={"file": ("x.geojson", io.BytesIO(b"{]"))})
    assert with_bad.status_code == 422
