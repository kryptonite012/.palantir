import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, pp, waitForJob } from "../../services/api";
import { usePQuery, useProjectId } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, Notice, PageHeader, Spinner, Table, fmtBytes, fmtNum } from "../../components/ui";

const TYPES = ["string", "identifier", "integer", "float", "boolean", "date", "datetime", "email", "phone", "latitude", "longitude"];
const STEPS = ["Select file", "Inspect", "Map fields", "Entities & links", "Validate (dry run)", "Import"];

type Spec = { target: string; type: string; sensitive?: boolean; required?: boolean; timezone?: string; case?: string };
type EntitySpec = { entity_type: string; name_field?: string; id_field?: string; id_namespace?: string; attributes: string[] };

export function Ingestion() {
  const pid = useProjectId();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const targetDataset = params.get("dataset");
  const sources = usePQuery<any[]>(["sources"], "/sources");
  const ontology = usePQuery<any>(["ontology"], "/ontology");
  const [step, setStep] = useState(0);
  const [file, setFile] = useState<any>(null);
  const [sourceId, setSourceId] = useState("");
  const [insp, setInsp] = useState<any>(null);
  const [parse, setParse] = useState<Record<string, string>>({});
  const [mapping, setMapping] = useState<Record<string, Spec & { include: boolean }>>({});
  const [meta, setMeta] = useState({ dataset_name: "", description: "", access_policy: "project", retention_policy: "indefinite",
    default_timezone: "UTC", is_synthetic: false, unique: "" });
  const [ents, setEnts] = useState<EntitySpec[]>([]);
  const [rels, setRels] = useState<{ source: number; target: number; rel_type: string; valid_from_field?: string }[]>([]);
  const [events, setEvents] = useState<{ enabled: boolean; time_field: string; title_template: string; category: string; entity: string }>({ enabled: false, time_field: "", title_template: "", category: "", entity: "" });
  const [geo, setGeo] = useState<{ enabled: boolean; lat_field: string; lon_field: string; label_field: string }>({ enabled: false, lat_field: "", lon_field: "", label_field: "" });
  const [dry, setDry] = useState<any>(null);
  const [job, setJob] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const targets = useMemo(() => Object.values(mapping).filter((m) => m.include).map((m) => m.target), [mapping]);

  const run = async (fn: () => Promise<void>) => {
    setErr(null);
    setBusy(true);
    try { await fn(); } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  const upload = (f: File) => run(async () => {
    const fd = new FormData();
    fd.append("file", f);
    if (sourceId) fd.append("source_id", sourceId);
    const r = await api(pp(pid, "/files"), { form: fd });
    setFile(r);
    const i = await api(pp(pid, "/ingest/inspect"), { body: { file_id: r.id, parse: {} } });
    applyInspection(i);
    setMeta((m) => ({ ...m, dataset_name: m.dataset_name || f.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_ -]/g, "_") }));
    setStep(1);
  });

  const applyInspection = (i: any) => {
    setInsp(i);
    const m: Record<string, Spec & { include: boolean }> = {};
    for (const c of i.columns) m[c] = { ...i.suggested_mapping[c], include: true };
    setMapping(m);
  };

  const reinspect = () => run(async () => {
    const i = await api(pp(pid, "/ingest/inspect"), { body: { file_id: file.id, parse } });
    applyInspection(i);
  });

  const config = () => {
    const map: Record<string, Spec> = {};
    for (const [src, s] of Object.entries(mapping)) {
      if (!s.include) continue;
      const { include: _i, ...rest } = s;
      map[src] = Object.fromEntries(Object.entries(rest).filter(([, v]) => v !== "" && v !== undefined && v !== false)) as Spec;
    }
    const cfg: any = {
      file_id: file.id, parse, mapping: map, default_timezone: meta.default_timezone, is_synthetic: meta.is_synthetic,
      quality: { unique: meta.unique ? meta.unique.split(",").map((x) => x.trim()).filter(Boolean) : [] },
      entities: ents.map((e) => Object.fromEntries(Object.entries(e).filter(([, v]) => v !== "" && v !== undefined))),
      relationships: rels,
    };
    if (targetDataset) cfg.dataset_id = targetDataset;
    else Object.assign(cfg, { dataset_name: meta.dataset_name, description: meta.description, access_policy: meta.access_policy, retention_policy: meta.retention_policy });
    if (events.enabled && events.time_field) cfg.events = { time_field: events.time_field, title_template: events.title_template || undefined,
      category: events.category || undefined, entity: events.entity === "" ? undefined : Number(events.entity) };
    if (geo.enabled && geo.lat_field && geo.lon_field) cfg.geo = { lat_field: geo.lat_field, lon_field: geo.lon_field, label_field: geo.label_field || undefined };
    return cfg;
  };

  const dryRun = () => run(async () => {
    setDry(await api(pp(pid, "/ingest/preview"), { body: { config: config() } }));
    setStep(4);
  });

  const commit = () => run(async () => {
    const j = await api(pp(pid, "/ingest/commit"), { body: { config: config() } });
    setStep(5);
    setJob(j);
    const done = await waitForJob(j.id, setJob);
    if (done.status === "succeeded") qc.invalidateQueries();
  });

  return (
    <div className="space-y-3">
      <PageHeader title="Ingestion" subtitle={targetDataset ? "Importing a new version of an existing dataset" : "Controlled import: inspect, map, validate, then commit. Originals are preserved unchanged."} />
      <ol className="flex flex-wrap gap-1 text-xxs">
        {STEPS.map((s, i) => (
          <li key={s} className={`rounded px-2 py-1 ${i === step ? "bg-accent text-white" : i < step ? "bg-accent/15 text-accent" : "bg-raised text-muted"}`}>{i + 1}. {s}</li>
        ))}
      </ol>
      <ErrorBox error={err} />
      {busy && <Spinner label="Working…" />}

      {step === 0 && (
        <Card title="Select a permitted source and file">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Data source">
              <select className="input" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                <option value="">(default local uploads)</option>
                {(sources.data ?? []).map((s) => <option key={s.id} value={s.id} disabled={!s.permitted}>{s.name}{s.permitted ? "" : " (not permitted)"}</option>)}
              </select>
            </Field>
            <Field label="File" hint="CSV, TSV, XLSX, JSON, JSONL, XML, SQLite, Parquet. Documents (PDF, DOCX, TXT, MD, EML) go to Documents.">
              <input className="input" type="file" accept=".csv,.tsv,.tab,.xlsx,.json,.jsonl,.ndjson,.xml,.sqlite,.sqlite3,.db,.parquet"
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </Field>
          </div>
        </Card>
      )}

      {step >= 1 && step < 5 && insp && (
        <Card title={<>File: {file.original_name} <span className="font-normal text-muted">· {fmtBytes(file.size_bytes)} · sha256 {file.sha256.slice(0, 12)}…</span></>}
          actions={step === 1 && <button className="btn btn-primary" onClick={() => setStep(2)}>Continue to mapping</button>}>
          <div className="mb-3 flex flex-wrap items-end gap-3 text-xs">
            <Badge>format: {insp.format}</Badge>{insp.encoding && <Badge>encoding: {insp.encoding}</Badge>}
            {insp.delimiter && <Badge>delimiter: {JSON.stringify(insp.delimiter)}</Badge>}
            {insp.notes.map((n: string) => <Badge key={n} tone="warn">{n}</Badge>)}
            {insp.sheets?.length > 1 && <Field label="Sheet"><select className="input" value={parse.sheet ?? ""} onChange={(e) => setParse({ ...parse, sheet: e.target.value })}>
              {insp.sheets.map((s: string) => <option key={s}>{s}</option>)}</select></Field>}
            {insp.tables?.length > 1 && <Field label="Table"><select className="input" value={parse.table ?? ""} onChange={(e) => setParse({ ...parse, table: e.target.value })}>
              {insp.tables.map((s: string) => <option key={s}>{s}</option>)}</select></Field>}
            {["csv", "tsv"].includes(insp.format) && <>
              <Field label="Delimiter override"><input className="input w-20" value={parse.delimiter ?? ""} onChange={(e) => setParse({ ...parse, delimiter: e.target.value })} /></Field>
              <Field label="Encoding override"><select className="input" value={parse.encoding ?? ""} onChange={(e) => setParse({ ...parse, encoding: e.target.value })}>
                <option value="">auto</option>{["utf-8", "utf-8-sig", "cp1252", "latin-1"].map((x) => <option key={x}>{x}</option>)}</select></Field>
            </>}
            {insp.format === "json" && <Field label="Record path"><input className="input" placeholder="e.g. data.items" value={parse.record_path ?? ""} onChange={(e) => setParse({ ...parse, record_path: e.target.value })} /></Field>}
            <button className="btn" onClick={reinspect}>Re-inspect</button>
          </div>
          {step === 1 && (
            <Table maxHeight={360} columns={insp.columns.map((c: string) => <span>{c} <span className="normal-case text-accent">{insp.inferred_types[c]}</span></span>)}
              rows={insp.preview.map((r: any) => insp.columns.map((c: string) => String(r[c] ?? "")))} />
          )}
        </Card>
      )}

      {step === 2 && (
        <Card title="Map columns to canonical fields" actions={<>
          <button className="btn" onClick={() => setStep(1)}>Back</button>
          <button className="btn btn-primary" onClick={() => setStep(3)}>Continue</button></>}>
          <div className="mb-3 grid gap-3 md:grid-cols-4">
            {!targetDataset && <>
              <Field label="Dataset name"><input className="input" value={meta.dataset_name} onChange={(e) => setMeta({ ...meta, dataset_name: e.target.value })} /></Field>
              <Field label="Access policy"><select className="input" value={meta.access_policy} onChange={(e) => setMeta({ ...meta, access_policy: e.target.value })}>
                <option value="project">project members</option><option value="restricted">restricted (engineers & admins)</option></select></Field>
              <Field label="Retention"><select className="input" value={meta.retention_policy} onChange={(e) => setMeta({ ...meta, retention_policy: e.target.value })}>
                {["indefinite", "1y", "3y", "7y", "until_case_closed"].map((r) => <option key={r}>{r}</option>)}</select></Field>
            </>}
            <Field label="Default time zone (naive timestamps)"><input className="input" value={meta.default_timezone} onChange={(e) => setMeta({ ...meta, default_timezone: e.target.value })} /></Field>
            <Field label="Unique key fields (comma separated)"><input className="input" value={meta.unique} onChange={(e) => setMeta({ ...meta, unique: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={meta.is_synthetic} onChange={(e) => setMeta({ ...meta, is_synthetic: e.target.checked })} /> Mark as synthetic data</label>
          </div>
          <Table columns={["Include", "Source column", "Sample", "Target field", "Type", "Case", "Time zone", "Required", "Sensitive"]}
            rows={Object.entries(mapping).map(([src, m]) => {
              const upd = (p: Partial<Spec & { include: boolean }>) => setMapping({ ...mapping, [src]: { ...m, ...p } });
              return [
                <input type="checkbox" checked={m.include} onChange={(e) => upd({ include: e.target.checked })} aria-label={`include ${src}`} />,
                <code className="font-mono">{src}</code>,
                <span className="text-muted">{String(insp.preview[0]?.[src] ?? "").slice(0, 30)}</span>,
                <input className="input w-36 font-mono" value={m.target} onChange={(e) => upd({ target: e.target.value })} />,
                <select className="input w-28" value={m.type} onChange={(e) => upd({ type: e.target.value })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>,
                <select className="input w-20" value={m.case ?? ""} onChange={(e) => upd({ case: e.target.value })}><option value="">—</option><option>lower</option><option>upper</option><option>title</option></select>,
                m.type === "datetime" ? <input className="input w-32" placeholder="default" value={m.timezone ?? ""} onChange={(e) => upd({ timezone: e.target.value })} /> : "",
                <input type="checkbox" checked={!!m.required} onChange={(e) => upd({ required: e.target.checked })} />,
                <input type="checkbox" checked={!!m.sensitive} onChange={(e) => upd({ sensitive: e.target.checked })} />,
              ];
            })} />
        </Card>
      )}

      {step === 3 && (
        <Card title="Entities, relationships, events and locations (optional)" actions={<>
          <button className="btn" onClick={() => setStep(2)}>Back</button>
          <button className="btn btn-primary" onClick={dryRun} disabled={busy}>Run validation (dry run)</button></>}>
          <Notice>Records sharing an identifier value (within the same namespace) resolve to the same entity deterministically. Records without identifiers create separate entities that you can later resolve through match review.</Notice>
          <div className="mt-3 space-y-2">
            {ents.map((e, i) => (
              <div key={i} className="grid grid-cols-6 items-end gap-2 rounded border border-line p-2">
                <Field label={`Entity #${i}`}><select className="input" value={e.entity_type} onChange={(ev) => setEnts(ents.map((x, j) => j === i ? { ...x, entity_type: ev.target.value } : x))}>
                  {(ontology.data?.entity_types ?? []).map((t: any) => <option key={t.name} value={t.name}>{t.label}</option>)}</select></Field>
                <Field label="Name field"><FieldSelect targets={targets} value={e.name_field} onChange={(v) => setEnts(ents.map((x, j) => j === i ? { ...x, name_field: v } : x))} /></Field>
                <Field label="Identifier field"><FieldSelect targets={targets} value={e.id_field} onChange={(v) => setEnts(ents.map((x, j) => j === i ? { ...x, id_field: v } : x))} /></Field>
                <Field label="Identifier namespace"><input className="input" placeholder="defaults to field" value={e.id_namespace ?? ""} onChange={(ev) => setEnts(ents.map((x, j) => j === i ? { ...x, id_namespace: ev.target.value } : x))} /></Field>
                <Field label="Attributes (comma)"><input className="input" value={e.attributes.join(",")} onChange={(ev) => setEnts(ents.map((x, j) => j === i ? { ...x, attributes: ev.target.value.split(",").map((s) => s.trim()).filter(Boolean) } : x))} /></Field>
                <button className="btn btn-danger" onClick={() => setEnts(ents.filter((_, j) => j !== i))}>Remove</button>
              </div>
            ))}
            <button className="btn" onClick={() => setEnts([...ents, { entity_type: "person", attributes: [] }])}>+ Entity mapping</button>
            {ents.length >= 2 && (
              <div className="space-y-2">
                {rels.map((r, i) => (
                  <div key={i} className="grid grid-cols-5 items-end gap-2 rounded border border-line p-2">
                    <Field label="From entity #"><input className="input" type="number" min={0} max={ents.length - 1} value={r.source} onChange={(e) => setRels(rels.map((x, j) => j === i ? { ...x, source: Number(e.target.value) } : x))} /></Field>
                    <Field label="Relationship"><select className="input" value={r.rel_type} onChange={(e) => setRels(rels.map((x, j) => j === i ? { ...x, rel_type: e.target.value } : x))}>
                      {(ontology.data?.relationship_types ?? []).map((t: any) => <option key={t.name} value={t.name}>{t.label}</option>)}</select></Field>
                    <Field label="To entity #"><input className="input" type="number" min={0} max={ents.length - 1} value={r.target} onChange={(e) => setRels(rels.map((x, j) => j === i ? { ...x, target: Number(e.target.value) } : x))} /></Field>
                    <Field label="Valid-from field"><FieldSelect targets={targets} value={r.valid_from_field} onChange={(v) => setRels(rels.map((x, j) => j === i ? { ...x, valid_from_field: v } : x))} /></Field>
                    <button className="btn btn-danger" onClick={() => setRels(rels.filter((_, j) => j !== i))}>Remove</button>
                  </div>
                ))}
                <button className="btn" onClick={() => setRels([...rels, { source: 0, target: 1, rel_type: "associated_with" }])}>+ Relationship (observed)</button>
              </div>
            )}
            <div className="grid grid-cols-5 items-end gap-2 rounded border border-line p-2">
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={events.enabled} onChange={(e) => setEvents({ ...events, enabled: e.target.checked })} /> Create timeline events</label>
              <Field label="Event time field"><FieldSelect targets={targets} value={events.time_field} onChange={(v) => setEvents({ ...events, time_field: v ?? "" })} /></Field>
              <Field label="Title template" hint="e.g. Payment {txn_id}"><input className="input" value={events.title_template} onChange={(e) => setEvents({ ...events, title_template: e.target.value })} /></Field>
              <Field label="Category"><input className="input" value={events.category} onChange={(e) => setEvents({ ...events, category: e.target.value })} /></Field>
              <Field label="Linked entity #"><input className="input" value={events.entity} onChange={(e) => setEvents({ ...events, entity: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-4 items-end gap-2 rounded border border-line p-2">
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={geo.enabled} onChange={(e) => setGeo({ ...geo, enabled: e.target.checked })} /> Create map points</label>
              <Field label="Latitude field"><FieldSelect targets={targets} value={geo.lat_field} onChange={(v) => setGeo({ ...geo, lat_field: v ?? "" })} /></Field>
              <Field label="Longitude field"><FieldSelect targets={targets} value={geo.lon_field} onChange={(v) => setGeo({ ...geo, lon_field: v ?? "" })} /></Field>
              <Field label="Label field"><FieldSelect targets={targets} value={geo.label_field} onChange={(v) => setGeo({ ...geo, label_field: v ?? "" })} /></Field>
            </div>
          </div>
        </Card>
      )}

      {step === 4 && dry && (
        <Card title="Validation results (nothing has been written)" actions={<>
          <button className="btn" onClick={() => setStep(3)}>Back</button>
          <button className="btn btn-primary" onClick={commit} disabled={busy}>Confirm import</button></>}>
          <div className="mb-3 flex flex-wrap gap-2 text-xs">
            <Badge tone="accent">{fmtNum(dry.counts.records)} records</Badge>
            <Badge tone={dry.quality.rows_with_errors ? "danger" : "ok"}>{fmtNum(dry.quality.rows_with_errors)} rows with errors</Badge>
            {Object.entries(dry.quality.issue_counts).map(([k, n]) => <Badge key={k} tone="warn">{k}: {String(n)}</Badge>)}
            {dry.quality.duplicate_rows > 0 && <Badge tone="warn">{dry.quality.duplicate_rows} duplicate candidates</Badge>}
            {dry.quality.schema_drift?.added && (dry.quality.schema_drift.added.length + dry.quality.schema_drift.removed.length > 0) && <Badge tone="warn">schema drift</Badge>}
          </div>
          <div className="grid gap-3 xl:grid-cols-2">
            <div>
              <h3 className="label">Issues (first 200)</h3>
              <Table maxHeight={380} columns={["Row", "Field", "Check", "Severity", "Message"]} rows={dry.issues.map((i: any) => [
                i.row_index != null ? i.row_index + 1 : "—", i.field ?? "—", i.check, <Badge tone={i.severity === "error" ? "danger" : "warn"}>{i.severity}</Badge>, i.message])} empty="No issues" />
            </div>
            <div>
              <h3 className="label">Transformed preview</h3>
              <Table maxHeight={380} columns={["Row", "Original → normalized"]} rows={dry.preview.map((p: any) => [p.row_index + 1,
                <div className="space-y-0.5">{Object.entries(p.normalized).map(([k, v]) => (
                  <div key={k} className="font-mono text-xxs"><span className="text-muted">{k}:</span> {String(v)} {p.errors[k] && <span className="text-danger">⚠ {p.errors[k]}</span>}</div>))}</div>])} />
            </div>
          </div>
        </Card>
      )}

      {step === 5 && job && (
        <Card title="Import job">
          <div className="space-y-2 text-xs">
            <div className="h-2 w-full overflow-hidden rounded bg-raised"><div className="h-full bg-accent transition-all" style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
            <p>Status: <Badge tone={job.status === "succeeded" ? "ok" : job.status === "failed" ? "danger" : "accent"}>{job.status}</Badge> {job.message}</p>
            {job.error && <ErrorBox error={new Error(job.error)} />}
            {job.status === "running" && <button className="btn" onClick={() => api(`/api/jobs/${job.id}/cancel`, { method: "POST" })}>Cancel</button>}
            {job.status === "failed" && <button className="btn" onClick={() => run(async () => { await api(`/api/jobs/${job.id}/retry`, { method: "POST" }); setJob(await waitForJob(job.id, setJob)); })}>Retry</button>}
            {job.status === "succeeded" && (
              <div className="space-y-2">
                <Notice tone="ok">Imported {fmtNum(job.result.counts?.records)} records into <b>{job.result.dataset?.name}</b> v{job.result.dataset?.version}.
                  {" "}{job.result.counts?.entities_created ?? 0} new entities, {job.result.counts?.relationships ?? 0} relationships, {job.result.counts?.events ?? 0} events, {job.result.counts?.geo_features ?? 0} map points.</Notice>
                <div className="flex gap-2">
                  <button className="btn btn-primary" onClick={() => nav(`/catalog/${job.result.dataset?.id}`)}>Open dataset</button>
                  <button className="btn" onClick={() => nav("/entities")}>Review entities</button>
                  <button className="btn" onClick={() => { setStep(0); setFile(null); setInsp(null); setDry(null); setJob(null); setEnts([]); setRels([]); }}>Import another</button>
                </div>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

function FieldSelect({ targets, value, onChange }: { targets: string[]; value?: string; onChange: (v: string | undefined) => void }) {
  return (
    <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)}>
      <option value="">—</option>
      {targets.map((t) => <option key={t}>{t}</option>)}
    </select>
  );
}
