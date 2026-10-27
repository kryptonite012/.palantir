import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../services/api";
import { useAtlas } from "../../app/store";
import { useGlobalCan } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, PageHeader, Table } from "../../components/ui";
import type { Project } from "../../types/api";

export function ProjectsPage() {
  const projects = useQuery<Project[]>({ queryKey: ["projects"], queryFn: () => api("/api/projects") });
  const { setProject, recentProjects } = useAtlas();
  const canCreate = useGlobalCan("project.create");
  const qc = useQueryClient();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", description: "", classification: "internal" });
  const [err, setErr] = useState<unknown>(null);
  const create = async () => {
    setErr(null);
    try {
      const p = await api("/api/projects", { body: form });
      await qc.invalidateQueries({ queryKey: ["projects"] });
      setProject(p.id);
      nav("/");
    } catch (e) {
      setErr(e);
    }
  };
  const recent = recentProjects.map((id) => projects.data?.find((p) => p.id === id)).filter(Boolean) as Project[];
  return (
    <div className="space-y-4">
      <PageHeader title="Projects & workspaces" subtitle="Each project isolates its data, members, ontology and audit scope." />
      {recent.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="label self-center">Recent</span>
          {recent.map((p) => <button key={p.id} className="btn" onClick={() => { setProject(p.id); nav("/"); }}>{p.name}</button>)}
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Your projects" className="lg:col-span-2" bodyClass="">
          <Table columns={["Name", "Role", "Classification", ""]} rows={(projects.data ?? []).map((p) => [
            p.name, p.role_label, <Badge>{p.classification}</Badge>,
            <button className="btn" onClick={() => { setProject(p.id); qc.invalidateQueries(); nav("/"); }}>Open</button>])} empty="You are not a member of any project." />
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
              <ErrorBox error={err} />
              <button className="btn btn-primary" disabled={!form.name} onClick={create}>Create project</button>
              <p className="text-xxs text-muted">The default ontology (people, organizations, locations, events, documents, accounts, assets, transactions, devices, projects) is created automatically.</p>
            </div>
          ) : <p className="text-xs text-muted">Only system administrators can create projects. Ask an administrator to add you to a project.</p>}
        </Card>
      </div>
    </div>
  );
}
