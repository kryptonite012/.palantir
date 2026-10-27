import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, pp } from "../../services/api";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { Badge, Card, Empty, ErrorBox, Json, PageHeader, Spinner, Table, Tabs, fmtNum, fmtTime } from "../../components/ui";
import type { Dataset } from "../../types/api";

export function Catalog() {
  const nav = useNavigate();
  const ds = usePQuery<Dataset[]>(["datasets"], "/datasets");
  const canIngest = useCan("ingest.run");
  return (
    <div className="space-y-3">
      <PageHeader title="Data Catalog" subtitle="Versioned datasets with schema, quality, lineage, access and retention policies."
        actions={canIngest && <button className="btn btn-primary" onClick={() => nav("/ingestion")}>Import data</button>} />
      {ds.isLoading ? <Spinner /> : !ds.data?.length ? (
        <Empty title="No datasets" action={canIngest && <button className="btn btn-primary" onClick={() => nav("/ingestion")}>Import data</button>}>
          Datasets you can access appear here. Restricted datasets are hidden unless your role permits them.
        </Empty>
      ) : (
        <Card bodyClass="">
          <Table columns={["Dataset", "Version", "Records", "Fields", "Errors", "Warnings", "Access", "Retention", "Imported"]}
            rows={ds.data.map((d) => {
              const q = d.latest?.quality ?? {};
              return [
                <button className="font-medium text-accent hover:underline" onClick={() => nav(`/catalog/${d.id}`)}>{d.name}</button>,
                `v${d.current_version}`, fmtNum(d.latest?.record_count), d.latest?.schema.fields.length ?? 0,
                <Badge tone={(q as any).errors ? "danger" : "neutral"}>{fmtNum((q as any).errors ?? 0)}</Badge>,
                <Badge tone={(q as any).warnings ? "warn" : "neutral"}>{fmtNum((q as any).warnings ?? 0)}</Badge>,
                <Badge tone={d.access_policy === "restricted" ? "warn" : "neutral"}>{d.access_policy}</Badge>,
                d.retention_policy, fmtTime(d.latest?.imported_at)];
            })} />
        </Card>
      )}
    </div>
  );
}

export function DatasetDetail() {
  const { datasetId } = useParams();
  const pid = useProjectId();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"records" | "schema" | "quality" | "lineage" | "versions" | "report">("records");
  const [version, setVersion] = useState<number | undefined>();
  const [view, setView] = useState<"normalized" | "raw">("normalized");
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<unknown>(null);
  const d = usePQuery<any>(["dataset", datasetId], `/datasets/${datasetId}`);
  const recs = usePQuery<any>(["records", datasetId], `/datasets/${datasetId}/records`, { version, limit: 50, offset }, tab === "records");
  const quality = usePQuery<any>(["quality", datasetId], `/datasets/${datasetId}/quality`, { version, limit: 200 }, tab === "quality");
  const canWrite = useCan("dataset.write");
  const canManage = useCan("project.manage");
  const canDelete = useCan("dataset.delete");
  if (d.isLoading) return <Spinner />;
  if (d.error || !d.data) return <ErrorBox error={d.error} />;
  const ds = d.data;
  const v = version ? ds.versions.find((x: any) => x.version === version) : ds.versions[0];
  const fields: any[] = ds.latest?.schema.fields ?? [];
  const cols: string[] = view === "normalized" ? fields.map((f) => f.name) : fields.map((f) => f.source);

  const patch = async (body: any) => {
    setErr(null);
    try {
      await api(pp(pid, `/datasets/${ds.id}`), { method: "PATCH", body });
      d.refetch();
    } catch (e) { setErr(e); }
  };
  const del = async () => {
    const name = prompt(`Type the dataset name (${ds.name}) to permanently delete it and its derived records:`);
    if (name === null) return;
    try {
      await api(pp(pid, `/datasets/${ds.id}`), { method: "DELETE", params: { confirm_name: name } });
      qc.invalidateQueries();
      nav("/catalog");
    } catch (e) { setErr(e); }
  };

  return (
    <div className="space-y-3">
      <PageHeader title={ds.name} subtitle={<>{ds.description || "No description"} · {fmtNum(v?.record_count)} records in v{v?.version} · SHA-256 <code className="font-mono text-xxs">{v?.content_sha256?.slice(0, 16)}…</code></>}
        actions={<>
          {ds.is_synthetic && <Badge tone="hypo">synthetic</Badge>}
          <select className="input w-28" value={version ?? ""} onChange={(e) => { setVersion(e.target.value ? Number(e.target.value) : undefined); setOffset(0); }}>
            <option value="">latest</option>
            {ds.versions.map((x: any) => <option key={x.version} value={x.version}>v{x.version}</option>)}
          </select>
          {canManage && (
            <select className="input w-32" value={ds.access_policy} onChange={(e) => patch({ access_policy: e.target.value })} aria-label="Access policy">
              <option value="project">project</option><option value="restricted">restricted</option>
            </select>
          )}
          {canWrite && (
            <select className="input w-36" value={ds.retention_policy} onChange={(e) => patch({ retention_policy: e.target.value })} aria-label="Retention">
              {["indefinite", "1y", "3y", "7y", "until_case_closed"].map((r) => <option key={r}>{r}</option>)}
            </select>
          )}
          {canWrite && <button className="btn" onClick={() => nav(`/ingestion?dataset=${ds.id}`)}>New version</button>}
          {canDelete && <button className="btn btn-danger" onClick={del}>Delete</button>}
        </>} />
      <ErrorBox error={err} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "records", label: "Records" }, { id: "schema", label: "Schema" },
        { id: "quality", label: "Quality" }, { id: "lineage", label: "Lineage" }, { id: "versions", label: `Versions (${ds.versions.length})` },
        { id: "report", label: "Ingestion report" }]} />
      {tab === "records" && (
        <Card title={<span className="flex items-center gap-2">Records
          <span className="flex rounded border border-line">{(["normalized", "raw"] as const).map((x) =>
            <button key={x} className={`px-2 py-0.5 text-xxs ${view === x ? "bg-accent/20" : ""}`} onClick={() => setView(x)}>{x === "raw" ? "original source values" : "normalized"}</button>)}</span>
          {recs.data?.redacted_fields?.length > 0 && <Badge tone="warn">redacted: {recs.data.redacted_fields.join(", ")}</Badge>}</span>}
          actions={<>
            <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>‹</button>
            <span className="text-xxs text-muted">{offset + 1}–{Math.min(offset + 50, recs.data?.total ?? 0)} of {fmtNum(recs.data?.total)}</span>
            <button className="btn" disabled={offset + 50 >= (recs.data?.total ?? 0)} onClick={() => setOffset(offset + 50)}>›</button>
          </>} bodyClass="">
          {recs.isLoading ? <Spinner /> : (
            <Table maxHeight={560} columns={["#", ...cols]} rows={(recs.data?.records ?? []).map((r: any) => [
              <span className="text-muted">{r.row_index + 1}</span>,
              ...cols.map((c) => { const val = (view === "normalized" ? r.normalized : r.raw)[c];
                return val === null || val === undefined || val === "" ? <span className="text-muted/60">∅</span> :
                  val === "[restricted]" ? <Badge tone="warn">restricted</Badge> : String(val); })])} />
          )}
        </Card>
      )}
      {tab === "schema" && (
        <Card bodyClass="">
          <Table columns={["Field", "Type", "Source column", "Sensitive", "Required", "Completeness"]} rows={fields.map((f) => [
            <code className="font-mono">{f.name}</code>, f.type, f.source, f.sensitive ? <Badge tone="warn">sensitive</Badge> : "",
            f.required ? "yes" : "", ds.latest?.quality?.completeness?.[f.name] != null ? `${(ds.latest.quality.completeness[f.name] * 100).toFixed(1)}%` : "—"])} />
        </Card>
      )}
      {tab === "quality" && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">{Object.entries(quality.data?.summary?.issue_counts ?? {}).map(([k, n]) => <Badge key={k} tone="warn">{k}: {String(n)}</Badge>)}
            {Object.keys(quality.data?.summary?.issue_counts ?? {}).length === 0 && <Badge tone="ok">no issues detected</Badge>}</div>
          <Card bodyClass="">
            <Table maxHeight={560} columns={["Row", "Field", "Check", "Severity", "Message", "Value"]} rows={(quality.data?.issues ?? []).map((i: any) => [
              i.row_index != null ? i.row_index + 1 : "—", i.field ?? "—", i.check, <Badge tone={i.severity === "error" ? "danger" : "warn"}>{i.severity}</Badge>, i.message, i.value ?? ""])} />
          </Card>
        </div>
      )}
      {tab === "lineage" && ds.lineage && (
        <Card title="Lineage">
          <ol className="space-y-2 text-xs">
            <li>① <b>Source</b>: {ds.lineage.source_file ? <>{ds.lineage.source_file.name} <code className="font-mono text-xxs text-muted">sha256 {ds.lineage.source_file.sha256}</code></> : `derived (${ds.lineage.origin})`}</li>
            {ds.lineage.parent_version_id && <li>Parent version: <code className="font-mono">{ds.lineage.parent_version_id}</code></li>}
            <li>② <b>Transformations</b> ({ds.lineage.pipeline_version}): <Json value={ds.lineage.transformations} max={220} /></li>
            <li>③ <b>Derived</b>: {ds.lineage.derived.entities} entities, {ds.lineage.derived.relationships} relationships</li>
          </ol>
        </Card>
      )}
      {tab === "versions" && (
        <Card bodyClass="">
          <Table columns={["Version", "Records", "Origin", "Imported", "Content SHA-256", "Issues"]} rows={ds.versions.map((x: any) => [
            `v${x.version}`, fmtNum(x.record_count), x.origin, fmtTime(x.imported_at), <code className="font-mono text-xxs">{x.content_sha256.slice(0, 24)}</code>,
            Object.entries(x.quality?.issue_counts ?? {}).map(([k, n]) => `${k}:${n}`).join(" ")])} />
        </Card>
      )}
      {tab === "report" && <Card><Json value={ds.ingestion_report} max={600} /></Card>}
    </div>
  );
}
