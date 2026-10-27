import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, pp, waitForJob } from "../../services/api";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { AssertionBadge, Badge, Card, Empty, ErrorBox, Field, Modal, Notice, PageHeader, Spinner, StatusBadge, Table, Tabs, fmtNum, fmtTime } from "../../components/ui";
import type { EntityView } from "../../types/api";

export function EntityExplorer() {
  const nav = useNavigate();
  const [tab, setTab] = useState<"entities" | "review" | "merges">("entities");
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const onto = usePQuery<any>(["ontology"], "/ontology");
  const ents = usePQuery<{ total: number; entities: EntityView[] }>(["entities"], "/entities", { entity_type: type, q, limit: 50, offset }, tab === "entities");
  return (
    <div className="space-y-3">
      <PageHeader title="Entity Explorer" subtitle="Resolved people, organizations, locations and other ontology types with full provenance." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "entities", label: "Entities" }, { id: "review", label: "Match review" }, { id: "merges", label: "Merge history" }]} />
      {tab === "entities" && (
        <>
          <div className="flex gap-2">
            <select className="input w-48" value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }} aria-label="Entity type">
              <option value="">All types</option>
              {(onto.data?.entity_types ?? []).map((t: any) => <option key={t.name} value={t.name}>{t.label}</option>)}
            </select>
            <input className="input max-w-sm" placeholder="Filter by name…" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
            <span className="ml-auto self-center text-xxs text-muted">{fmtNum(ents.data?.total)} entities</span>
            <button className="btn" disabled={offset === 0} onClick={() => setOffset(offset - 50)}>‹</button>
            <button className="btn" disabled={offset + 50 >= (ents.data?.total ?? 0)} onClick={() => setOffset(offset + 50)}>›</button>
          </div>
          {ents.isLoading ? <Spinner /> : !ents.data?.total ? <Empty title="No entities">Entities are created when imports map fields to ontology types.</Empty> : (
            <Card bodyClass="">
              <Table columns={["Name", "Type", "Relationships", "Attributes", "Redacted"]} rows={ents.data.entities.map((e) => [
                <button className="font-medium text-accent hover:underline" onClick={() => nav(`/entities/${e.id}`)}>{e.display_name}</button>,
                <Badge>{e.entity_type}</Badge>, e.relationship_count ?? 0,
                <span className="text-muted">{Object.entries(e.attributes).filter(([k]) => k !== "name").slice(0, 4).map(([k, v]) => `${k}: ${v.join(" | ")}`).join(" · ")}</span>,
                e.redacted_fields.length ? <Badge tone="warn">{e.redacted_fields.join(", ")}</Badge> : ""])} />
            </Card>
          )}
        </>
      )}
      {tab === "review" && <MatchReview />}
      {tab === "merges" && <MergeHistory />}
    </div>
  );
}

function MatchReview() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const [status, setStatus] = useState("pending");
  const [band, setBand] = useState("");
  const [job, setJob] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const canResolve = useCan("entity.resolve");
  const canReview = useCan("entity.review");
  const cands = usePQuery<any>(["candidates"], "/match-candidates", { status, band, limit: 100 });
  const resolve = async () => {
    setErr(null);
    try {
      const j = await api(pp(pid, "/entities/resolve"), { body: {} });
      setJob(await waitForJob(j.id, setJob));
      cands.refetch();
    } catch (e) { setErr(e); }
  };
  const review = async (c: any, decision: "accept" | "reject", survivor?: string) => {
    const note = prompt(decision === "accept" ? "Reason for accepting this match (recorded in audit):" : "Reason for rejecting:") ?? "";
    try {
      await api(pp(pid, `/match-candidates/${c.id}/review`), { body: { decision, note, survivor_id: survivor } });
      cands.refetch();
      qc.invalidateQueries({ queryKey: [pid, "entities"] });
    } catch (e) { setErr(e); }
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {canResolve && <button className="btn btn-primary" onClick={resolve}>Run entity resolution</button>}
        <select className="input w-32" value={status} onChange={(e) => setStatus(e.target.value)}><option>pending</option><option>accepted</option><option>rejected</option><option>all</option></select>
        <select className="input w-32" value={band} onChange={(e) => setBand(e.target.value)}><option value="">all bands</option><option>strong</option><option>ambiguous</option></select>
        {job && <span className="text-xs">Job <StatusBadge status={job.status} /> {job.result?.candidates_created != null && `${job.result.candidates_created} new candidates`}</span>}
      </div>
      <Notice>Every merge requires a reviewer decision. Scores are similarity measures (algorithm <code>er-1.1</code>), not calibrated probabilities. Fields missing on either side are not compared and never count as agreement.</Notice>
      <ErrorBox error={err} />
      {(cands.data?.candidates ?? []).map((c: any) => (
        <Card key={c.id} title={<span className="flex items-center gap-2"><StatusBadge status={c.band} /> score <span className="font-mono">{c.score.toFixed(3)}</span> <Badge>{c.entity_type}</Badge> <StatusBadge status={c.status} /></span>}
          actions={canReview && c.status === "pending" && <>
            <button className="btn btn-primary" onClick={() => review(c, "accept", c.entity_a.id)}>Merge into “{c.entity_a.display_name}”</button>
            <button className="btn" onClick={() => review(c, "accept", c.entity_b.id)}>Merge into “{c.entity_b.display_name}”</button>
            <button className="btn btn-danger" onClick={() => review(c, "reject")}>Not the same</button></>}>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <Table columns={["Feature", c.entity_a.display_name, c.entity_b.display_name, "Similarity", "Method"]} rows={c.evidence.features.map((f: any) => [
                f.feature, Array.isArray(f.a) ? f.a.join(", ") : f.a, Array.isArray(f.b) ? f.b.join(", ") : f.b,
                <span className={`font-mono ${f.similarity >= 0.9 ? "text-ok" : f.similarity === 0 ? "text-danger" : "text-warn"}`}>{f.similarity.toFixed(2)}</span>, <span className="text-xxs text-muted">{f.method}</span>])} />
            </div>
            <div className="space-y-1 text-xs">
              <p><b>Matching:</b> {c.evidence.matching_fields.join(", ") || "—"}</p>
              <p><b className="text-danger">Conflicting:</b> {c.evidence.conflicting_fields.join(", ") || "none"}</p>
              <p><b className="text-muted">Not compared (missing):</b> {c.evidence.not_compared.join(", ") || "—"}</p>
              <p><b>Sources:</b> {Object.values(c.evidence.sources ?? {}).map((s: any) => s.length).join(" + ")} records · algorithm {c.algorithm_version}</p>
              {c.review_note && <p><b>Review note:</b> {c.review_note}</p>}
            </div>
          </div>
        </Card>
      ))}
      {cands.data && !cands.data.candidates.length && <Empty title="No candidates">Run entity resolution to generate match candidates for review.</Empty>}
    </div>
  );
}

function MergeHistory() {
  const pid = useProjectId();
  const merges = usePQuery<any[]>(["merges"], "/merges");
  const canReview = useCan("entity.review");
  const [err, setErr] = useState<unknown>(null);
  const nav = useNavigate();
  return (
    <Card bodyClass="">
      <ErrorBox error={err} />
      <Table columns={["When", "Survivor", "Merged record", "Status", ""]} rows={(merges.data ?? []).map((m) => [
        fmtTime(m.performed_at), <button className="text-accent hover:underline" onClick={() => nav(`/entities/${m.survivor_id}`)}>{m.survivor_id.slice(-8)}</button>,
        m.merged_name, m.reverted_at ? <Badge tone="warn">reverted {fmtTime(m.reverted_at)}</Badge> : <Badge tone="ok">active</Badge>,
        canReview && !m.reverted_at && <button className="btn" onClick={() => api(pp(pid, `/merges/${m.id}/revert`), { method: "POST" }).then(() => merges.refetch()).catch(setErr)}>Revert</button>])}
        empty="No merges yet" />
    </Card>
  );
}

export function EntityDetail() {
  const { entityId } = useParams();
  const pid = useProjectId();
  const nav = useNavigate();
  const e = usePQuery<any>(["entity", entityId], `/entities/${entityId}`);
  const onto = usePQuery<any>(["ontology"], "/ontology");
  const canGraph = useCan("graph.write");
  const [relOpen, setRelOpen] = useState(false);
  const [rel, setRel] = useState({ target: "", rel_type: "associated_with", justification: "" });
  const [targetQ, setTargetQ] = useState("");
  const targets = usePQuery<any>(["entities-pick", targetQ], "/entities", { q: targetQ, limit: 10 }, relOpen && targetQ.length > 1);
  const [err, setErr] = useState<unknown>(null);
  if (e.isLoading) return <Spinner />;
  if (!e.data) return <ErrorBox error={e.error} />;
  const d = e.data;
  const addRel = async () => {
    try {
      await api(pp(pid, "/relationships"), { body: { source_entity_id: d.id, target_entity_id: rel.target, rel_type: rel.rel_type, justification: rel.justification } });
      setRelOpen(false);
      e.refetch();
    } catch (x) { setErr(x); }
  };
  return (
    <div className="space-y-3">
      <PageHeader title={d.display_name} subtitle={<><Badge>{d.entity_type}</Badge> <code className="font-mono text-xxs">{d.id}</code> {d.status !== "active" && <Badge tone="warn">{d.status} → {d.merged_into_id}</Badge>}</>}
        actions={<>
          <button className="btn" onClick={() => nav(`/graph?center=${d.id}`)}>Open in graph</button>
          <button className="btn" onClick={() => nav(`/timeline?entity=${d.id}`)}>Timeline</button>
          {canGraph && <button className="btn btn-primary" onClick={() => setRelOpen(true)}>Assert relationship</button>}
        </>} />
      <ErrorBox error={err} />
      <div className="grid gap-3 xl:grid-cols-2">
        <Card title="Attributes (with provenance)" bodyClass="">
          <Table columns={["Field", "Source value", "Normalized", "Records", "First source record"]} rows={Object.entries(d.attribute_provenance).flatMap(([f, items]: [string, any]) =>
            items.map((it: any, i: number) => [i === 0 ? <b>{f}</b> : "", String(it.value ?? ""), it.normalized === undefined ? "" : String(it.normalized),
              it.count ?? 1, it.record_id ? <code className="font-mono text-xxs">{it.record_id.slice(-10)}</code> : <Badge tone="warn">manual</Badge>]))} />
        </Card>
        <Card title={`Relationships (${d.relationships.length})`} bodyClass="">
          <Table maxHeight={420} columns={["Direction", "Type", "Other entity", "Basis", "Evidence"]} rows={d.relationships.map((r: any) => [
            r.direction === "out" ? "→" : "←", r.rel_type,
            r.other ? <button className="text-accent hover:underline" onClick={() => nav(`/entities/${r.other.id}`)}>{r.other.display_name}</button> : "—",
            <AssertionBadge kind={r.assertion} status={r.status} />, `${r.evidence_count} item(s)`])} />
        </Card>
        <Card title={`Source records (${d.source_records.length})`} bodyClass="">
          <Table maxHeight={300} columns={["Dataset", "Row", "Record"]} rows={d.source_records.map((s: any) => [
            s.restricted ? <Badge tone="warn">restricted dataset</Badge> : <button className="text-accent hover:underline" onClick={() => nav(`/catalog/${s.dataset_id}`)}>{s.dataset_name}</button>,
            s.row_index + 1, <code className="font-mono text-xxs">{s.record_id}</code>])} />
        </Card>
        <Card title="Linked documents · events · quality" bodyClass="space-y-2 p-3 text-xs">
          {d.linked_documents.map((l: any) => <p key={l.document_id}><button className="text-accent hover:underline" onClick={() => nav(`/documents?doc=${l.document_id}&page=${l.first_page}`)}>{l.title}</button> <span className="text-muted">first mention p.{l.first_page} ({l.link_method})</span></p>)}
          {!d.linked_documents.length && <p className="text-muted">No documents mention this entity by name.</p>}
          <hr className="border-line" />
          {d.events.slice(0, 10).map((ev: any) => <p key={ev.id}>{fmtTime(ev.event_time)} — {ev.title}</p>)}
          {d.events.length > 10 && <p className="text-muted">+{d.events.length - 10} more on the timeline</p>}
          <hr className="border-line" />
          {d.quality_warnings.map((q: any, i: number) => <p key={i} className="text-warn">⚠ {q.check} on {q.field}: {q.message}</p>)}
          {!d.quality_warnings.length && <p className="text-muted">No quality warnings on source records.</p>}
        </Card>
        <Card title="Match & merge history" bodyClass="">
          <Table columns={["When", "Survivor", "Merged", "Reverted"]} rows={d.merge_history.map((m: any) => [fmtTime(m.performed_at), m.survivor_id.slice(-8), m.merged_id.slice(-8), m.reverted_at ? fmtTime(m.reverted_at) : "—"])} empty="No merges" />
        </Card>
      </div>
      <Modal open={relOpen} title="Assert a relationship (recorded as manual)" onClose={() => setRelOpen(false)}>
        <div className="space-y-2">
          <Field label="Find target entity"><input className="input" value={targetQ} onChange={(x) => setTargetQ(x.target.value)} /></Field>
          <select className="input" size={5} value={rel.target} onChange={(x) => setRel({ ...rel, target: x.target.value })}>
            {(targets.data?.entities ?? []).filter((t: any) => t.id !== d.id).map((t: any) => <option key={t.id} value={t.id}>{t.display_name} ({t.entity_type})</option>)}
          </select>
          <Field label="Relationship type"><select className="input" value={rel.rel_type} onChange={(x) => setRel({ ...rel, rel_type: x.target.value })}>
            {(onto.data?.relationship_types ?? []).map((t: any) => <option key={t.name} value={t.name}>{t.label}</option>)}</select></Field>
          <Field label="Justification (required)"><textarea className="input" rows={3} value={rel.justification} onChange={(x) => setRel({ ...rel, justification: x.target.value })} /></Field>
          <button className="btn btn-primary" disabled={!rel.target || rel.justification.length < 3} onClick={addRel}>Save relationship</button>
        </div>
      </Modal>
    </div>
  );
}
