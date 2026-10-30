import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, download } from "../../services/api";
import { useGlobalCan, useProject, useProjectId } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, Json, Notice, PageHeader, Table, fmtTime } from "../../components/ui";

export function AuditPage() {
  const pid = useProjectId();
  const project = useProject();
  const isAuditor = useGlobalCan("audit.read");
  const [f, setF] = useState({ action: "", actor: "", outcome: "", scope: isAuditor ? "all" : "project", offset: 0 });
  const [verify, setVerify] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const canProject = project.data?.role === "project_admin";
  const q = useQuery({
    queryKey: ["audit", f, pid],
    queryFn: () => api("/api/admin/audit", { params: { action: f.action, actor: f.actor, outcome: f.outcome, project_id: f.scope === "project" ? pid : undefined, limit: 100, offset: f.offset } }),
    enabled: isAuditor || canProject,
  });
  if (!isAuditor && !canProject) return <Notice tone="warn">The Audit Center requires a system or security administrator, or a project administrator (project scope).</Notice>;
  return (
    <div className="space-y-3">
      <PageHeader title="Audit Center" subtitle="Append-only, hash-chained audit log of security-relevant operations."
        actions={<>
          {isAuditor && <button className="btn" onClick={() => api("/api/admin/audit/verify", { method: "POST" }).then(setVerify).catch(setErr)}>Verify chain</button>}
          {isAuditor && <button className="btn" onClick={() => api("/api/admin/audit/checkpoint", { method: "POST" }).then((r) => setVerify({ checkpoint: r })).catch(setErr)}>Signed checkpoint</button>}
          <button className="btn" onClick={() => download("/api/admin/audit/export", "atlas-audit.csv", { params: { project_id: f.scope === "project" ? pid : undefined } }).catch(setErr)}>Export CSV</button>
        </>} />
      <ErrorBox error={err} />
      {verify?.valid !== undefined && <Notice tone={verify.valid ? "ok" : "warn"}>{verify.valid ? `Chain intact: ${verify.events_checked} events verified, ${verify.checkpoints?.checked ?? 0} signed checkpoints valid.`
        : `Chain BROKEN at sequence ${verify.broken_at_seq ?? "?"} ${verify.checkpoints?.reason ?? ""}`} Head {verify.head?.slice(0, 16)}…</Notice>}
      {verify?.checkpoint && <Notice tone="ok">Checkpoint written at seq {verify.checkpoint.seq}. Copy <code>audit-checkpoints.jsonl</code> to separate media for stronger tamper evidence.</Notice>}
      <Notice tone="warn">Limitation: an administrator with full control of this machine's storage and the checkpoint key could rewrite history undetectably. Export checkpoints externally.</Notice>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Action prefix"><input className="input w-44" value={f.action} onChange={(e) => setF({ ...f, action: e.target.value, offset: 0 })} placeholder="e.g. auth." /></Field>
        <Field label="Actor"><input className="input w-36" value={f.actor} onChange={(e) => setF({ ...f, actor: e.target.value, offset: 0 })} /></Field>
        <Field label="Outcome"><select className="input w-32" value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value, offset: 0 })}><option value="">any</option><option>success</option><option>denied</option><option>failure</option></select></Field>
        <Field label="Scope"><select className="input w-36" value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value, offset: 0 })}>
          {isAuditor && <option value="all">All projects</option>}<option value="project">Active project</option></select></Field>
        <span className="ml-auto text-xxs text-muted">{q.data?.total ?? 0} events</span>
        <button className="btn" disabled={f.offset === 0} onClick={() => setF({ ...f, offset: Math.max(0, f.offset - 100) })}>‹</button>
        <button className="btn" disabled={f.offset + 100 >= (q.data?.total ?? 0)} onClick={() => setF({ ...f, offset: f.offset + 100 })}>›</button>
      </div>
      <div className="grid gap-3 xl:grid-cols-[1fr_360px]">
        <Card bodyClass="">
          <Table maxHeight={620} columns={["Seq", "Time", "Actor", "Action", "Resource", "Outcome", "Hash"]} rows={(q.data?.events ?? []).map((e: any) => [
            <button className="text-accent hover:underline" onClick={() => setDetail(e)}>{e.seq}</button>, fmtTime(e.ts), e.actor_name, <code className="font-mono">{e.action}</code>,
            `${e.resource_type}${e.resource_id ? ":" + e.resource_id.slice(-8) : ""}`,
            <Badge tone={e.outcome === "success" ? "ok" : e.outcome === "denied" ? "warn" : "danger"}>{e.outcome}</Badge>, <code className="font-mono text-xxs text-muted">{e.hash.slice(0, 10)}</code>])} />
        </Card>
        {detail && <Card title={`Event ${detail.seq}`}><Json value={detail} max={560} /></Card>}
      </div>
    </div>
  );
}
