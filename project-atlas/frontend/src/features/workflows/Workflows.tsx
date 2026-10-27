import { useCallback, useEffect, useMemo, useState } from "react";
import { addEdge, Background, Connection, Controls, Edge, Handle, Node, NodeProps, Position, ReactFlow, useEdgesState, useNodesState } from "@xyflow/react";
import { api, pp, waitForJob } from "../../services/api";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, Json, Notice, PageHeader, StatusBadge, Table } from "../../components/ui";

type Spec = { type: string; label: string; inputs: Record<string, string>; output: string; params: Record<string, any>; side_effect: boolean; writes_data: boolean; permission: string };

function AtlasNode({ data, selected }: NodeProps) {
  const d = data as { spec: Spec; status?: string; id: string };
  const inputs = Object.entries(d.spec.inputs);
  return (
    <div className={`min-w-[150px] rounded-md border bg-panel px-2 py-1.5 text-[11px] text-ink shadow ${selected ? "border-accent" : "border-line"}`}>
      {inputs.map(([port, type], i) => (
        <Handle key={port} type="target" id={port} position={Position.Left} style={{ top: 14 + i * 14, background: "#58a6de" }} title={`${port}: ${type}`} />
      ))}
      <div className="flex items-center justify-between gap-2"><b>{d.spec.label}</b>{d.spec.side_effect && <span title="side effects" className="text-warn">⚠</span>}</div>
      <div className="font-mono text-[9px] text-muted">{d.id} → {d.spec.output}</div>
      {inputs.length > 1 && <div className="text-[9px] text-muted">{inputs.map(([p]) => p).join(" / ")}</div>}
      {d.status && <div className="mt-0.5"><StatusBadge status={d.status} /></div>}
      <Handle type="source" position={Position.Right} style={{ background: "#e0aa46" }} />
    </div>
  );
}
const nodeTypes = { atlas: AtlasNode };

export function WorkflowsPage() {
  const pid = useProjectId();
  const catalog = usePQuery<Spec[]>(["wf-catalog"], "/workflows/catalog");
  const list = usePQuery<any[]>(["workflows"], "/workflows");
  const datasets = usePQuery<any[]>(["datasets"], "/datasets");
  const reports = usePQuery<any[]>(["reports"], "/reports");
  const canWrite = useCan("workflow.write");
  const [wfId, setWfId] = useState<string | null>(null);
  const [name, setName] = useState("New workflow");
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [runInfo, setRunInfo] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [versions, setVersions] = useState<any[]>([]);
  const specs = useMemo(() => Object.fromEntries((catalog.data ?? []).map((s) => [s.type, s])), [catalog.data]);

  const definition = useCallback(() => ({
    nodes: nodes.map((n) => ({ id: n.id, type: (n.data as any).spec.type, params: (n.data as any).params, position: n.position })),
    edges: edges.map((e) => ({ source: e.source, target: e.target, target_port: e.targetHandle ?? undefined })),
  }), [nodes, edges]);

  const load = async (id: string, version?: number) => {
    setErr(null); setResult(null);
    const w = await api(pp(pid, `/workflows/${id}`), { params: { version } });
    setWfId(id); setName(w.name); setVersions(w.versions);
    setNodes(w.definition.nodes.map((n: any, i: number) => ({ id: n.id, type: "atlas", position: n.position ?? { x: 40 + (i % 4) * 220, y: 40 + Math.floor(i / 4) * 120 },
      data: { id: n.id, spec: specs[n.type], params: n.params ?? {} } })));
    setEdges(w.definition.edges.map((e: any, i: number) => ({ id: `e${i}`, source: e.source, target: e.target, targetHandle: e.target_port ?? Object.keys(specs[w.definition.nodes.find((n: any) => n.id === e.target).type].inputs)[0] })));
    setRunInfo({ runs: w.runs });
  };

  const addNode = (spec: Spec) => {
    let i = nodes.length + 1;
    while (nodes.some((n) => n.id === `${spec.type}_${i}`)) i++;
    const id = `${spec.type}_${i}`;
    setNodes([...nodes, { id, type: "atlas", position: { x: 60 + (nodes.length % 4) * 220, y: 60 + Math.floor(nodes.length / 4) * 120 }, data: { id, spec, params: {} } }]);
    setSel(id);
  };
  const onConnect = useCallback((c: Connection) => setEdges((es) => addEdge({ ...c, id: `e${Date.now()}` }, es)), [setEdges]);
  const setParams = (id: string, params: any) => setNodes(nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, params } } : n)));
  const selected = nodes.find((n) => n.id === sel);

  const call = async (fn: () => Promise<void>) => { setErr(null); try { await fn(); } catch (e) { setErr(e); } };
  const validate = () => call(async () => { const r = await api(pp(pid, "/workflows/validate"), { body: { name, definition: definition() } }); setResult({ validated: r.order }); });
  const save = () => call(async () => {
    const r = wfId ? await api(pp(pid, `/workflows/${wfId}`), { method: "PUT", body: { name, definition: definition() } })
      : await api(pp(pid, "/workflows"), { body: { name, definition: definition() } });
    setWfId(r.id); list.refetch(); await load(r.id);
  });
  const paint = (res: any) => setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, status: res?.[n.id]?.status } })));
  const preview = () => call(async () => { const r = await api(pp(pid, `/workflows/${wfId}/preview`), { body: {} }); setResult(r); paint(r.nodes); });
  const run = () => call(async () => {
    const needs = nodes.some((n) => (n.data as any).spec.side_effect);
    if (needs && !confirm("This workflow writes data or exports files. Run it for real?")) return;
    const r = await api(pp(pid, `/workflows/${wfId}/runs`), { body: { confirm: needs } });
    await waitForJob(r.job_id);
    const detail = await api(pp(pid, `/workflows/${wfId}/runs/${r.run_id}`));
    setResult({ ...detail, nodes: detail.node_results });
    paint(detail.node_results);
  });
  useEffect(() => { setResult(null); }, [wfId]);

  return (
    <div className="flex h-full flex-col gap-2">
      <PageHeader title="Workflows" subtitle="Typed, versioned node graphs executing real backend operations. Preview runs on ≤200 rows and skips side effects."
        actions={<>
          <select className="input w-56" value={wfId ?? ""} onChange={(e) => e.target.value ? load(e.target.value) : (setWfId(null), setNodes([]), setEdges([]), setName("New workflow"))}>
            <option value="">New workflow</option>{(list.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name} (v{w.current_version})</option>)}</select>
          {wfId && versions.length > 1 && <select className="input w-24" onChange={(e) => load(wfId, Number(e.target.value))}>{versions.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}</select>}
          <input className="input w-48" value={name} onChange={(e) => setName(e.target.value)} aria-label="Workflow name" />
          <button className="btn" onClick={validate}>Validate</button>
          {canWrite && <button className="btn" onClick={save}>{wfId ? "Save new version" : "Save"}</button>}
          <button className="btn" disabled={!wfId} onClick={preview}>Preview</button>
          <button className="btn btn-primary" disabled={!wfId} onClick={run}>Run</button>
        </>} />
      <ErrorBox error={err} />
      <div className="grid min-h-0 flex-1 gap-2 xl:grid-cols-[180px_1fr_340px]">
        <Card title="Nodes" bodyClass="max-h-full overflow-auto p-2">
          {(catalog.data ?? []).map((s) => (
            <button key={s.type} className="mb-1 block w-full rounded border border-line px-2 py-1 text-left text-xs hover:border-accent" onClick={() => addNode(s)}>
              {s.label} <span className="block font-mono text-[9px] text-muted">{Object.values(s.inputs).join(",") || "∅"} → {s.output}{s.side_effect ? " ⚠" : ""}</span>
            </button>
          ))}
        </Card>
        <div className="card min-h-[420px] overflow-hidden">
          <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            nodeTypes={nodeTypes} onNodeClick={(_, n) => setSel(n.id)} fitView colorMode="dark" deleteKeyCode={["Backspace", "Delete"]}>
            <Background gap={16} size={1} />
            <Controls />
          </ReactFlow>
        </div>
        <div className="min-h-0 space-y-2 overflow-auto">
          {selected && (
            <Card title={`Parameters · ${selected.id}`}>
              <ParamEditor spec={(selected.data as any).spec} params={(selected.data as any).params} datasets={datasets.data ?? []} reports={reports.data ?? []}
                onChange={(p) => setParams(selected.id, p)} />
            </Card>
          )}
          {result?.validated && <Notice tone="ok">Valid. Execution order: {result.validated.join(" → ")}</Notice>}
          {result?.nodes && (
            <Card title={<>Results {result.preview && <Badge tone="accent">preview</Badge>} {result.status && <StatusBadge status={result.status} />}</>}>
              {Object.entries(result.nodes).map(([id, r]: [string, any]) => (
                <details key={id} className="mb-1 text-xs" open={r.status === "failed"}>
                  <summary className="cursor-pointer"><b>{id}</b> <StatusBadge status={r.status} /> {r.duration_ms != null && <span className="text-muted">{r.duration_ms} ms</span>} {r.error && <span className="text-danger">{r.error}</span>}</summary>
                  {r.output?.kind === "table" ? <><p className="text-muted">{r.output.rows} rows · {r.output.columns.length} columns</p>
                    <Table maxHeight={160} columns={r.output.columns.slice(0, 6)} rows={r.output.sample.slice(0, 8).map((s: any) => r.output.columns.slice(0, 6).map((c: string) => String(s[c] ?? "")))} /></>
                    : r.output ? <Json value={r.output.value} max={180} /> : r.reason && <p className="text-muted">{r.reason}</p>}
                </details>
              ))}
              {(result.logs ?? []).length > 0 && <details><summary className="label cursor-pointer">Logs</summary>{result.logs.map((l: any, i: number) => <p key={i} className="font-mono text-xxs">{l.at.slice(11, 19)} {l.node} {l.level}: {l.message}</p>)}</details>}
            </Card>
          )}
          {runInfo?.runs?.length > 0 && <Card title="Recent runs" bodyClass=""><Table columns={["When", "Status"]} rows={runInfo.runs.map((r: any) => [r.created_at.slice(0, 19), <StatusBadge status={r.status} />])} /></Card>}
        </div>
      </div>
    </div>
  );
}

function ParamEditor({ spec, params, datasets, reports, onChange }: { spec: Spec; params: any; datasets: any[]; reports: any[]; onChange: (p: any) => void }) {
  const [raw, setRaw] = useState(JSON.stringify(params, null, 2));
  useEffect(() => setRaw(JSON.stringify(params, null, 2)), [params]);
  return (
    <div className="space-y-2 text-xs">
      {Object.entries(spec.params).map(([k, p]) => {
        const v = params[k] ?? "";
        const set = (val: any) => onChange({ ...params, [k]: val === "" ? undefined : val });
        const label = `${k}${p.required ? " *" : ""} (${p.type})`;
        if (p.type === "dataset") return <Field key={k} label={label}><select className="input" value={v} onChange={(e) => set(e.target.value)}><option value="">Select…</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>;
        if (p.type === "report") return <Field key={k} label={label}><select className="input" value={v} onChange={(e) => set(e.target.value)}><option value="">Select…</option>{reports.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}</select></Field>;
        if (p.type === "enum") return <Field key={k} label={label}><select className="input" value={v} onChange={(e) => set(e.target.value)}><option value="">—</option>{p.options.map((o: string) => <option key={o}>{o}</option>)}</select></Field>;
        if (p.type === "boolean") return <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} />{k}</label>;
        if (p.type === "fields") return <Field key={k} label={`${label} — comma separated`}><input className="input" value={(v || []).join?.(",") ?? v} onChange={(e) => set(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} /></Field>;
        if (["conditions", "object"].includes(p.type)) return null;
        return <Field key={k} label={label}><input className="input" value={v} onChange={(e) => set(p.type === "integer" || p.type === "number" ? Number(e.target.value) : e.target.value)} /></Field>;
      })}
      {Object.values(spec.params).some((p) => ["conditions", "object"].includes(p.type)) && (
        <Field label="All parameters (JSON)" hint='e.g. {"conditions": [{"field": "amount", "op": "gt", "value": 1000}]}'>
          <textarea className="input h-28 font-mono" value={raw} onChange={(e) => setRaw(e.target.value)} onBlur={() => { try { onChange(JSON.parse(raw)); } catch { /* keep editing */ } }} />
        </Field>
      )}
      <p className="text-[10px] text-muted">Requires permission <code>{spec.permission}</code>{spec.side_effect ? " · has side effects (skipped in preview, needs confirmation)" : ""}. Add <code>retries</code> for transient failures.</p>
    </div>
  );
}
