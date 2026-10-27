import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, download, pp } from "../../services/api";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, Json, Notice, PageHeader, Table, fmtBytes, fmtTime } from "../../components/ui";
import { Chart } from "../../components/Chart";

type Section = Record<string, any> & { type: string };
const TEMPLATE: Section[] = [
  { type: "summary", title: "Executive summary", body: "" },
  { type: "methodology", title: "Methodology", body: "" },
  { type: "limitations", title: "Limitations", body: "Findings are limited to the datasets listed in the manifest. Statistical outliers are not evidence of wrongdoing." },
];

export function ReportsPage() {
  const pid = useProjectId();
  const [params] = useSearchParams();
  const reports = usePQuery<any[]>(["reports"], "/reports");
  const datasets = usePQuery<any[]>(["datasets"], "/datasets");
  const runs = usePQuery<any[]>(["analyses"], "/analyses");
  const snaps = usePQuery<any[]>(["snapshots"], "/graph/snapshots");
  const invs = usePQuery<any[]>(["investigations"], "/investigations");
  const canWrite = useCan("report.write");
  const canExport = useCan("report.export");
  const [id, setId] = useState<string | null>(params.get("id"));
  const [title, setTitle] = useState("Untitled report");
  const [sections, setSections] = useState<Section[]>(TEMPLATE);
  const [preview, setPreview] = useState<any>(null);
  const [exports, setExports] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const invParam = params.get("investigation");

  useEffect(() => {
    if (invParam && !id) setSections([...TEMPLATE.slice(0, 2), { type: "findings", investigation_id: invParam, title: "Findings" }, { type: "evidence", investigation_id: invParam, title: "Evidence register" }, TEMPLATE[2]]);
  }, [invParam, id]);
  useEffect(() => {
    if (!id) return;
    api(pp(pid, `/reports/${id}`)).then((r) => { setTitle(r.title); setSections(r.definition.sections); setExports(r.exports); }).catch(setErr);
  }, [id, pid]);

  const call = async (fn: () => Promise<void>) => { setErr(null); setBusy(true); try { await fn(); } catch (e) { setErr(e); } finally { setBusy(false); } };
  const save = () => call(async () => {
    const body = { title, definition: { sections }, investigation_id: invParam ?? undefined };
    const r = id ? await api(pp(pid, `/reports/${id}`), { method: "PUT", body }) : await api(pp(pid, "/reports"), { body });
    setId(r.id); reports.refetch();
  });
  const doPreview = () => call(async () => { await save(); setPreview(await api(pp(pid, `/reports/${id}/preview`), { method: "POST" })); });
  const doExport = (fmt: string) => call(async () => {
    const r = await api(pp(pid, `/reports/${id}/export`), { method: "POST", params: { fmt } });
    setExports([r, ...exports]);
    await download(pp(pid, `/reports/${id}/exports/${r.id}`), `${title.replace(/[^A-Za-z0-9_-]+/g, "_")}.${fmt}`);
  });
  const upd = (i: number, patch: Partial<Section>) => setSections(sections.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, d: number) => { const n = [...sections]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); setSections(n); };

  return (
    <div className="space-y-3">
      <PageHeader title="Reports" subtitle="Reproducible reports with a manifest of dataset versions, analysis parameters, timestamps and software versions."
        actions={<>
          <select className="input w-56" value={id ?? ""} onChange={(e) => { setPreview(null); if (e.target.value) setId(e.target.value); else { setId(null); setTitle("Untitled report"); setSections(TEMPLATE); setExports([]); } }}>
            <option value="">New report</option>{(reports.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select>
          {canWrite && <button className="btn" onClick={save} disabled={busy}>Save</button>}
          <button className="btn" onClick={doPreview} disabled={busy || !canWrite}>Preview</button>
          {canExport && id && ["pdf", "html", "xlsx", "csv", "json"].map((f) => <button key={f} className="btn" disabled={busy} onClick={() => doExport(f)}>{f.toUpperCase()}</button>)}
        </>} />
      <ErrorBox error={err} />
      <div className="grid gap-3 xl:grid-cols-2">
        <Card title={<input className="input w-80 text-sm font-semibold" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Report title" />}>
          <div className="space-y-2">
            {sections.map((s, i) => (
              <div key={i} className="rounded border border-line p-2 text-xs">
                <div className="mb-1 flex items-center gap-1"><Badge tone="accent">{s.type}</Badge>
                  <input className="input" value={s.title ?? ""} placeholder="Section title" onChange={(e) => upd(i, { title: e.target.value })} />
                  <button className="btn btn-ghost" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                  <button className="btn btn-ghost" disabled={i === sections.length - 1} onClick={() => move(i, 1)}>↓</button>
                  <button className="btn btn-ghost text-danger" onClick={() => setSections(sections.filter((_, j) => j !== i))}>✕</button></div>
                {["summary", "methodology", "text", "limitations", "appendix"].includes(s.type) && <textarea className="input" rows={3} value={s.body ?? ""} onChange={(e) => upd(i, { body: e.target.value })} />}
                {s.type === "dataset_table" && <div className="grid grid-cols-3 gap-1">
                  <select className="input" value={s.dataset_id ?? ""} onChange={(e) => upd(i, { dataset_id: e.target.value })}><option value="">dataset…</option>{(datasets.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
                  <input className="input" placeholder="columns (comma, optional)" value={(s.columns ?? []).join(",")} onChange={(e) => upd(i, { columns: e.target.value ? e.target.value.split(",").map((x) => x.trim()) : undefined })} />
                  <input className="input" type="number" placeholder="row limit" value={s.limit ?? 500} onChange={(e) => upd(i, { limit: Number(e.target.value) })} /></div>}
                {s.type === "analysis" && <select className="input" value={s.analysis_run_id ?? ""} onChange={(e) => upd(i, { analysis_run_id: e.target.value })}><option value="">analysis run…</option>
                  {(runs.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.kind} · {fmtTime(r.created_at)}</option>)}</select>}
                {s.type === "graph" && <select className="input" value={s.snapshot_id ?? ""} onChange={(e) => upd(i, { snapshot_id: e.target.value })}><option value="">graph snapshot…</option>
                  {(snaps.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select>}
                {["findings", "evidence"].includes(s.type) && <div className="flex gap-2"><select className="input" value={s.investigation_id ?? ""} onChange={(e) => upd(i, { investigation_id: e.target.value })}><option value="">investigation…</option>
                  {(invs.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select>
                  {s.type === "findings" && <label className="flex items-center gap-1 whitespace-nowrap"><input type="checkbox" checked={!!s.include_drafts} onChange={(e) => upd(i, { include_drafts: e.target.checked })} />include drafts</label>}</div>}
                {s.type === "timeline" && <div className="grid grid-cols-2 gap-1"><input className="input" type="datetime-local" value={s.start ?? ""} onChange={(e) => upd(i, { start: e.target.value || undefined })} /><input className="input" type="datetime-local" value={s.end ?? ""} onChange={(e) => upd(i, { end: e.target.value || undefined })} /></div>}
                {s.type === "map" && <input className="input" placeholder="layers (comma, optional)" value={(s.layers ?? []).join(",")} onChange={(e) => upd(i, { layers: e.target.value ? e.target.value.split(",").map((x) => x.trim()) : undefined })} />}
              </div>
            ))}
            <Field label="Add section"><select className="input" value="" onChange={(e) => e.target.value && setSections([...sections, { type: e.target.value, title: e.target.value.replace("_", " ") }])}>
              <option value="">Choose…</option>{["text", "dataset_table", "analysis", "graph", "timeline", "map", "findings", "evidence", "appendix"].map((t) => <option key={t}>{t}</option>)}</select></Field>
          </div>
        </Card>
        <div className="space-y-3">
          {exports.length > 0 && <Card title="Exports" bodyClass=""><Table columns={["Format", "Size", "SHA-256", ""]} rows={exports.map((e) => [e.format, fmtBytes(e.size_bytes), <code className="font-mono text-xxs">{e.sha256.slice(0, 16)}</code>,
            <button className="btn" onClick={() => download(pp(pid, `/reports/${id}/exports/${e.id}`), `report.${e.format}`)}>Download</button>])} /></Card>}
          {preview ? <Card title="Preview">
            <div className="space-y-2 text-xs">
              {preview.blocks.map((b: any, i: number) => b.kind === "heading" ? <h3 key={i} className="mt-3 text-sm font-semibold">{b.text}</h3>
                : b.kind === "paragraph" ? <p key={i}>{b.text}</p>
                : b.kind === "table" ? <div key={i}><p className="label">{b.title}</p><Table maxHeight={220} columns={b.columns} rows={b.rows.slice(0, 30).map((r: any[]) => r.map(String))} />{b.caption && <p className="text-muted">{b.caption}</p>}</div>
                : b.kind === "chart" ? <Chart key={i} height={180} option={{ xAxis: { type: "category", data: b.labels }, yAxis: { type: "value" }, series: [{ type: b.chart === "line" ? "line" : "bar", data: b.values }] }} />
                : b.kind === "finding" ? <div key={i} className="rounded border-l-4 border-accent bg-raised p-2"><b>{b.title}</b> <Badge>{b.status}</Badge> <Badge>{b.basis}</Badge><p>{b.statement}</p><p className="text-muted">{b.supporting.length} supporting · {b.contradicting.length} contradicting</p></div>
                : b.kind === "diagram" ? <Notice key={i}>Graph diagram: {b.nodes.length} nodes, {b.edges.length} edges (rendered in PDF/HTML)</Notice>
                : b.kind === "scatter" ? <Notice key={i}>Map plot: {b.points.length} points (rendered in PDF/HTML)</Notice>
                : <Json key={i} value={b} max={140} />)}
              <h3 className="label mt-3">Manifest</h3><Json value={preview.manifest} max={200} />
            </div>
          </Card> : <p className="text-xs text-muted">Save and preview to see the resolved report content.</p>}
        </div>
      </div>
    </div>
  );
}
