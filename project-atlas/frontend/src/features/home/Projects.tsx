import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, waitForJob } from "../../services/api";
import { useAtlas } from "../../app/store";
import { useGlobalCan } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, Notice, PageHeader, Table } from "../../components/ui";
import { askText, toast } from "../../components/feedback";
import type { Project } from "../../types/api";

export function ProjectsPage() {
  const projects = useQuery<Project[]>({ queryKey: ["projects"], queryFn: () => api("/api/projects") });
  const { setProject, recentProjects } = useAtlas();
  const canCreate = useGlobalCan("project.create");
  const canDelete = useGlobalCan("admin.projects");
  const qc = useQueryClient();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [form, setForm] = useState({ name: "", description: "", classification: "internal" });
  const [err, setErr] = useState<unknown>(null);
  const [demo, setDemo] = useState<{ progress: number; message: string } | null>(null);

  const open = (id: string) => { setProject(id); qc.invalidateQueries(); nav("/"); };
  const create = async () => {
    setErr(null);
    try {
      const p = await api("/api/projects", { body: form });
      await qc.invalidateQueries({ queryKey: ["projects"] });
      toast.ok(`Project “${p.name}” created`);
      open(p.id);
    } catch (e) { setErr(e); }
  };
  const createDemo = async () => {
    setErr(null);
    setDemo({ progress: 0, message: "Creating project" });
    try {
      const r = await api("/api/projects/demo", { body: {} });
      const done = await waitForJob(r.job.id, (j) => setDemo({ progress: j.progress, message: j.message }));
      if (done.status !== "succeeded") throw new Error(done.error ?? "Demo load failed");
      await qc.invalidateQueries({ queryKey: ["projects"] });
      toast.ok("Demo workspace ready — all data is synthetic");
      open(r.project.id);
    } catch (e) { setErr(e); setDemo(null); }
  };
  const archive = async (p: Project) => {
    try {
      await api(`/api/projects/${p.id}/archive`, { method: "PATCH", body: { archived: !p.archived } });
      projects.refetch();
      toast.ok(p.archived ? `Restored ${p.name}` : `Archived ${p.name}`);
    } catch (e) { setErr(e); }
  };
  const remove = async (p: Project) => {
    const name = await askText({ title: `Delete project “${p.name}”?`, danger: true, confirmText: "Delete permanently", mustEqual: p.name,
      body: "Every dataset, record, entity, document, investigation, workflow and report in the project is deleted. Audit events are kept. Make a backup first if unsure." });
    if (name === null) return;
    try {
      await api(`/api/projects/${p.id}`, { method: "DELETE", params: { confirm_name: name } });
      if (useAtlas.getState().projectId === p.id) setProject(null);
      projects.refetch();
      toast.ok(`Deleted ${p.name}`);
    } catch (e) { setErr(e); }
  };
  const recent = recentProjects.map((id) => projects.data?.find((p) => p.id === id)).filter(Boolean) as Project[];
  const hasDemo = projects.data?.some((p) => p.name.startsWith("Northwind Harbor (synthetic demo)"));
  return (
    <div className="space-y-4">
      <PageHeader title="Projects & workspaces" subtitle="Each project isolates its data, members, ontology and audit scope." />
      <ErrorBox error={err} />
      {recent.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="label self-center">Recent</span>
          {recent.map((p) => <button key={p.id} className="btn" onClick={() => open(p.id)}>{p.name}</button>)}
        </div>
      )}
      {canCreate && !hasDemo && (
        <Card className={params.get("demo") ? "border-accent" : ""} title="Explore with synthetic data">
          <div className="flex flex-wrap items-center gap-4">
            <p className="max-w-2xl flex-1 text-xs text-muted">
              Creates <b className="text-ink">Northwind Harbor (synthetic demo)</b>: 106 fictional records across four datasets, five documents
              (including one with a prompt-injection attempt), district polygons and pre-computed match candidates — loaded through the
              same validated, audited pipelines as real data. Nothing in it describes real people or organizations.
            </p>
            {demo ? (
              <div className="w-72 text-xs">
                <div className="h-2 overflow-hidden rounded bg-raised"><div className="h-full bg-accent transition-all" style={{ width: `${Math.round(demo.progress * 100)}%` }} /></div>
                <p className="mt-1 text-muted">{demo.message || "Working…"}</p>
              </div>
            ) : <button className="btn btn-primary" onClick={createDemo}>Create demo workspace</button>}
          </div>
        </Card>
      )}
      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Your projects" className="lg:col-span-2" bodyClass="">
          <Table columns={["Name", "Role", "Classification", "Status", ""]} rows={(projects.data ?? []).map((p) => [
            <span><b>{p.name}</b>{p.description && <span className="block max-w-md truncate text-xxs text-muted">{p.description}</span>}</span>,
            p.role_label, <Badge>{p.classification}</Badge>, p.archived ? <Badge tone="warn">archived</Badge> : <Badge tone="ok">active</Badge>,
            <span className="flex justify-end gap-1">
              <button className="btn btn-primary" onClick={() => open(p.id)}>Open</button>
              {p.role === "project_admin" && <button className="btn" onClick={() => archive(p)}>{p.archived ? "Unarchive" : "Archive"}</button>}
              {canDelete && p.role === "project_admin" && <button className="btn btn-danger" onClick={() => remove(p)}>Delete</button>}
            </span>])} empty="You are not a member of any project." />
        </Card>
        <Card title="New project">
          {canCreate ? (
            <div className="space-y-2">
              <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Description"><input className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
              <Field label="Classification">
                <select className="input" value={form.classification} onChange={(e) => setForm({ ...form, classification: e.target.value })}>
                  {["public", "internal", "confidential", "restricted"].map((c) => <option key={c}>{c}</option>)}
                </select>
              </Field>
              <button className="btn btn-primary" disabled={!form.name} onClick={create}>Create project</button>
              <p className="text-xxs text-muted">The default ontology (people, organizations, locations, events, documents, accounts, assets, transactions, devices, projects) is created automatically.</p>
            </div>
          ) : <Notice>Only system administrators can create projects. Ask an administrator to add you to a project.</Notice>}
        </Card>
      </div>
    </div>
  );
}
