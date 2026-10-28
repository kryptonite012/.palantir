import { useEffect, useMemo, useRef, useState } from "react";
import { askText, toast } from "../../components/feedback";
import { useNavigate, useSearchParams } from "react-router-dom";
import cytoscape, { Core } from "cytoscape";
import { api, download, pp } from "../../services/api";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { AssertionBadge, Badge, ErrorBox, Field, Json, Notice, PageHeader, SplitPane, Spinner } from "../../components/ui";
import type { GraphEdge, GraphNode } from "../../types/api";

const TYPE_COLORS: Record<string, string> = {
  person: "#58a6de", organization: "#e0aa46", location: "#56be88", event: "#b88ce8", document: "#9aa7b4",
  account: "#e86262", asset: "#c8b46e", transaction: "#d67fb4", device: "#6fc3c3", project: "#8fa8e8",
};
const EDGE_STYLE: Record<string, { style: string; color: string }> = {
  observed: { style: "solid", color: "#6b7b8c" }, inferred: { style: "dashed", color: "#58a6de" },
  model_suggested: { style: "dotted", color: "#b88ce8" }, manual: { style: "dashed", color: "#e0aa46" },
};

export function GraphPage() {
  const pid = useProjectId();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const center = params.get("center");
  const [depth, setDepth] = useState(1);
  const [limit, setLimit] = useState(150);
  const [relTypes, setRelTypes] = useState<string[]>([]);
  const [assertions, setAssertions] = useState<string[]>([]);
  const [unverified, setUnverified] = useState(false);
  const [data, setData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[]; truncated?: boolean; total_nodes?: number } | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [edgeSel, setEdgeSel] = useState<string | null>(null);
  const [algo, setAlgo] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const cyRef = useRef<Core | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const onto = usePQuery<any>(["ontology"], "/ontology");
  const snaps = usePQuery<any[]>(["snapshots"], "/graph/snapshots");
  const canWrite = useCan("graph.write");
  const canExport = useCan("report.export");

  const load = async (merge = false, c = center) => {
    setLoading(true);
    setErr(null);
    try {
      const r = await api(pp(pid, "/graph"), { params: { center: c, depth, limit, rel_type: relTypes, assertion: assertions, include_unverified: unverified } });
      if (merge && data) {
        const nodes = new Map(data.nodes.map((n) => [n.id, n]));
        r.nodes.forEach((n: GraphNode) => nodes.set(n.id, n));
        const edges = new Map(data.edges.map((e) => [e.id, e]));
        r.edges.forEach((e: GraphEdge) => edges.set(e.id, e));
        setData({ nodes: [...nodes.values()], edges: [...edges.values()] });
      } else setData(r);
    } catch (e) { setErr(e); } finally { setLoading(false); }
  };
  useEffect(() => { if (pid) load(); /* eslint-disable-next-line */ }, [pid, center, depth, limit, relTypes, assertions, unverified]);

  useEffect(() => {
    if (!boxRef.current || !data) return;
    const cy = cytoscape({
      container: boxRef.current,
      elements: [
        ...data.nodes.map((n) => ({ data: { id: n.id, label: n.label, type: n.entity_type, degree: n.degree ?? 1 } })),
        ...data.edges.map((e) => ({ data: { id: e.id, source: e.source, target: e.target, label: e.rel_type, assertion: e.assertion } })),
      ],
      style: [
        { selector: "node", style: { "background-color": (el: any) => TYPE_COLORS[el.data("type")] ?? "#8899aa", label: "data(label)",
          color: "#c9d3dd", "font-size": 8, "text-valign": "bottom", "text-margin-y": 3, width: (el: any) => 10 + Math.min(24, (el.data("score") ?? 0) * 60 + Math.sqrt(el.data("degree") ?? 1) * 2),
          height: (el: any) => 10 + Math.min(24, (el.data("score") ?? 0) * 60 + Math.sqrt(el.data("degree") ?? 1) * 2), "border-width": 0 } },
        { selector: "node[community]", style: { "border-width": 3, "border-color": (el: any) => `hsl(${(el.data("community") * 67) % 360},70%,60%)` } },
        { selector: "node:selected", style: { "border-width": 3, "border-color": "#ffffff" } },
        { selector: "edge", style: { width: 1, "curve-style": "bezier", "target-arrow-shape": "triangle", "arrow-scale": 0.6,
          "line-style": (el: any) => EDGE_STYLE[el.data("assertion")]?.style ?? "solid",
          "line-color": (el: any) => EDGE_STYLE[el.data("assertion")]?.color ?? "#6b7b8c",
          "target-arrow-color": (el: any) => EDGE_STYLE[el.data("assertion")]?.color ?? "#6b7b8c", opacity: 0.8 } },
        { selector: "edge:selected", style: { width: 3, "line-color": "#ffffff" } },
        { selector: ".path", style: { "line-color": "#e86262", "target-arrow-color": "#e86262", width: 3, "background-color": "#e86262" } },
        { selector: ".faded", style: { opacity: 0.15 } },
      ] as any,
      layout: { name: "cose", animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 60 } as any,
      wheelSensitivity: 0.25,
      boxSelectionEnabled: true,
    });
    cy.on("select unselect", "node", () => setSelected(cy.$("node:selected").map((n) => n.id())));
    cy.on("tap", "edge", (e) => setEdgeSel(e.target.id()));
    cy.on("dbltap", "node", (e) => setParams({ center: e.target.id() }));
    cyRef.current = cy;
    (window as unknown as { __atlasCy?: Core }).__atlasCy = cy; // used by the end-to-end test to select nodes
    return () => cy.destroy();
  }, [data, setParams]);

  const runAlgo = async (algorithm: string) => {
    setErr(null);
    try {
      const p: any = { rel_types: relTypes.length ? relTypes : undefined, assertions: assertions.length ? assertions : undefined, include_unverified: unverified, top: 50 };
      if (algorithm === "shortest_path") { if (selected.length !== 2) throw new Error("Select exactly two nodes (shift-click) first"); p.source = selected[0]; p.target = selected[1]; }
      const r = await api(pp(pid, "/graph/analyze"), { body: { algorithm, params: p } });
      setAlgo(r);
      const cy = cyRef.current;
      if (!cy) return;
      cy.elements().removeClass("path faded");
      cy.nodes().removeData("score community");
      if (r.result.ranking) r.result.ranking.forEach((x: any) => cy.$id(x.entity_id).data("score", x.score));
      if (r.result.communities) r.result.communities.forEach((c: any, i: number) => c.members.forEach((m: any) => cy.$id(m.entity_id).data("community", i + 1)));
      if (r.result.paths?.length) {
        const path = r.result.paths[0].map((x: any) => x.entity_id);
        cy.elements().addClass("faded");
        path.forEach((id: string, i: number) => {
          cy.$id(id).removeClass("faded").addClass("path");
          if (i) cy.edges().filter((e) => (e.source().id() === path[i - 1] && e.target().id() === id) || (e.target().id() === path[i - 1] && e.source().id() === id)).removeClass("faded").addClass("path");
        });
      }
    } catch (e) { setErr(e); }
  };

  const saveSnapshot = async () => {
    const name = await askText({ title: "Save graph snapshot", label: "Name", confirmText: "Save" });
    if (!name || !cyRef.current) return;
    const ids = selected.length ? selected : cyRef.current.nodes().map((n) => n.id());
    const layout = Object.fromEntries(cyRef.current.nodes().map((n) => [n.id(), n.position()]));
    try { await api(pp(pid, "/graph/snapshots"), { body: { name, node_ids: ids, layout, filters: { relTypes, assertions, unverified, center } } }); snaps.refetch(); toast.ok(`Snapshot “${name}” saved (${ids.length} nodes)`); } catch (e) { setErr(e); }
  };
  const loadSnapshot = async (id: string) => {
    const s = await api(pp(pid, `/graph/snapshots/${id}`));
    setData({ nodes: s.nodes, edges: s.edges });
    setTimeout(() => cyRef.current?.nodes().forEach((n) => { const p = s.layout?.[n.id()]; if (p) n.position(p); }), 50);
  };
  const exportGraph = (fmt: string) => {
    const ids = selected.length ? selected : (data?.nodes ?? []).map((n) => n.id);
    download(pp(pid, "/graph/export"), `atlas-subgraph.${fmt}`, { method: "POST", body: { name: "export", node_ids: ids }, params: { fmt } }).catch(setErr);
  };

  const [explain, setExplain] = useState<any>(null);
  const runExplain = async () => {
    setErr(null);
    try {
      if (selected.length !== 2) throw new Error("Select exactly two nodes (shift-click) to explain how they connect");
      const r = await api(pp(pid, "/graph/explain"), { params: { source: selected[0], target: selected[1], include_unverified: unverified } });
      setExplain(r);
      const cy = cyRef.current;
      if (cy && r.paths[0]) {
        const path = r.paths[0].nodes.map((n: any) => n.id);
        cy.elements().removeClass("path faded").addClass("faded");
        path.forEach((id: string, i: number) => {
          cy.$id(id).removeClass("faded").addClass("path");
          if (i) cy.edges().filter((ed) => [ed.source().id(), ed.target().id()].sort().join() === [path[i - 1], id].sort().join()).removeClass("faded").addClass("path");
        });
      }
    } catch (e) { setErr(e); }
  };
  const nodeDetail = usePQuery<any>(["entity", selected[selected.length - 1]], `/entities/${selected[selected.length - 1]}`, undefined, selected.length > 0);
  const edgeDetail = usePQuery<any>(["rel", edgeSel], `/relationships/${edgeSel}`, undefined, !!edgeSel);
  const relTypeOptions = useMemo(() => (onto.data?.relationship_types ?? []).map((r: any) => r.name), [onto.data]);

  return (
    <div className="flex h-full flex-col gap-2">
      <PageHeader title="Knowledge Graph" subtitle={<>Server-side filtering, progressive loading{data?.truncated ? <> · <Badge tone="warn">showing {data.nodes.length} of {data.total_nodes ?? "more"} nodes</Badge></> : null}. Double-click a node to focus; shift/box-select for multi-select.</>}
        actions={<>
          {center && <button className="btn" onClick={() => setParams({})}>Overview</button>}
          {canWrite && <button className="btn" onClick={saveSnapshot}>Save snapshot</button>}
          {canExport && <><button className="btn" onClick={() => exportGraph("graphml")}>GraphML</button><button className="btn" onClick={() => exportGraph("json")}>JSON</button><button className="btn" onClick={() => exportGraph("gexf")}>GEXF</button></>}
        </>} />
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <Field label="Depth"><input className="input w-16" type="number" min={1} max={4} value={depth} onChange={(e) => setDepth(Number(e.target.value))} /></Field>
        <Field label="Node limit"><input className="input w-20" type="number" min={10} max={2000} step={50} value={limit} onChange={(e) => setLimit(Number(e.target.value))} /></Field>
        <Field label="Relationship types"><select multiple className="input h-16 w-48" value={relTypes} onChange={(e) => setRelTypes([...e.target.selectedOptions].map((o) => o.value))}>
          {relTypeOptions.map((r: string) => <option key={r}>{r}</option>)}</select></Field>
        <Field label="Basis"><select multiple className="input h-16 w-44" value={assertions} onChange={(e) => setAssertions([...e.target.selectedOptions].map((o) => o.value))}>
          {Object.keys(EDGE_STYLE).map((a) => <option key={a}>{a}</option>)}</select></Field>
        <label className="flex items-center gap-1"><input type="checkbox" checked={unverified} onChange={(e) => setUnverified(e.target.checked)} /> include unverified hypotheses</label>
        {center && <button className="btn" onClick={() => load(true, selected[0] ?? center)}>Expand selection</button>}
        <span className="mx-2 h-6 border-l border-line" />
        <button className="btn btn-primary" onClick={runExplain} title="Select two nodes first">Explain connection</button>
        {["degree_centrality", "pagerank", "betweenness_centrality", "communities", "connected_components", "shortest_path"].map((a) =>
          <button key={a} className="btn" onClick={() => runAlgo(a)}>{a.replace("_", " ")}</button>)}
      </div>
      <ErrorBox error={err} />
      <div className="card min-h-0 flex-1 overflow-hidden">
        <SplitPane id="graph" initial={0.72} left={
          <div className="relative h-full">
            {loading && <div className="absolute left-2 top-2 z-10"><Spinner label="Loading graph…" /></div>}
            <div ref={boxRef} className="h-full w-full" aria-label="Graph canvas" />
            <div className="absolute bottom-2 left-2 flex flex-wrap gap-2 rounded bg-panel/80 p-1.5 text-[10px]">
              {Object.entries(EDGE_STYLE).map(([k, v]) => <span key={k} className="flex items-center gap-1"><span style={{ borderTop: `2px ${v.style} ${v.color}`, width: 16 }} />{k}</span>)}
              {Object.entries(TYPE_COLORS).slice(0, 5).map(([k, c]) => <span key={k} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: c }} />{k}</span>)}
            </div>
          </div>
        } right={
          <div className="space-y-3 p-3 text-xs">
            {explain && (
              <div className="space-y-2">
                <div className="flex items-center justify-between"><h3 className="label">How {explain.source.label} connects to {explain.target.label}</h3>
                  <button className="btn btn-ghost" onClick={() => { setExplain(null); cyRef.current?.elements().removeClass("path faded"); }}>✕</button></div>
                {!explain.found && <p className="text-muted">No path in the current graph{unverified ? "" : " (unverified hypotheses excluded)"}.</p>}
                {explain.paths.map((p: any, pi: number) => (
                  <div key={pi} className="rounded border border-line p-2">
                    <p className="mb-1 font-medium">Path {pi + 1} · {p.length} hop{p.length === 1 ? "" : "s"} {p.all_observed ? <Badge tone="ok">all observed</Badge> : <Badge tone="warn">includes {p.bases.filter((b: string) => b !== "observed").join(", ")}</Badge>}</p>
                    <ol className="space-y-1.5">
                      {p.hops.map((h: any, hi: number) => (
                        <li key={hi} className="border-l-2 border-accent/40 pl-2">
                          <span><b>{h.from.label}</b> → <b>{h.to.label}</b></span>
                          {h.relationships.map((r: any) => (
                            <div key={r.id} className="mt-0.5 text-[11px]">
                              <span className="font-mono">{r.rel_type}</span> <AssertionBadge kind={r.assertion} status={r.status} /> <span className="text-muted">{r.evidence_count} evidence</span>
                              {r.evidence_sample?.restricted ? <p className="text-warn">Evidence in a restricted dataset</p>
                                : r.evidence_sample?.text && <p className="truncate text-muted" title={r.evidence_sample.text}>{r.evidence_sample.dataset ? `${r.evidence_sample.dataset} row ${r.evidence_sample.row_index + 1}: ` : ""}{r.evidence_sample.text}</p>}
                            </div>
                          ))}
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
                <Notice tone="warn">{explain.note}</Notice>
              </div>
            )}
            {edgeDetail.data && edgeSel && (
              <div className="space-y-1">
                <h3 className="label">Relationship</h3>
                <p><b>{edgeDetail.data.source.display_name}</b> —{edgeDetail.data.rel_type}→ <b>{edgeDetail.data.target.display_name}</b></p>
                <AssertionBadge kind={edgeDetail.data.assertion} status={edgeDetail.data.status} />
                <p className="text-muted">{edgeDetail.data.how_created}. Created {edgeDetail.data.created_at} by {edgeDetail.data.created_by}.</p>
                {edgeDetail.data.valid_from && <p>Valid {edgeDetail.data.valid_from} → {edgeDetail.data.valid_to ?? "…"}</p>}
                {edgeDetail.data.evidence_records?.length > 0 && <p>Evidence: {edgeDetail.data.evidence_records.length} source record(s) in {[...new Set(edgeDetail.data.evidence_records.map((r: any) => r.dataset))].join(", ")}</p>}
                <Json value={edgeDetail.data.evidence} max={160} />
              </div>
            )}
            {selected.length > 0 && nodeDetail.data && (
              <div className="space-y-1">
                <h3 className="label">Entity {selected.length > 1 && `(${selected.length} selected)`}</h3>
                <p className="text-sm font-semibold">{nodeDetail.data.display_name} <Badge>{nodeDetail.data.entity_type}</Badge></p>
                {Object.entries(nodeDetail.data.attributes).slice(0, 8).map(([k, v]: any) => <p key={k}><span className="text-muted">{k}:</span> {v.join(" | ")}</p>)}
                <p>{nodeDetail.data.source_records.length} source records · {nodeDetail.data.relationships.length} relationships · {nodeDetail.data.linked_documents.length} documents</p>
                {nodeDetail.data.quality_warnings.length > 0 && <Badge tone="warn">{nodeDetail.data.quality_warnings.length} quality warnings</Badge>}
                <div className="flex gap-1 pt-1"><button className="btn" onClick={() => nav(`/entities/${nodeDetail.data.id}`)}>Full details</button>
                  <button className="btn" onClick={() => setParams({ center: nodeDetail.data.id })}>Focus</button></div>
              </div>
            )}
            {algo && (
              <div className="space-y-1">
                <h3 className="label">{algo.kind}</h3>
                <p className="text-muted">Run {algo.id.slice(-8)} · {algo.algorithm_version} · {algo.duration_ms} ms · n={algo.result.sample_size?.nodes}</p>
                {algo.result.ranking && <ol className="list-decimal pl-4">{algo.result.ranking.slice(0, 12).map((r: any) => <li key={r.entity_id}>{r.label} <span className="font-mono text-muted">{r.score.toFixed(4)}</span></li>)}</ol>}
                {algo.result.count != null && <p>{algo.result.count} groups; sizes {(algo.result.sizes ?? algo.result.communities?.map((c: any) => c.size) ?? []).slice(0, 10).join(", ")}</p>}
                {algo.result.paths && <p>{algo.result.found ? `Path length ${algo.result.length}: ${algo.result.paths[0].map((x: any) => x.label).join(" → ")}` : "No path in the filtered graph."}</p>}
                {algo.result.note && <Notice tone="warn">{algo.result.note}</Notice>}
                <p className="text-[10px] text-muted">{algo.result.limitations}</p>
              </div>
            )}
            <div>
              <h3 className="label">Snapshots</h3>
              {(snaps.data ?? []).map((s) => <button key={s.id} className="block text-accent hover:underline" onClick={() => loadSnapshot(s.id)}>{s.name} ({s.nodes} nodes)</button>)}
              {!snaps.data?.length && <p className="text-muted">None saved</p>}
            </div>
          </div>
        } />
      </div>
    </div>
  );
}
