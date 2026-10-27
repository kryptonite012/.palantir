import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, pp } from "../../services/api";
import { useProject, useProjectId } from "../../app/hooks";
import { Card, Empty, PageHeader, Spinner, Stat, Table, StatusBadge, fmtBytes, fmtNum, fmtTime, Badge } from "../../components/ui";
import { Chart } from "../../components/Chart";
import type { Dataset, Job } from "../../types/api";

export function Home() {
  const pid = useProjectId();
  const nav = useNavigate();
  const project = useProject();
  const ov = useQuery({ queryKey: ["overview", pid], queryFn: () => api(pp(pid, "/overview")), enabled: !!pid });
  const datasets = useQuery<Dataset[]>({ queryKey: ["datasets", pid], queryFn: () => api(pp(pid, "/datasets")), enabled: !!pid });
  const jobs = useQuery<Job[]>({ queryKey: ["jobs-home", pid], queryFn: () => api("/api/jobs", { params: { project_id: pid, limit: 8 } }), enabled: !!pid });

  if (!pid) {
    return (
      <Empty title="No project selected" action={<button className="btn btn-primary" onClick={() => nav("/projects")}>Create or open a project</button>}>
        Projects are isolated workspaces with their own datasets, ontology, members and audit scope.
      </Empty>
    );
  }
  if (ov.isLoading) return <Spinner />;
  const o = ov.data ?? {};
  const rel = o.relationships_by_assertion ?? {};
  const empty = !o.datasets && !o.documents;
  return (
    <div className="space-y-4">
      <PageHeader title={project.data?.name ?? "Atlas Home"}
        subtitle={<>Role: {project.data?.role_label} · classification <Badge>{project.data?.classification}</Badge> · all figures computed locally from this project's data</>}
        actions={<button className="btn" onClick={() => nav("/projects")}>Projects</button>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Datasets" value={fmtNum(o.datasets)} onClick={() => nav("/catalog")} />
        <Stat label="Indexed records" value={fmtNum(o.records)} hint="current versions" onClick={() => nav("/catalog")} />
        <Stat label="Entities" value={fmtNum(o.entities)} onClick={() => nav("/entities")} />
        <Stat label="Relationships" value={fmtNum(o.relationships)} onClick={() => nav("/graph")} />
        <Stat label="Documents" value={fmtNum(o.documents)} onClick={() => nav("/documents")} />
        <Stat label="Quality issues" value={fmtNum(o.quality_issues_current)} hint="current versions" onClick={() => nav("/catalog")} />
        <Stat label="Storage" value={fmtBytes(o.storage_bytes ?? 0)} hint="uploaded originals" onClick={() => nav("/admin")} />
        <Stat label="Local AI" value={o.ai?.healthy_models ? `${o.ai.healthy_models} model(s)` : "Off"} hint={o.ai?.enabled ? "enabled" : "optional"} onClick={() => nav("/admin")} />
      </div>
      {empty ? (
        <Empty title="This project has no data yet" action={<button className="btn btn-primary" onClick={() => nav("/ingestion")}>Import a dataset</button>}>
          Start by importing a CSV, spreadsheet, JSON, XML, SQLite or Parquet file. Synthetic demonstration data is in <code>sample-data/</code>.
        </Empty>
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          <Card title="Relationships by basis" className="lg:col-span-1">
            {Object.keys(rel).length ? (
              <Chart height={220} option={{ tooltip: { trigger: "item" }, series: [{ type: "pie", radius: ["45%", "70%"],
                data: Object.entries(rel as Record<string, number>).map(([k, v]) => ({ name: k, value: v })), label: { color: "inherit" } }] }} />
            ) : <p className="text-xs text-muted">No relationships yet.</p>}
          </Card>
          <Card title="Datasets" className="lg:col-span-2" bodyClass="">
            <Table columns={["Name", "Version", "Records", "Quality issues", "Imported", ""]}
              rows={(datasets.data ?? []).map((d) => [
                <button className="text-accent hover:underline" onClick={() => nav(`/catalog/${d.id}`)}>{d.name}</button>,
                `v${d.current_version}`, fmtNum(d.latest?.record_count),
                fmtNum(Object.values(d.latest?.quality?.issue_counts ?? {}).reduce((a, b) => a + b, 0)),
                fmtTime(d.latest?.imported_at), d.is_synthetic ? <Badge tone="hypo">synthetic</Badge> : null])} />
          </Card>
        </div>
      )}
      <Card title="Recent jobs" bodyClass="">
        <Table columns={["Kind", "Status", "Message", "Started", "Finished"]}
          rows={(jobs.data ?? []).map((j) => [j.kind, <StatusBadge status={j.status} />, j.error ?? j.message, fmtTime(j.created_at), fmtTime(j.finished_at)])}
          empty="No jobs yet" />
      </Card>
    </div>
  );
}
