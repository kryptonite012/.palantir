import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, pp } from "../../services/api";
import { useGlobalCan, useProject, useProjectId } from "../../app/hooks";
import { Badge, Card, Empty, PageHeader, Spinner, Stat, StatusBadge, Table, fmtBytes, fmtNum, fmtTime } from "../../components/ui";
import { Chart } from "../../components/Chart";
import type { Dataset, Job } from "../../types/api";

const ACTION_LABEL: Record<string, string> = {
  "ingest.started": "started an import", "ingest.completed": "imported a dataset version", "entity.match_accepted": "merged two entities",
  "entity.match_rejected": "rejected a match", "entity.merge_reverted": "reverted a merge", "entity.resolution_started": "ran entity resolution",
  "entity.watch": "started watching an entity", "relationship.create_manual": "asserted a relationship", "relationship.status_changed": "reviewed a relationship",
  "analysis.run": "ran an analysis", "analysis.reproduce": "reproduced an analysis", "export.report": "exported a report", "report.create": "created a report",
  "investigation.create": "opened an investigation", "finding.create": "drafted a finding", "finding.status_changed": "updated a finding",
  "evidence.capture": "captured evidence", "workflow.run_started": "ran a workflow", "workflow.create": "created a workflow",
  "dataset.update": "updated dataset settings", "dataset.delete": "deleted a dataset", "document.process_started": "added a document",
  "graph.snapshot_created": "saved a graph snapshot", "graph.explain": "explained a connection", "project.create": "created the project",
  "demo.loaded": "loaded the synthetic demo data", "permission.member_set": "changed membership", "retention.purge": "purged expired data",
};

export function Home() {
  const pid = useProjectId();
  const nav = useNavigate();
  const project = useProject();
  const canCreate = useGlobalCan("project.create");
  const ov = useQuery({ queryKey: ["overview", pid], queryFn: () => api(pp(pid, "/overview")), enabled: !!pid, refetchInterval: 20_000 });
  const ins = useQuery({ queryKey: ["insights", pid], queryFn: () => api(pp(pid, "/insights")), enabled: !!pid, refetchInterval: 30_000 });
  const act = useQuery<any[]>({ queryKey: ["activity", pid], queryFn: () => api(pp(pid, "/activity"), { params: { limit: 14 } }), enabled: !!pid, refetchInterval: 20_000 });
  const watches = useQuery<any[]>({ queryKey: ["watches", pid], queryFn: () => api(pp(pid, "/watches")), enabled: !!pid });
  const datasets = useQuery<Dataset[]>({ queryKey: ["datasets", pid], queryFn: () => api(pp(pid, "/datasets")), enabled: !!pid });
  const jobs = useQuery<Job[]>({ queryKey: ["jobs-home", pid], queryFn: () => api("/api/jobs", { params: { project_id: pid, limit: 6 } }), enabled: !!pid, refetchInterval: 10_000 });

  if (!pid) {
    return (
      <Empty title="Welcome to Project Atlas" action={<div className="flex gap-2">
        {canCreate && <button className="btn btn-primary" onClick={() => nav("/projects?demo=1")}>Explore the synthetic demo</button>}
        <button className="btn" onClick={() => nav("/projects")}>Create or open a project</button></div>}>
        Projects are isolated workspaces with their own datasets, ontology, members and audit scope. The demo loads a fully
        fictional logistics review — people, organizations, payments, documents and map data — in about ten seconds.
      </Empty>
    );
  }
  if (ov.isLoading) return <Spinner />;
  const o = ov.data ?? {};
  const i = ins.data ?? {};
  const rel = o.relationships_by_assertion ?? {};
  const empty = !o.datasets && !o.documents;
  const running = (jobs.data ?? []).filter((j) => j.status === "running" || j.status === "queued");
  return (
    <div className="space-y-4">
      <PageHeader title={project.data?.name ?? "Atlas Home"}
        subtitle={<>{project.data?.description && <>{project.data.description} · </>}Role: {project.data?.role_label} · <Badge>{project.data?.classification}</Badge>
          {project.data?.archived && <> <Badge tone="warn">archived</Badge></>} · figures computed locally from this project</>}
        actions={<><button className="btn" onClick={() => window.dispatchEvent(new Event("atlas:palette"))}>Jump to… <span className="kbd">Ctrl K</span></button>
          <button className="btn" onClick={() => nav("/projects")}>Projects</button></>} />
      {running.length > 0 && (
        <div className="card flex items-center gap-3 px-3 py-2 text-xs">
          <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
          {running.map((j) => <span key={j.id}><b>{j.kind}</b> {j.message} <span className="font-mono">{Math.round(j.progress * 100)}%</span></span>)}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Datasets" value={fmtNum(o.datasets)} onClick={() => nav("/catalog")} />
        <Stat label="Indexed records" value={fmtNum(o.records)} hint="current versions" onClick={() => nav("/catalog")} />
        <Stat label="Entities" value={fmtNum(o.entities)} onClick={() => nav("/entities")} />
        <Stat label="Relationships" value={fmtNum(o.relationships)} onClick={() => nav("/graph")} />
        <Stat label="Documents" value={fmtNum(o.documents)} onClick={() => nav("/documents")} />
        <Stat label="Quality issues" value={fmtNum(o.quality_issues_current)} hint="current versions" onClick={() => nav("/catalog")} />
        <Stat label="Storage" value={fmtBytes(o.storage_bytes ?? 0)} hint="uploaded originals" onClick={() => nav("/admin")} />
        <Stat label="Local AI" value={o.ai?.healthy_models ? `${o.ai.healthy_models} model(s)` : "Off"} hint={o.ai?.enabled ? "enabled" : "optional"} onClick={() => nav("/admin?tab=models")} />
      </div>
      {empty ? (
        <Empty title="This project has no data yet" action={<div className="flex gap-2">
          <button className="btn btn-primary" onClick={() => nav("/ingestion")}>Import a dataset</button>
          <button className="btn" onClick={() => nav("/documents")}>Add documents</button></div>}>
          Import CSV, spreadsheets, JSON, XML, SQLite or Parquet, or add PDF/Word/e-mail documents. Every import is validated in a dry run first.
        </Empty>
      ) : (
        <div className="grid gap-3 xl:grid-cols-3">
          <Card title="Events over time" className="xl:col-span-2">
            {(i.events_by_month ?? []).length ? (
              <Chart height={200} option={{ xAxis: { type: "category", data: i.events_by_month.map((m: any) => m.month) }, yAxis: { type: "value" },
                series: [{ type: "bar", data: i.events_by_month.map((m: any) => m.count), itemStyle: { borderRadius: [3, 3, 0, 0] } }] }} />
            ) : <p className="text-xs text-muted">No timeline events. Map a date/time field to events during import.</p>}
          </Card>
          <Card title="Relationships by basis">
            {Object.keys(rel).length ? (
              <Chart height={200} option={{ tooltip: { trigger: "item" }, series: [{ type: "pie", radius: ["48%", "72%"],
                data: Object.entries(rel as Record<string, number>).map(([k, v]) => ({ name: k, value: v })), label: { color: "inherit", fontSize: 10 } }] }} />
            ) : <p className="text-xs text-muted">No relationships yet.</p>}
          </Card>
          <Card title="Most connected entities" bodyClass="">
            <Table columns={["Entity", "Type", "Links"]} rows={(i.top_connected ?? []).map((e: any) => [
              <button className="text-accent hover:underline" onClick={() => nav(`/entities/${e.id}`)}>{e.label}</button>, <Badge>{e.entity_type}</Badge>,
              <span className="font-mono">{e.degree}</span>])} empty="No relationships" />
          </Card>
          <Card title="Entities by type">
            {Object.keys(i.entities_by_type ?? {}).length ? (
              <Chart height={190} option={{ grid: { left: 90, right: 16, top: 8, bottom: 24 }, xAxis: { type: "value" },
                yAxis: { type: "category", data: Object.keys(i.entities_by_type) }, series: [{ type: "bar", data: Object.values(i.entities_by_type) }] }} />
            ) : <p className="text-xs text-muted">No entities.</p>}
          </Card>
          <Card title="Data quality (current versions)">
            {Object.keys(i.quality_by_check ?? {}).length ? (
              <ul className="space-y-1 text-xs">{Object.entries(i.quality_by_check as Record<string, number>).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                <li key={k} className="flex items-center gap-2"><span className="w-40 truncate">{k.replaceAll("_", " ")}</span>
                  <span className="h-2 rounded bg-warn/60" style={{ width: `${Math.max(4, Math.min(100, (v / Math.max(...Object.values(i.quality_by_check as Record<string, number>))) * 100))}%` }} />
                  <span className="font-mono">{v}</span></li>))}</ul>
            ) : <p className="text-xs text-ok">No quality issues in current versions.</p>}
            <button className="btn mt-2" onClick={() => nav("/catalog")}>Review in catalog</button>
          </Card>
        </div>
      )}
      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Recent activity" className="xl:col-span-2" bodyClass="divide-y divide-line/50">
          {(act.data ?? []).map((a) => (
            <div key={a.seq} className="flex items-center gap-2 px-3 py-1.5 text-xs">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[10px] font-bold text-accent">{a.actor[0]?.toUpperCase()}</span>
              <span><b>{a.actor}</b> {ACTION_LABEL[a.action] ?? a.action}</span>
              <span className="ml-auto whitespace-nowrap text-[10px] text-muted">{fmtTime(a.ts)}</span>
            </div>
          ))}
          {!act.data?.length && <p className="p-3 text-xs text-muted">No activity yet.</p>}
        </Card>
        <div className="space-y-3">
          <Card title={`Watching (${watches.data?.length ?? 0})`}>
            {(watches.data ?? []).map((w) => <button key={w.id} className="block text-xs text-accent hover:underline" onClick={() => nav(`/entities/${w.entity_id}`)}>{w.display_name} <span className="text-muted">({w.entity_type})</span></button>)}
            {!watches.data?.length && <p className="text-xs text-muted">Watch an entity (Entity Explorer → entity → Watch) to be alerted when new data mentions it.</p>}
          </Card>
          <Card title="Recent jobs" bodyClass="">
            <Table columns={["Kind", "Status", "Finished"]} rows={(jobs.data ?? []).map((j) => [j.kind, <StatusBadge status={j.status} />, fmtTime(j.finished_at)])} empty="No jobs yet" />
          </Card>
        </div>
      </div>
      {!empty && (
        <Card title="Datasets" bodyClass="">
          <Table columns={["Name", "Version", "Records", "Quality issues", "Imported", ""]}
            rows={(datasets.data ?? []).map((d) => [
              <button className="text-accent hover:underline" onClick={() => nav(`/catalog/${d.id}`)}>{d.name}</button>,
              `v${d.current_version}`, fmtNum(d.latest?.record_count),
              fmtNum(Object.values(d.latest?.quality?.issue_counts ?? {}).reduce((a, b) => a + b, 0)),
              fmtTime(d.latest?.imported_at), d.is_synthetic ? <Badge tone="hypo">synthetic</Badge> : null])} />
        </Card>
      )}
    </div>
  );
}
