import { useEffect, useRef, useState } from "react";
import maplibregl, { GeoJSONSource, Map as MlMap } from "maplibre-gl";
import { api, pp } from "../../services/api";
import { useAtlas } from "../../app/store";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { Badge, ErrorBox, Field, Notice, PageHeader, SplitPane, Table, fmtNum } from "../../components/ui";
import { offlineStyle } from "./basemap";

type Mode = "inspect" | "radius" | "measure" | "annotate";

export function GeoPage() {
  const pid = useProjectId();
  const theme = useAtlas((s) => s.theme);
  const mapRef = useRef<MlMap | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const layers = usePQuery<any[]>(["geo-layers"], "/geo/layers");
  const [active, setActive] = useState<string[]>([]);
  const [heat, setHeat] = useState(false);
  const [cluster, setCluster] = useState(true);
  const [mode, setMode] = useState<Mode>("inspect");
  const [radiusM, setRadiusM] = useState(5000);
  const [time, setTime] = useState({ start: "", end: "" });
  const [result, setResult] = useState<any>(null);
  const [measure, setMeasure] = useState<[number, number][]>([]);
  const [join, setJoin] = useState({ points: "", polygons: "" });
  const [err, setErr] = useState<unknown>(null);
  const canWrite = useCan("geo.write");
  const modeRef = useRef(mode);
  modeRef.current = mode;

  const fitted = useRef(false);
  useEffect(() => { if (layers.data && !active.length) setActive(layers.data.map((l) => l.layer)); }, [layers.data]); // eslint-disable-line
  useEffect(() => {
    // Fit the view to the extent of the project's geodata once, so the user starts where the data is.
    const map = mapRef.current;
    const boxes = (layers.data ?? []).map((l) => l.bbox).filter((b) => b && b.every((x: number | null) => x !== null));
    if (!map || fitted.current || !boxes.length) return;
    const w = Math.min(...boxes.map((b) => b[0])), s = Math.min(...boxes.map((b) => b[1]));
    const e = Math.max(...boxes.map((b) => b[2])), n = Math.max(...boxes.map((b) => b[3]));
    map.fitBounds([[w, s], [e, n]], { padding: 60, maxZoom: 12, duration: 0 });
    fitted.current = true;
  }, [layers.data, theme]);

  useEffect(() => {
    if (!box.current) return;
    const map = new maplibregl.Map({ container: box.current, style: offlineStyle(theme === "dark"), center: [10.6, 59.8], zoom: 7, attributionControl: false });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    mapRef.current = map;
    return () => map.remove();
  }, [theme]);

  // load features for selected layers / time filter
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !pid) return;
    const apply = async () => {
      try {
        const fc = await api(pp(pid, "/geo/features"), { params: { layer: active, start: time.start ? `${time.start}T00:00:00Z` : undefined, end: time.end ? `${time.end}T23:59:59Z` : undefined } });
        const points = { type: "FeatureCollection", features: fc.features.filter((f: any) => f.geometry.type === "Point") };
        const shapes = { type: "FeatureCollection", features: fc.features.filter((f: any) => f.geometry.type !== "Point") };
        for (const id of ["pts-heat", "pts-cluster", "pts-count", "pts", "shapes-fill", "shapes-line"]) if (map.getLayer(id)) map.removeLayer(id);
        for (const id of ["pts", "shapes"]) if (map.getSource(id)) map.removeSource(id);
        map.addSource("shapes", { type: "geojson", data: shapes as any });
        map.addLayer({ id: "shapes-fill", type: "fill", source: "shapes", paint: { "fill-color": "#58a6de", "fill-opacity": 0.12 } });
        map.addLayer({ id: "shapes-line", type: "line", source: "shapes", paint: { "line-color": "#58a6de", "line-width": 1.2 } });
        map.addSource("pts", { type: "geojson", data: points as any, cluster: cluster && !heat, clusterRadius: 40, clusterMaxZoom: 8 });
        if (heat) map.addLayer({ id: "pts-heat", type: "heatmap", source: "pts", paint: { "heatmap-radius": 22, "heatmap-opacity": 0.8 } });
        else {
          map.addLayer({ id: "pts-cluster", type: "circle", source: "pts", filter: ["has", "point_count"], paint: { "circle-color": "#e0aa46", "circle-opacity": 0.75, "circle-radius": ["step", ["get", "point_count"], 12, 10, 16, 50, 22] } });
          map.addLayer({ id: "pts", type: "circle", source: "pts", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": 5, "circle-color": ["match", ["get", "_kind"], "annotation", "#e86262", "#58a6de"], "circle-stroke-width": 1, "circle-stroke-color": "#0d1419" } });
        }
      } catch (e) { setErr(e); }
    };
    if (map.isStyleLoaded()) apply(); else map.once("load", apply);
  }, [pid, active, heat, cluster, time, theme]);

  // interactions
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const onClick = async (e: maplibregl.MapMouseEvent) => {
      const { lng, lat } = e.lngLat;
      const m = modeRef.current;
      try {
        if (m === "inspect") {
          const feats = map.queryRenderedFeatures(e.point, { layers: ["pts", "pts-cluster", "shapes-fill"].filter((l) => map.getLayer(l)) });
          if (!feats.length) return;
          const f: any = feats[0];
          if (f.properties.cluster) {
            const z = await (map.getSource("pts") as GeoJSONSource).getClusterExpansionZoom(f.properties.cluster_id);
            map.easeTo({ center: f.geometry.coordinates, zoom: z });
            return;
          }
          const props = Object.entries(f.properties).filter(([k]) => !k.startsWith("_")).slice(0, 10).map(([k, v]) => `<div><b>${k}</b>: ${String(v).replace(/</g, "&lt;")}</div>`).join("");
          new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<div><b>${String(f.properties._name ?? "").replace(/</g, "&lt;")}</b> <i>${f.properties._layer}</i>${props}</div>`).addTo(map);
        } else if (m === "radius") {
          setResult({ kind: "radius", ...(await api(pp(pid, "/geo/radius"), { params: { lon: lng, lat, radius_m: radiusM, layer: active } })) });
        } else if (m === "measure") {
          setMeasure((prev) => {
            const next = prev.length >= 2 ? [[lng, lat] as [number, number]] : [...prev, [lng, lat] as [number, number]];
            if (next.length === 2) api(pp(pid, "/geo/distance"), { params: { lon1: next[0][0], lat1: next[0][1], lon2: next[1][0], lat2: next[1][1] } })
              .then((d) => setResult({ kind: "distance", ...d, points: next }));
            return next;
          });
        } else if (m === "annotate") {
          const name = prompt("Annotation label:");
          if (!name) return;
          await api(pp(pid, "/geo/features"), { body: { name, layer: "annotations", geometry: { type: "Point", coordinates: [lng, lat] } } });
          layers.refetch();
          setActive((a) => (a.includes("annotations") ? [...a] : [...a, "annotations"]));
        }
      } catch (x) { setErr(x); }
    };
    map.on("click", onClick);
    return () => { map.off("click", onClick); };
  }, [pid, radiusM, active, layers]);

  const runJoin = async () => {
    try { setResult({ kind: "join", ...(await api(pp(pid, "/geo/join"), { params: { point_layer: join.points, polygon_layer: join.polygons } })) }); } catch (e) { setErr(e); }
  };
  const importLayer = async (f: File) => {
    const name = prompt("Layer name:", f.name.replace(/\.[^.]+$/, ""));
    if (!name) return;
    const fd = new FormData();
    fd.append("layer", name);
    fd.append("file", f);
    try { await api(pp(pid, "/geo/layers"), { form: fd }); layers.refetch(); setActive((a) => [...a, name]); } catch (e) { setErr(e); }
  };

  return (
    <div className="flex h-full flex-col gap-2">
      <PageHeader title="Geospatial Explorer" subtitle="Offline basemap (Natural Earth, bundled). Points come only from recorded coordinates — missing coordinates are never inferred; no live tracking." />
      <ErrorBox error={err} />
      <div className="card min-h-0 flex-1 overflow-hidden">
        <SplitPane id="geo" initial={0.74} left={<div ref={box} className="h-full w-full" aria-label="Map" />} right={
          <div className="space-y-3 p-3 text-xs">
            <div>
              <h3 className="label">Layers</h3>
              {(layers.data ?? []).map((l) => <label key={l.layer} className="flex items-center gap-1.5"><input type="checkbox" checked={active.includes(l.layer)}
                onChange={(e) => setActive(e.target.checked ? [...active, l.layer] : active.filter((x) => x !== l.layer))} />{l.layer} <span className="text-muted">({fmtNum(l.count)} · {l.kind})</span></label>)}
              {!layers.data?.length && <p className="text-muted">No geodata yet. Map latitude/longitude fields during ingestion or import GeoJSON.</p>}
              {canWrite && <label className="btn mt-2 cursor-pointer">Import GeoJSON<input type="file" accept=".geojson,.json" className="hidden" onChange={(e) => e.target.files?.[0] && importLayer(e.target.files[0])} /></label>}
            </div>
            <div className="flex gap-3"><label className="flex items-center gap-1"><input type="checkbox" checked={heat} onChange={(e) => setHeat(e.target.checked)} />heatmap</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={cluster} onChange={(e) => setCluster(e.target.checked)} />clustering</label></div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Time from"><input className="input" type="date" value={time.start} onChange={(e) => setTime({ ...time, start: e.target.value })} /></Field>
              <Field label="Time to"><input className="input" type="date" value={time.end} onChange={(e) => setTime({ ...time, end: e.target.value })} /></Field>
            </div>
            <div>
              <h3 className="label">Click mode</h3>
              <div className="flex flex-wrap gap-1">{(["inspect", "radius", "measure", "annotate"] as Mode[]).filter((m) => m !== "annotate" || canWrite).map((m) =>
                <button key={m} className={`btn ${mode === m ? "btn-primary" : ""}`} onClick={() => setMode(m)}>{m}</button>)}</div>
              {mode === "radius" && <Field label="Radius (m)"><input className="input" type="number" value={radiusM} onChange={(e) => setRadiusM(Number(e.target.value))} /></Field>}
              {mode === "measure" && <p className="mt-1 text-muted">Click two points. {measure.length === 1 && "First point set."}</p>}
            </div>
            <div className="space-y-1">
              <h3 className="label">Spatial join (points in polygons)</h3>
              <select className="input" value={join.points} onChange={(e) => setJoin({ ...join, points: e.target.value })}><option value="">point layer…</option>{(layers.data ?? []).map((l) => <option key={l.layer}>{l.layer}</option>)}</select>
              <select className="input" value={join.polygons} onChange={(e) => setJoin({ ...join, polygons: e.target.value })}><option value="">polygon layer…</option>{(layers.data ?? []).map((l) => <option key={l.layer}>{l.layer}</option>)}</select>
              <button className="btn" disabled={!join.points || !join.polygons} onClick={runJoin}>Run join</button>
            </div>
            {result?.kind === "radius" && <div><h3 className="label">{result.results.length} within {fmtNum(result.radius_m)} m</h3>
              <Table maxHeight={220} columns={["Name", "Layer", "Distance"]} rows={result.results.map((r: any) => [r.properties._name, r.properties._layer, `${fmtNum(r.distance_m)} m`])} />
              <p className="text-[10px] text-muted">{result.method}</p></div>}
            {result?.kind === "distance" && <Notice>Distance: <b>{fmtNum(result.distance_m / 1000, 3)} km</b> ({result.method})</Notice>}
            {result?.kind === "join" && <div><h3 className="label">Join: {result.points} points, {result.unmatched_points} outside all polygons</h3>
              <Table columns={["Polygon", "Points"]} rows={result.by_polygon.map((p: any) => [p.polygon_name, p.point_count])} />
              <p className="text-[10px] text-muted">{result.method}</p></div>}
            <Badge tone="ok">offline basemap · no network tiles</Badge>
          </div>
        } />
      </div>
    </div>
  );
}
