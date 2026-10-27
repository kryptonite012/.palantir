"""Offline geospatial operations on GeoJSON geometries (no external services).

Implements bounding-box and radius queries (haversine), distance measurement,
point-in-polygon spatial joins (ray casting), grid clustering and GeoJSON
layer import. Coordinates are WGS84 longitude/latitude. Missing coordinates
are never inferred.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from project_atlas.core.errors import ValidationFailed
from project_atlas.database.models import GeoFeature

EARTH_RADIUS_M = 6371008.8
MAX_FEATURES = 50000


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _coords(geom: dict[str, Any]) -> list[tuple[float, float]]:
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point":
        return [tuple(c[:2])]
    if t in {"LineString", "MultiPoint"}:
        return [tuple(p[:2]) for p in c]
    if t in {"Polygon", "MultiLineString"}:
        return [tuple(p[:2]) for ring in c for p in ring]
    if t == "MultiPolygon":
        return [tuple(p[:2]) for poly in c for ring in poly for p in ring]
    raise ValidationFailed(f"Unsupported geometry type {t}")


def validate_geometry(geom: dict[str, Any]) -> tuple[float, float, float, float]:
    pts = _coords(geom)
    if not pts:
        raise ValidationFailed("Geometry has no coordinates")
    for lon, lat in pts:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValidationFailed(f"Coordinate out of range: {lon}, {lat}")
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    return min(lons), min(lats), max(lons), max(lats)


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geometry(lon: float, lat: float, geom: dict[str, Any]) -> bool:
    if geom["type"] == "Polygon":
        rings = geom["coordinates"]
        return point_in_ring(lon, lat, rings[0]) and not any(point_in_ring(lon, lat, h) for h in rings[1:])
    if geom["type"] == "MultiPolygon":
        return any(point_in_geometry(lon, lat, {"type": "Polygon", "coordinates": p}) for p in geom["coordinates"])
    return False


def feature_view(f: GeoFeature) -> dict[str, Any]:
    return {"type": "Feature", "id": f.id, "geometry": f.geometry,
            "properties": {**(f.properties or {}), "_id": f.id, "_name": f.name, "_layer": f.layer, "_kind": f.kind,
                           "_record_id": f.record_id, "_entity_id": f.entity_id,
                           "_time": f.feature_time.isoformat() if f.feature_time else None}}


def query(db: Session, project_id: str, *, layers: list[str] | None, bbox: list[float] | None,
          start: datetime | None, end: datetime | None, limit: int = 5000) -> list[GeoFeature]:
    q = select(GeoFeature).where(GeoFeature.project_id == project_id)
    if layers:
        q = q.where(GeoFeature.layer.in_(layers))
    if bbox:
        if len(bbox) != 4:
            raise ValidationFailed("bbox must be minLon,minLat,maxLon,maxLat")
        w, s, e, n = bbox
        q = q.where(GeoFeature.max_lon >= w, GeoFeature.min_lon <= e, GeoFeature.max_lat >= s, GeoFeature.min_lat <= n)
    if start:
        q = q.where(or_(GeoFeature.feature_time.is_(None), GeoFeature.feature_time >= start))
    if end:
        q = q.where(or_(GeoFeature.feature_time.is_(None), GeoFeature.feature_time <= end))
    return db.execute(q.limit(min(limit, MAX_FEATURES))).scalars().all()


def radius(db: Session, project_id: str, lon: float, lat: float, radius_m: float, layers: list[str] | None) -> list[dict[str, Any]]:
    if radius_m <= 0 or radius_m > 2_000_000:
        raise ValidationFailed("radius_m must be in (0, 2,000,000]")
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    cands = query(db, project_id, layers=layers, bbox=[lon - dlon, lat - dlat, lon + dlon, lat + dlat], start=None, end=None)
    out = []
    for f in cands:
        if f.geometry["type"] != "Point":
            continue
        flon, flat = f.geometry["coordinates"][:2]
        d = haversine_m(lon, lat, flon, flat)
        if d <= radius_m:
            out.append({**feature_view(f), "distance_m": round(d, 2)})
    return sorted(out, key=lambda x: x["distance_m"])


def spatial_join(db: Session, project_id: str, point_layer: str, polygon_layer: str) -> dict[str, Any]:
    polys = [f for f in query(db, project_id, layers=[polygon_layer], bbox=None, start=None, end=None)
             if f.geometry["type"] in {"Polygon", "MultiPolygon"}]
    points = [f for f in query(db, project_id, layers=[point_layer], bbox=None, start=None, end=None) if f.geometry["type"] == "Point"]
    counts = []
    unmatched = 0
    assignments: dict[str, list[str]] = {p.id: [] for p in polys}
    for pt in points:
        lon, lat = pt.geometry["coordinates"][:2]
        hit = False
        for pg in polys:
            if pg.min_lon <= lon <= pg.max_lon and pg.min_lat <= lat <= pg.max_lat and point_in_geometry(lon, lat, pg.geometry):
                assignments[pg.id].append(pt.id)
                hit = True
        unmatched += 0 if hit else 1
    for pg in polys:
        counts.append({"polygon_id": pg.id, "polygon_name": pg.name, "point_count": len(assignments[pg.id]),
                       "point_ids": assignments[pg.id][:200]})
    return {"point_layer": point_layer, "polygon_layer": polygon_layer, "points": len(points), "polygons": len(polys),
            "unmatched_points": unmatched, "by_polygon": sorted(counts, key=lambda c: -c["point_count"]),
            "method": "ray-casting point-in-polygon on WGS84 coordinates (planar approximation)"}


def grid_clusters(features: list[GeoFeature], cell_deg: float) -> list[dict[str, Any]]:
    if cell_deg <= 0:
        raise ValidationFailed("cell size must be positive")
    cells: dict[tuple[int, int], list[tuple[float, float, str]]] = {}
    for f in features:
        if f.geometry["type"] != "Point":
            continue
        lon, lat = f.geometry["coordinates"][:2]
        cells.setdefault((math.floor(lon / cell_deg), math.floor(lat / cell_deg)), []).append((lon, lat, f.id))
    return sorted(({"centroid": [round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)],
                    "count": len(pts), "feature_ids": [p[2] for p in pts][:100]} for pts in cells.values()),
                  key=lambda c: -c["count"])


def import_geojson(db: Session, project_id: str, layer: str, data: bytes, user_id: str, kind: str = "layer") -> int:
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailed(f"Invalid GeoJSON: {exc}") from exc
    feats = doc.get("features") if doc.get("type") == "FeatureCollection" else [doc] if doc.get("type") == "Feature" else None
    if feats is None:
        raise ValidationFailed("GeoJSON must be a FeatureCollection or Feature")
    if len(feats) > MAX_FEATURES:
        raise ValidationFailed(f"Too many features (max {MAX_FEATURES})")
    n = 0
    for f in feats:
        geom = f.get("geometry")
        if not geom:
            continue  # features without geometry are skipped, never assigned coordinates
        w, s, e, nn = validate_geometry(geom)
        props = f.get("properties") or {}
        add_feature(db, project_id=project_id, layer=layer, kind=kind, name=str(props.get("name", ""))[:255],
                    geometry=geom, properties=props, user_id=user_id)
        n += 1
    return n


def add_feature(db: Session, *, project_id: str, layer: str, kind: str, name: str, geometry: dict[str, Any],
                properties: dict[str, Any], user_id: str, feature_time: datetime | None = None) -> GeoFeature:
    w, s, e, n = validate_geometry(geometry)
    f = GeoFeature(project_id=project_id, layer=layer[:128], kind=kind, name=name, geometry=geometry,
                   properties=json.loads(json.dumps(properties, default=str)), min_lon=w, min_lat=s, max_lon=e, max_lat=n,
                   feature_time=feature_time, created_by=user_id)
    db.add(f)
    return f
