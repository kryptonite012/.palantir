import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, pp } from "../../services/api";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { Badge, Card, Empty, ErrorBox, Field, Modal, PageHeader, Spinner, StatusBadge, Table, fmtTime } from "../../components/ui";

export function InvestigationsPage() {
  const pid = useProjectId();
  const nav = useNavigate();
  const list = usePQuery<any[]>(["investigations"], "/investigations");
  const canCreate = useCan("investigation.create");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", objective: "", scope: "", classification: "internal" });
  const [err, setErr] = useState<unknown>(null);
  const create = async () => {
    try { const r = await api(pp(pid, "/investigations"), { body: form }); nav(`/investigations/${r.id}`); } catch (e) { setErr(e); }
  };
  return (
    <div className="space-y-3">
      <PageHeader title="Investigations" subtitle="Scoped workspaces for authorized research, compliance, auditing and organizational analysis."
        actions={canCreate && <button className="btn btn-primary" onClick={() => setOpen(true)}>New investigation</button>} />
      {!list.data?.length ? <Empty title="No investigations">Only investigations you own or collaborate on are listed.</Empty> : (
        <Card bodyClass="">
          <Table columns={["Title", "Status", "Classification", "Objective", "Created"]} rows={list.data.map((i) => [
            <button className="font-medium text-accent hover:underline" onClick={() => nav(`/investigations/${i.id}`)}>{i.title}</button>,
            <StatusBadge status={i.status} />, <Badge>{i.classification}</Badge>, <span className="text-muted">{i.objective}</span>, fmtTime(i.created_at)])} />
        </Card>
      )}
      <Modal open={open} title="New investigation" onClose={() => setOpen(false)}>
        <div className="space-y-2">
          <Field label="Title"><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label="Objective"><textarea className="input" rows={2} value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></Field>
          <Field label="Scope & authorization basis"><textarea className="input" rows={2} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} /></Field>
          <Field label="Classification"><select className="input" value={form.classification} onChange={(e) => setForm({ ...form, classification: e.target.value })}>
            {["public", "internal", "confidential", "restricted"].map((c) => <option key={c}>{c}</option>)}</select></Field>
          <ErrorBox error={err} />
          <button className="btn btn-primary" disabled={!form.title} onClick={create}>Create</button>
        </div>
      </Modal>
    </div>
  );
}

const NEXT: Record<string, string[]> = {
  draft: ["under_review"], under_review: ["confirmed_by_reviewer", "disputed", "rejected", "draft"],
  disputed: ["under_review", "rejected", "superseded"], confirmed_by_reviewer: ["superseded", "disputed"], rejected: ["draft"], superseded: [],
};

export function InvestigationDetail() {
  const { invId } = useParams();
  const pid = useProjectId();
  const nav = useNavigate();
  const inv = usePQuery<any>(["investigation", invId], `/investigations/${invId}`);
  const members = usePQuery<any[]>(["members"], "/members");
  const [err, setErr] = useState<unknown>(null);
  const [evOpen, setEvOpen] = useState(false);
  const [ev, setEv] = useState({ source_type: "record", source_ref: "", excerpt: "" });
  const [fOpen, setFOpen] = useState(false);
  const [f, setF] = useState({ title: "", statement: "", basis: "analyst_assessment" });
  const [note, setNote] = useState("");
  const canReview = useCan("finding.review");
  if (inv.isLoading) return <Spinner />;
  if (!inv.data) return <ErrorBox error={inv.error} />;
  const d = inv.data;
  const call = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); inv.refetch(); } catch (e) { setErr(e); } };
  const evById = Object.fromEntries(d.evidence.map((e: any) => [e.id, e]));
  return (
    <div className="space-y-3">
      <PageHeader title={d.title} subtitle={<><StatusBadge status={d.status} /> <Badge>{d.classification}</Badge> {d.objective}</>}
        actions={<button className="btn" onClick={() => nav(`/reports?investigation=${d.id}`)}>Build report</button>} />
      <ErrorBox error={err} />
      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Scope & collaborators">
          <p className="mb-2 text-xs">{d.scope || <span className="text-muted">No scope statement.</span>}</p>
          <ul className="text-xs">{d.collaborators.map((c: string) => <li key={c}>{members.data?.find((m) => m.user_id === c)?.display_name ?? c}</li>)}</ul>
          <select className="input mt-2" onChange={(e) => e.target.value && call(() => api(pp(pid, `/investigations/${d.id}/collaborators/${e.target.value}`), { method: "PUT" }))} value="">
            <option value="">Add collaborator…</option>
            {(members.data ?? []).filter((m) => !d.collaborators.includes(m.user_id)).map((m) => <option key={m.user_id} value={m.user_id}>{m.display_name} ({m.role})</option>)}
          </select>
        </Card>
        <Card title="Linked items">
          {d.items.map((i: any) => <p key={i.id} className="text-xs"><Badge>{i.item_type}</Badge> {i.label}</p>)}
          {!d.items.length && <p className="text-xs text-muted">Link datasets, entities, snapshots and analyses by id.</p>}
          <LinkItem onAdd={(item_type, ref_id) => call(() => api(pp(pid, `/investigations/${d.id}/items`), { body: { item_type, ref_id } }))} />
        </Card>
        <Card title="Notes">
          <div className="max-h-48 space-y-1 overflow-auto text-xs">{d.notes.map((n: any) => <p key={n.id}><span className="text-muted">{fmtTime(n.created_at)}</span> {n.body}</p>)}</div>
          <textarea className="input mt-2" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn mt-1" disabled={!note} onClick={() => call(async () => { await api(pp(pid, `/investigations/${d.id}/notes`), { body: { body: note } }); setNote(""); })}>Add note</button>
        </Card>
      </div>
      <Card title={`Evidence (${d.evidence.length})`} actions={<button className="btn" onClick={() => setEvOpen(true)}>Capture evidence</button>} bodyClass="">
        <Table columns={["ID", "Source", "Location", "Excerpt", "Classification", "Rev", "Captured"]} rows={d.evidence.map((e: any) => [
          <code className="font-mono text-xxs">{e.id.slice(-8)}</code>, `${e.source_type}`, e.location.page ? `${e.location.page_label} ${e.location.page}` : e.location.row_index != null ? `row ${e.location.row_index + 1}` : "",
          <span className="line-clamp-3">{e.excerpt}</span>, <Badge>{e.classification}</Badge>, e.revision, fmtTime(e.captured_at)])} empty="No evidence captured" />
      </Card>
      <Card title={`Findings (${d.findings.length})`} actions={<button className="btn btn-primary" onClick={() => setFOpen(true)}>New finding</button>}>
        <div className="space-y-2">
          {d.findings.map((fd: any) => (
            <div key={fd.id} className="rounded border border-line p-2 text-xs">
              <div className="flex items-center gap-2"><b>{fd.title}</b><StatusBadge status={fd.status} /><Badge tone={fd.basis === "model_hypothesis" ? "hypo" : "neutral"}>{fd.basis.replaceAll("_", " ")}</Badge>
                <span className="ml-auto flex gap-1">{NEXT[fd.status].map((s) => (["confirmed_by_reviewer", "disputed", "rejected"].includes(s) && !canReview) ? null :
                  <button key={s} className="btn" onClick={() => {
                    const note = prompt(`Note for ${s.replaceAll("_", " ")}:`) ?? "";
                    const superseded_by_id = s === "superseded" ? prompt("Superseding finding id:") ?? undefined : undefined;
                    call(() => api(pp(pid, `/investigations/${d.id}/findings/${fd.id}/status`), { body: { status: s, note, superseded_by_id } }));
                  }}>{s.replaceAll("_", " ")}</button>)}</span></div>
              <p className="my-1">{fd.statement}</p>
              <div className="grid gap-2 md:grid-cols-2">
                <div><span className="label text-ok">Supporting</span>{fd.supporting.map((id: string) => <p key={id} className="line-clamp-2 text-muted">• {evById[id]?.excerpt}</p>)}</div>
                <div><span className="label text-danger">Contradicting</span>{fd.contradicting.map((id: string) => <p key={id} className="line-clamp-2 text-muted">• {evById[id]?.excerpt}</p>)}</div>
              </div>
              <div className="mt-1 flex gap-1">
                <select className="input w-64" value="" onChange={(e) => { const [stance, id] = e.target.value.split(":"); if (id) call(() => api(pp(pid, `/investigations/${d.id}/findings/${fd.id}/evidence`), { body: { evidence_id: id, stance } })); }}>
                  <option value="">Link evidence…</option>
                  {d.evidence.flatMap((e: any) => [<option key={`s${e.id}`} value={`supporting:${e.id}`}>supports: {e.excerpt.slice(0, 50)}</option>,
                    <option key={`c${e.id}`} value={`contradicting:${e.id}`}>contradicts: {e.excerpt.slice(0, 50)}</option>])}
                </select>
              </div>
              <details className="mt-1"><summary className="cursor-pointer text-muted">History ({fd.history.length})</summary>
                {fd.history.map((h: any, i: number) => <p key={i} className="text-xxs text-muted">{h.at} · {h.from ?? ""} → {h.status} · {h.note}</p>)}</details>
            </div>
          ))}
        </div>
      </Card>
      <Modal open={evOpen} title="Capture evidence" onClose={() => setEvOpen(false)}>
        <div className="space-y-2">
          <Field label="Source type"><select className="input" value={ev.source_type} onChange={(e) => setEv({ ...ev, source_type: e.target.value })}>
            {["record", "document_chunk", "entity", "relationship", "analysis_run"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Source id" hint="Record ids appear in dataset views; passage ids in search results and the document assistant."><input className="input font-mono" value={ev.source_ref} onChange={(e) => setEv({ ...ev, source_ref: e.target.value })} /></Field>
          <Field label="Excerpt (optional; must be verbatim for document passages)"><textarea className="input" rows={3} value={ev.excerpt} onChange={(e) => setEv({ ...ev, excerpt: e.target.value })} /></Field>
          <button className="btn btn-primary" disabled={!ev.source_ref} onClick={() => call(async () => { await api(pp(pid, `/investigations/${d.id}/evidence`), { body: { ...ev, excerpt: ev.excerpt || undefined } }); setEvOpen(false); })}>Capture</button>
        </div>
      </Modal>
      <Modal open={fOpen} title="New finding" onClose={() => setFOpen(false)}>
        <div className="space-y-2">
          <Field label="Title"><input className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Statement"><textarea className="input" rows={4} value={f.statement} onChange={(e) => setF({ ...f, statement: e.target.value })} /></Field>
          <Field label="Basis"><select className="input" value={f.basis} onChange={(e) => setF({ ...f, basis: e.target.value })}>
            {["direct_evidence", "deterministic_calculation", "analyst_assessment", "model_hypothesis"].map((b) => <option key={b}>{b}</option>)}</select></Field>
          <button className="btn btn-primary" disabled={!f.title || !f.statement} onClick={() => call(async () => { await api(pp(pid, `/investigations/${d.id}/findings`), { body: f }); setFOpen(false); })}>Create (draft)</button>
        </div>
      </Modal>
    </div>
  );
}

function LinkItem({ onAdd }: { onAdd: (type: string, ref: string) => void }) {
  const [t, setT] = useState("dataset");
  const [r, setR] = useState("");
  return (
    <div className="mt-2 flex gap-1">
      <select className="input w-32" value={t} onChange={(e) => setT(e.target.value)}>{["dataset", "entity", "saved_query", "graph_snapshot", "analysis_run", "document", "report"].map((x) => <option key={x}>{x}</option>)}</select>
      <input className="input font-mono" placeholder="id" value={r} onChange={(e) => setR(e.target.value)} />
      <button className="btn" disabled={!r} onClick={() => { onAdd(t, r); setR(""); }}>Link</button>
    </div>
  );
}
