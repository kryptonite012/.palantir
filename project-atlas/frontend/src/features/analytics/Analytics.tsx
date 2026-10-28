import { useMemo, useState } from "react";
import { api, pp } from "../../services/api";
import { useAI, useCan, usePQuery, useProjectId } from "../../app/hooks";
import { AskData } from "./AskData";
import { Badge, Card, ErrorBox, Field, Json, Notice, PageHeader, Spinner, Table, Tabs, fmtTime } from "../../components/ui";
import { Chart } from "../../components/Chart";
import type { AnalysisRun, Dataset } from "../../types/api";

const KINDS: Record<string, { label: string; params: ("field" | "fields" | "time_field" | "value_field" | "period")[] }> = {
  describe: { label: "Descriptive statistics", params: [] },
  frequency: { label: "Frequency distribution", params: ["field"] },
  missing: { label: "Missing-data analysis", params: [] },
  outliers: { label: "Outlier detection (IQR + robust z)", params: ["field"] },
  correlation: { label: "Correlation (Pearson)", params: ["fields"] },
  trend: { label: "Trend over time", params: ["time_field", "value_field", "period"] },
  timeseries: { label: "Time-series summary", params: ["time_field"] },
};

export function AnalyticsPage() {
  const [tab, setTab] = useState<"run" | "history" | "sql" | "ask">("run");
  const ai = useAI();
  return (
    <div className="space-y-3">
      <PageHeader title="Analytics" subtitle="Every run records dataset versions, content hashes, parameters, algorithm version and duration, and can be reproduced." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "run", label: "New analysis" }, { id: "history", label: "Runs & reproducibility" }, { id: "sql", label: "SQL console" }, ...(ai ? [{ id: "ask" as const, label: "Ask your data (AI)" }] : [])]} />
      {tab === "run" && <RunAnalysis />}
      {tab === "history" && <History />}
      {tab === "sql" && <SqlConsole />}
      {tab === "ask" && <AskData />}
    </div>
  );
}

function RunAnalysis() {
  const pid = useProjectId();
  const ds = usePQuery<Dataset[]>(["datasets"], "/datasets");
  const [dsId, setDsId] = useState("");
  const [kind, setKind] = useState("describe");
  const [p, setP] = useState<any>({ period: "M" });
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const dataset = ds.data?.find((d) => d.id === dsId);
  const fields = dataset?.latest?.schema.fields ?? [];
  const go = async () => {
    setErr(null); setBusy(true);
    try {
      const params: any = {};
      for (const k of KINDS[kind].params) if (p[k]) params[k] = p[k];
      setRun(await api(pp(pid, "/analyses"), { body: { kind, dataset_version_id: dataset?.latest?.version_id, params } }));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="grid gap-3 xl:grid-cols-[320px_1fr]">
      <Card title="Configure">
        <div className="space-y-2">
          <Field label="Dataset (current version)"><select className="input" value={dsId} onChange={(e) => setDsId(e.target.value)}>
            <option value="">Select…</option>{(ds.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name} v{d.current_version}</option>)}</select></Field>
          <Field label="Analysis"><select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></Field>
          {KINDS[kind].params.map((k) => k === "fields" ? (
            <Field key={k} label="Fields (multi-select)"><select multiple className="input h-24" value={p.fields ?? []} onChange={(e) => setP({ ...p, fields: [...e.target.selectedOptions].map((o) => o.value) })}>
              {fields.map((f) => <option key={f.name}>{f.name}</option>)}</select></Field>
          ) : k === "period" ? (
            <Field key={k} label="Period"><select className="input" value={p.period} onChange={(e) => setP({ ...p, period: e.target.value })}>
              {["D", "W", "M", "Q", "Y"].map((x) => <option key={x}>{x}</option>)}</select></Field>
          ) : (
            <Field key={k} label={k.replace("_", " ")}><select className="input" value={p[k] ?? ""} onChange={(e) => setP({ ...p, [k]: e.target.value })}>
              <option value="">{k === "value_field" ? "(count records)" : "Select…"}</option>{fields.map((f) => <option key={f.name}>{f.name}</option>)}</select></Field>
          ))}
          <button className="btn btn-primary" disabled={!dataset || busy} onClick={go}>Run</button>
          <ErrorBox error={err} />
        </div>
      </Card>
      <div>{busy ? <Spinner /> : run ? <RunResult run={run} /> : <p className="text-xs text-muted">Results appear here.</p>}</div>
    </div>
  );
}

export function RunResult({ run }: { run: AnalysisRun }) {
  const r = run.result;
  const chart = useMemo(() => {
    if (run.kind === "frequency") return { xAxis: { type: "category", data: r.values.slice(0, 25).map((v: any) => v.value), axisLabel: { rotate: 30 } }, yAxis: { type: "value" }, series: [{ type: "bar", data: r.values.slice(0, 25).map((v: any) => v.count) }] };
    if (run.kind === "trend") return { xAxis: { type: "category", data: r.points.map((x: any) => x.period) }, yAxis: { type: "value" }, series: [{ type: "line", data: r.points.map((x: any) => x.value), smooth: false }] };
    if (run.kind === "missing") return { xAxis: { type: "category", data: r.fields.map((f: any) => f.field), axisLabel: { rotate: 30 } }, yAxis: { type: "value", max: 1 }, series: [{ type: "bar", data: r.fields.map((f: any) => f.share) }] };
    if (run.kind === "timeseries") return { xAxis: { type: "category", data: Object.keys(r.by_hour_utc ?? {}) }, yAxis: { type: "value" }, series: [{ type: "bar", data: Object.values(r.by_hour_utc ?? {}) }] };
    return null;
  }, [run, r]);
  return (
    <Card title={<>{run.kind} <span className="font-mono text-xxs font-normal text-muted">run {run.id.slice(-8)}</span></>}>
      <div className="mb-2 flex flex-wrap gap-1 text-xxs">
        <Badge>{run.algorithm_version}</Badge><Badge>atlas {run.software_version}</Badge><Badge>{run.duration_ms.toFixed(1)} ms</Badge>
        <Badge tone="accent">result sha256 {run.result_sha256.slice(0, 12)}…</Badge>
        {((run.inputs as any).dataset_versions ?? []).map((d: any) => <Badge key={d.version_id}>{d.dataset_name} v{d.version}</Badge>)}
        {((run.inputs as any).redacted_fields ?? []).length > 0 && <Badge tone="warn">redacted: {(run.inputs as any).redacted_fields.join(", ")}</Badge>}
      </div>
      {r.disclaimer && <Notice tone="warn">{r.disclaimer}</Notice>}
      {(r.assumptions || r.limitations || r.method || r.note) && <p className="my-2 text-xs text-muted">{[r.method, r.assumptions, r.limitations, r.note].filter(Boolean).join(" ")}</p>}
      {chart && <Chart option={chart as any} height={240} />}
      {run.kind === "describe" && <Table columns={["Field", "Kind", "n", "Missing", "Distinct", "Mean", "Std", "Min", "Median", "Max / top"]} rows={r.fields.map((f: any) => [
        f.field, f.kind, f.n, f.missing, f.distinct, f.mean?.toFixed?.(3) ?? "", f.std?.toFixed?.(3) ?? "", f.min ?? "", f.median ?? "",
        f.kind === "numeric" ? f.max : (f.top ?? []).map((t: any) => `${t.value} (${t.count})`).join(", ")])} />}
      {run.kind === "outliers" && <Table columns={["Row", "Value", "Robust z", "Record"]} rows={r.outliers.map((o: any) => [o.row_index + 1, o.value, o.robust_z?.toFixed(2), <code className="font-mono text-xxs">{o.record_id}</code>])} empty="No outliers beyond the fences" />}
      {run.kind === "correlation" && <Table columns={["A", "B", "n", "r", "95% CI"]} rows={r.pairs.map((x: any) => [x.a, x.b, x.n, x.pearson_r?.toFixed(4) ?? "—", x.ci95 ? `[${x.ci95.join(", ")}]` : "—"])} />}
      {!["describe", "outliers", "correlation"].includes(run.kind) && !chart && <Json value={r} />}
    </Card>
  );
}

function History() {
  const pid = useProjectId();
  const runs = usePQuery<AnalysisRun[]>(["analyses"], "/analyses");
  const [sel, setSel] = useState<AnalysisRun | null>(null);
  const [rep, setRep] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const open = async (id: string) => { setRep(null); try { setSel(await api(pp(pid, `/analyses/${id}`))); } catch (e) { setErr(e); } };
  const reproduce = async (id: string) => { try { setRep(await api(pp(pid, `/analyses/${id}/reproduce`), { method: "POST" })); runs.refetch(); } catch (e) { setErr(e); } };
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Card bodyClass="">
        <Table maxHeight={600} columns={["When", "Kind", "Algorithm", "Result hash", "Reproduction of", ""]} rows={(runs.data ?? []).map((r) => [
          fmtTime(r.created_at), <button className="text-accent hover:underline" onClick={() => open(r.id)}>{r.kind}</button>, r.algorithm_version,
          <code className="font-mono text-xxs">{r.result_sha256.slice(0, 12)}</code>, r.reproduced_from_id?.slice(-8) ?? "", <button className="btn" onClick={() => reproduce(r.id)}>Reproduce</button>])} empty="No analyses run yet" />
      </Card>
      <div className="space-y-3">
        <ErrorBox error={err} />
        {rep && <Notice tone={rep.identical_result ? "ok" : "warn"}>
          Reproduction {rep.identical_result ? "produced an identical result" : "produced a DIFFERENT result"}; inputs {rep.identical_inputs ? "identical" : "changed since the original run"}
          {rep.algorithm_version_changed ? "; algorithm version changed" : ""}.</Notice>}
        {sel && <RunResult run={sel} />}
      </div>
    </div>
  );
}

function SqlConsole() {
  const pid = useProjectId();
  const tables = usePQuery<any[]>(["sql-tables"], "/sql/tables");
  const canAI = useCan("ai.use");
  const [sql, setSql] = useState("select * from ");
  const [res, setRes] = useState<any>(null);
  const [draft, setDraft] = useState<any>(null);
  const [question, setQuestion] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setErr(null); setBusy(true); try { setRes(await api(pp(pid, "/sql"), { body: { sql } })); } catch (e) { setErr(e); } finally { setBusy(false); } };
  const ask = async () => { setErr(null); try { setDraft(await api(pp(pid, "/ai/sql-draft"), { body: { question } })); } catch (e) { setErr(e); } };
  return (
    <div className="grid gap-3 xl:grid-cols-[260px_1fr]">
      <Card title="Tables (current versions)">
        {(tables.data ?? []).map((t) => <details key={t.table} className="mb-1 text-xs"><summary className="cursor-pointer font-mono">{t.table} <span className="text-muted">v{t.version}</span></summary>
          <ul className="pl-3 font-mono text-xxs text-muted">{t.columns.map((c: string) => <li key={c}>{c}</li>)}</ul></details>)}
        <p className="mt-2 text-[10px] text-muted">Read-only, single SELECT/WITH statement, row and time limited. Sensitive columns are excluded unless your role permits them.</p>
      </Card>
      <div className="space-y-3">
        {canAI && (
          <Card title="Draft SQL with local AI (optional)">
            <div className="flex gap-2"><input className="input" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. total payment amount per organization" />
              <button className="btn" onClick={ask} disabled={question.length < 3}>Draft</button></div>
            {draft && <div className="mt-2 space-y-1 text-xs"><Badge tone="hypo">{draft.label}</Badge> {draft.valid ? <Badge tone="ok">passes validation</Badge> : <Badge tone="danger">rejected: {draft.validation_error}</Badge>}
              <pre className="rounded bg-bg p-2 font-mono text-xxs">{draft.sql}</pre>
              {draft.valid && <button className="btn" onClick={() => setSql(draft.sql)}>Copy into editor (not executed)</button>}
              <p className="text-muted">{draft.note}</p></div>}
          </Card>
        )}
        <Card title="Query" actions={<button className="btn btn-primary" onClick={run} disabled={busy}>Run (Ctrl+Enter)</button>}>
          <textarea className="input h-32 font-mono" value={sql} onChange={(e) => setSql(e.target.value)} spellCheck={false}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run(); }} aria-label="SQL" />
          <ErrorBox error={err} />
        </Card>
        {res && <Card title={<>{res.row_count} rows {res.truncated && <Badge tone="warn">truncated at limit</Badge>} <span className="font-normal text-muted">{res.elapsed_ms} ms</span></>} bodyClass="">
          <Table maxHeight={480} columns={res.columns} rows={res.rows.map((r: any[]) => r.map((v) => (v === null ? "∅" : String(v))))} /></Card>}
      </div>
    </div>
  );
}
