import { FormEvent, useEffect, useState } from "react";
import { askText, toast } from "../../components/feedback";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../services/api";
import { useCan, useProjectId } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, PageHeader, Spinner, fmtTime } from "../../components/ui";

const TYPES = ["dataset_record", "entity", "relationship", "document", "report", "investigation"];

function Snippet({ text }: { text: string }) {
  const parts = text.split(/(\[\[.*?\]\])/g);
  return <span>{parts.map((p, i) => p.startsWith("[[") ? <mark key={i} className="rounded bg-warn/30 px-0.5 text-ink">{p.slice(2, -2)}</mark> : p)}</span>;
}

export function SearchPage() {
  const pid = useProjectId();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  const [types, setTypes] = useState<string[]>([]);
  const [scope, setScope] = useState<"project" | "all">("project");
  const [dates, setDates] = useState({ from: "", to: "" });
  const [semantic, setSemantic] = useState(false);
  const canAI = useCan("ai.use");
  useEffect(() => setDraft(q), [q]);
  const res = useQuery({
    queryKey: ["search", q, types, scope, dates, pid],
    queryFn: () => api("/api/search", { params: { q, project_id: scope === "project" ? pid : undefined, type: types, date_from: dates.from, date_to: dates.to, limit: 50 } }),
    enabled: !!q && !semantic,
  });
  const sem = useQuery({ queryKey: ["semantic", q, pid], queryFn: () => api(`/api/projects/${pid}/ai/semantic-search`, { params: { q } }), enabled: !!q && semantic });
  const saved = useQuery({ queryKey: ["saved", pid], queryFn: () => api("/api/search/saved", { params: { project_id: pid } }), enabled: !!pid });
  const hist = useQuery({ queryKey: ["history", pid, q], queryFn: () => api("/api/search/history", { params: { project_id: pid } }), enabled: !!pid });

  const submit = (e: FormEvent) => { e.preventDefault(); setParams({ q: draft }); };
  const open = (r: any) => {
    if (r.doc_type === "entity") nav(`/entities/${r.ref_id}`);
    else if (r.doc_type === "dataset_record") nav(`/catalog/${r.dataset_id}`);
    else if (r.doc_type === "document") nav(`/documents?doc=${r.dataset_id}`);
    else if (r.doc_type === "investigation") nav(`/investigations/${r.ref_id}`);
    else if (r.doc_type === "report") nav(`/reports?id=${r.ref_id}`);
  };
  const save = async () => {
    const name = await askText({ title: "Save search", label: "Name", defaultValue: q, confirmText: "Save" });
    if (name) { await api("/api/search/saved", { body: { project_id: pid, name, query: q, filters: { types } } }); saved.refetch(); toast.ok("Search saved"); }
  };

  return (
    <div className="space-y-3">
      <PageHeader title="Global Search" subtitle={<>Syntax: <code>"exact phrase"</code>, <code>AND</code>/<code>OR</code>/<code>NOT</code>, <code>(…)</code>, <code>pref*</code>, <code>type:entity</code>, <code>amount&gt;1000</code>, <code>city:Oslo</code></>} />
      <form onSubmit={submit} className="flex gap-2">
        <input className="input text-sm" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Search datasets, entities, documents, reports…" autoFocus aria-label="Search query" />
        <button className="btn btn-primary">Search</button>
        {q && <button type="button" className="btn" onClick={save}>Save</button>}
      </form>
      <div className="grid gap-3 lg:grid-cols-[220px_1fr]">
        <aside className="space-y-3">
          <Card title="Filters">
            <div className="space-y-2 text-xs">
              <Field label="Scope"><select className="input" value={scope} onChange={(e) => setScope(e.target.value as any)}>
                <option value="project">Active project</option><option value="all">All my projects</option></select></Field>
              <span className="label">Types</span>
              {TYPES.map((t) => <label key={t} className="flex items-center gap-1.5"><input type="checkbox" checked={types.includes(t)}
                onChange={(e) => setTypes(e.target.checked ? [...types, t] : types.filter((x) => x !== t))} />{t.replace("_", " ")}</label>)}
              <Field label="Indexed from"><input className="input" type="date" value={dates.from} onChange={(e) => setDates({ ...dates, from: e.target.value })} /></Field>
              <Field label="Indexed to"><input className="input" type="date" value={dates.to} onChange={(e) => setDates({ ...dates, to: e.target.value })} /></Field>
              {canAI && <label className="flex items-center gap-1.5"><input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} /> Semantic (local embeddings)</label>}
            </div>
          </Card>
          <Card title="Saved searches">
            {(saved.data ?? []).map((s: any) => <button key={s.id} className="block w-full truncate py-0.5 text-left text-xs text-accent hover:underline" onClick={() => setParams({ q: s.query })}>{s.name}</button>)}
            {!saved.data?.length && <p className="text-xxs text-muted">None yet</p>}
          </Card>
          <Card title="Recent" actions={<button className="btn btn-ghost text-xxs" onClick={() => api("/api/search/history", { method: "DELETE", params: { project_id: pid } }).then(() => hist.refetch())}>Clear</button>}>
            {(hist.data?.items ?? []).slice(0, 10).map((h: any) => <button key={h.id} className="block w-full truncate py-0.5 text-left text-xs hover:underline" onClick={() => setParams({ q: h.query })}>{h.query} <span className="text-muted">({h.result_count})</span></button>)}
            <p className="mt-1 text-[10px] text-muted">Kept for {hist.data?.retention_days ?? 90} days</p>
          </Card>
        </aside>
        <section>
          {!q ? <p className="text-xs text-muted">Enter a query to search.</p> : semantic ? (
            sem.isLoading ? <Spinner /> : sem.error ? <ErrorBox error={sem.error} /> : (
              <Card title={<>Semantic results <Badge tone="hypo">{sem.data.label}</Badge></>}>
                {sem.data.results.map((r: any) => <div key={r.chunk_id} className="border-b border-line/50 py-2 text-xs">
                  <button className="font-medium text-accent hover:underline" onClick={() => nav(`/documents?doc=${r.document_id}&page=${r.page}`)}>{r.title} · p.{r.page}</button>
                  <span className="ml-2 font-mono text-xxs text-muted">cos {r.cosine}</span><p className="text-muted">{r.excerpt}</p></div>)}
              </Card>)
          ) : res.isLoading ? <Spinner /> : res.error ? <ErrorBox error={res.error} /> : (
            <Card title={<>{res.data.total} results <span className="font-mono text-xxs font-normal text-muted">{res.data.parsed}</span></>} bodyClass="divide-y divide-line/50">
              {res.data.results.map((r: any) => (
                <div key={`${r.doc_type}-${r.ref_id}`} className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Badge tone={{ entity: "accent", document: "hypo", dataset_record: "neutral" }[r.doc_type as string] ?? "neutral"}>{r.doc_type.replace("_", " ")}</Badge>
                    <button className="text-xs font-medium text-accent hover:underline" onClick={() => open(r)}>{r.title}</button>
                    <span className="ml-auto font-mono text-xxs text-muted">score {r.score} · {fmtTime(r.created_at)}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted"><Snippet text={r.snip ?? ""} /></p>
                </div>
              ))}
              {res.data.results.length === 0 && <p className="p-4 text-xs text-muted">No matches. Restricted datasets are excluded unless your role allows them.</p>}
            </Card>
          )}
        </section>
      </div>
    </div>
  );
}
