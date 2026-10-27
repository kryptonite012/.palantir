import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, pp } from "../../services/api";
import { useCan, useGlobalCan, usePQuery, useProjectId } from "../../app/hooks";
import { Badge, Card, ErrorBox, Field, Json, Notice, PageHeader, Table, Tabs, fmtBytes, fmtTime } from "../../components/ui";

export function AdminPage() {
  const [tab, setTab] = useState<"system" | "users" | "members" | "ontology" | "backups" | "models">("system");
  return (
    <div className="space-y-3">
      <PageHeader title="Administration" subtitle="Users, project membership, ontology, backups, local AI models and offline verification." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "system", label: "System & offline" }, { id: "users", label: "Users" }, { id: "members", label: "Project members" },
        { id: "ontology", label: "Ontology" }, { id: "backups", label: "Backup & restore" }, { id: "models", label: "AI models" }]} />
      {tab === "system" && <System />}
      {tab === "users" && <Users />}
      {tab === "members" && <Members />}
      {tab === "ontology" && <Ontology />}
      {tab === "backups" && <Backups />}
      {tab === "models" && <Models />}
    </div>
  );
}

function System() {
  const status = useQuery({ queryKey: ["sys-status"], queryFn: () => api("/api/system/status") });
  const off = useQuery({ queryKey: ["offline-check"], queryFn: () => api("/api/system/offline-check"), enabled: false });
  const s = status.data;
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Card title="System status">
        {s && <div className="grid grid-cols-2 gap-1 text-xs">
          <span className="text-muted">Version</span><span>{s.app} {s.version} ({s.env})</span>
          <span className="text-muted">Database</span><span>{s.database} · revision {s.schema_revision}</span>
          <span className="text-muted">Offline mode</span><span>{String(s.offline_mode)}</span>
          <span className="text-muted">Storage</span><span className="break-all font-mono text-xxs">{s.storage_dir}</span>
          <span className="text-muted">Backups</span><span className="break-all font-mono text-xxs">{s.backup_dir}</span>
          <span className="text-muted">Disk</span><span>{fmtBytes(s.disk.free)} free of {fmtBytes(s.disk.total)}</span>
          <span className="text-muted">Python / platform</span><span>{s.python} · {s.platform}</span>
          <span className="text-muted">Jobs</span><span>{JSON.stringify(s.jobs)}</span>
        </div>}
      </Card>
      <Card title="Offline verification" actions={<button className="btn btn-primary" onClick={() => off.refetch()}>Run checks</button>}>
        {off.data ? <div className="space-y-1 text-xs">
          <Notice tone={off.data.all_required_ok ? "ok" : "warn"}>{off.data.all_required_ok ? "All required checks passed." : "Some checks failed — review below."}</Notice>
          {off.data.checks.map((c: any) => <div key={c.check} className="flex items-start gap-2"><Badge tone={c.ok ? "ok" : c.check === "ocr_engine_available" ? "neutral" : "danger"}>{c.ok ? "pass" : "fail"}</Badge>
            <div><b>{c.check}</b><div className="text-muted">{typeof c.detail === "string" ? c.detail : JSON.stringify(c.detail)}</div></div></div>)}
          <ul className="mt-2 list-disc pl-4 text-muted">{off.data.limitations.map((l: string) => <li key={l}>{l}</li>)}</ul>
        </div> : <p className="text-xs text-muted">Checks configuration, telemetry, bind address, AI endpoint, the outbound network guard (with a live probe), dependencies and blocked connection attempts.</p>}
      </Card>
    </div>
  );
}

function Users() {
  const canAdmin = useGlobalCan("admin.users");
  const canSec = useGlobalCan("admin.users.security");
  const users = useQuery({ queryKey: ["users"], queryFn: () => api("/api/admin/users"), enabled: canAdmin || canSec });
  const [form, setForm] = useState({ username: "", display_name: "", password: "", global_role: "" });
  const [token, setToken] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  if (!canAdmin && !canSec) return <Notice tone="warn">Requires a system or security administrator.</Notice>;
  const call = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); users.refetch(); } catch (e) { setErr(e); } };
  return (
    <div className="grid gap-3 xl:grid-cols-[1fr_320px]">
      <Card bodyClass="">
        <ErrorBox error={err} />
        {token && <Notice tone="warn">One-time reset token (shown once, valid 60 minutes): <code className="select-all font-mono">{token}</code></Notice>}
        <Table columns={["User", "Global role", "Projects", "MFA", "Status", ""]} rows={(users.data ?? []).map((u: any) => [
          <span><b>{u.username}</b> <span className="text-muted">{u.display_name}</span></span>,
          canAdmin ? <select className="input w-40" value={u.global_role ?? "none"} onChange={(e) => call(() => api(`/api/admin/users/${u.id}`, { method: "PATCH", body: { global_role: e.target.value } }))}>
            <option value="none">—</option><option value="system_admin">System Administrator</option><option value="security_admin">Security Administrator</option></select> : u.global_role_label,
          u.projects, u.mfa_enabled ? <Badge tone="ok">on</Badge> : <Badge>off</Badge>,
          <span>{u.is_active ? <Badge tone="ok">active</Badge> : <Badge tone="danger">disabled</Badge>} {u.locked && <Badge tone="warn">locked</Badge>}</span>,
          <span className="flex gap-1">
            <button className="btn" onClick={() => call(() => api(`/api/admin/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }))}>{u.is_active ? "Disable" : "Enable"}</button>
            <button className="btn" onClick={() => call(async () => setToken((await api(`/api/admin/users/${u.id}/reset-token`, { method: "POST" })).token))}>Reset token</button>
            <button className="btn" onClick={() => call(() => api(`/api/admin/users/${u.id}/revoke-sessions`, { method: "POST" }))}>Revoke sessions</button>
            {u.mfa_enabled && <button className="btn" onClick={() => confirm(`Reset MFA for ${u.username}? They must re-enrol.`) && call(() => api(`/api/admin/users/${u.id}`, { method: "PATCH", body: { reset_mfa: true } }))}>Reset MFA</button>}
          </span>])} />
      </Card>
      {canAdmin && <Card title="Create user">
        <div className="space-y-2">
          <Field label="Username"><input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
          <Field label="Display name"><input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></Field>
          <Field label="Initial password" hint="≥12 chars, three character classes"><input className="input" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label="Global role"><select className="input" value={form.global_role} onChange={(e) => setForm({ ...form, global_role: e.target.value })}>
            <option value="">none (project roles only)</option><option value="system_admin">System Administrator</option><option value="security_admin">Security Administrator</option></select></Field>
          <button className="btn btn-primary" onClick={() => call(async () => { await api("/api/admin/users", { body: { ...form, global_role: form.global_role || null, display_name: form.display_name || form.username } }); setForm({ username: "", display_name: "", password: "", global_role: "" }); })}>Create</button>
        </div>
      </Card>}
    </div>
  );
}

function Members() {
  const pid = useProjectId();
  const members = usePQuery<any[]>(["members"], "/members");
  const dir = useQuery({ queryKey: ["directory"], queryFn: () => api("/api/admin/users/directory") });
  const canManage = useCan("members.manage");
  const [add, setAdd] = useState({ user_id: "", role: "analyst" });
  const [err, setErr] = useState<unknown>(null);
  const roles = ["project_admin", "data_engineer", "analyst", "reviewer", "read_only"];
  const call = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); members.refetch(); } catch (e) { setErr(e); } };
  return (
    <Card bodyClass="">
      <ErrorBox error={err} />
      <Table columns={["User", "Role", ""]} rows={(members.data ?? []).map((m) => [`${m.display_name} (${m.username})`,
        canManage ? <select className="input w-44" value={m.role} onChange={(e) => call(() => api(pp(pid, "/members"), { method: "PUT", body: { user_id: m.user_id, role: e.target.value } }))}>
          {roles.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}</select> : m.role_label,
        canManage && <button className="btn btn-danger" onClick={() => call(() => api(pp(pid, `/members/${m.user_id}`), { method: "DELETE" }))}>Remove</button>])} />
      {canManage && <div className="flex gap-2 p-3">
        <select className="input" value={add.user_id} onChange={(e) => setAdd({ ...add, user_id: e.target.value })}><option value="">Add user…</option>
          {(dir.data ?? []).filter((u: any) => !members.data?.some((m) => m.user_id === u.id)).map((u: any) => <option key={u.id} value={u.id}>{u.display_name} ({u.username})</option>)}</select>
        <select className="input w-44" value={add.role} onChange={(e) => setAdd({ ...add, role: e.target.value })}>{roles.map((r) => <option key={r}>{r}</option>)}</select>
        <button className="btn btn-primary" disabled={!add.user_id} onClick={() => call(() => api(pp(pid, "/members"), { method: "PUT", body: add }))}>Add</button>
      </div>}
    </Card>
  );
}

function Ontology() {
  const pid = useProjectId();
  const onto = usePQuery<any>(["ontology"], "/ontology");
  const canWrite = useCan("ontology.write");
  const [edit, setEdit] = useState<string>("");
  const [err, setErr] = useState<unknown>(null);
  const [rel, setRel] = useState({ name: "", label: "", directed: true });
  const save = async () => {
    setErr(null);
    try { await api(pp(pid, "/ontology/entity-types"), { method: "PUT", body: JSON.parse(edit) }); onto.refetch(); setEdit(""); } catch (e) { setErr(e); }
  };
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Card title="Entity types" bodyClass="">
        <Table columns={["Type", "Fields", "Version", ""]} rows={(onto.data?.entity_types ?? []).map((t: any) => [<b>{t.label}</b>,
          <span className="flex flex-wrap gap-1">{t.fields.map((f: any) => <Badge key={f.name} tone={f.sensitive ? "warn" : f.identifier ? "accent" : "neutral"}>{f.name}:{f.type}</Badge>)}</span>,
          `v${t.schema_version}`, canWrite && <button className="btn" onClick={() => setEdit(JSON.stringify({ name: t.name, label: t.label, fields: t.fields }, null, 2))}>Edit</button>])} />
        {canWrite && <div className="p-3"><button className="btn" onClick={() => setEdit(JSON.stringify({ name: "vessel", label: "Vessel", fields: [{ name: "name", type: "string", required: true }, { name: "imo_number", type: "identifier", identifier: true }] }, null, 2))}>New entity type</button></div>}
      </Card>
      <div className="space-y-3">
        {edit && <Card title="Edit entity type (JSON)" actions={<button className="btn btn-primary" onClick={save}>Save (new schema version)</button>}>
          <textarea className="input h-64 font-mono" value={edit} onChange={(e) => setEdit(e.target.value)} />
          <p className="mt-1 text-xxs text-muted">Field types: {onto.data?.field_types?.join(", ")}. Flags: identifier, sensitive, required, pattern.</p>
          <ErrorBox error={err} />
        </Card>}
        <Card title="Relationship types" bodyClass="">
          <Table columns={["Name", "Label", "Directed", "Source types", "Target types"]} rows={(onto.data?.relationship_types ?? []).map((r: any) => [r.name, r.label, r.directed ? "yes" : "no", r.source_types.join(", ") || "any", r.target_types.join(", ") || "any"])} />
          {canWrite && <div className="flex gap-2 p-3"><input className="input" placeholder="name" value={rel.name} onChange={(e) => setRel({ ...rel, name: e.target.value })} />
            <input className="input" placeholder="label" value={rel.label} onChange={(e) => setRel({ ...rel, label: e.target.value })} />
            <button className="btn" onClick={() => api(pp(pid, "/ontology/relationship-types"), { method: "PUT", body: rel }).then(() => onto.refetch()).catch(setErr)}>Add</button></div>}
        </Card>
      </div>
    </div>
  );
}

function Backups() {
  const can = useGlobalCan("admin.backup");
  const list = useQuery({ queryKey: ["backups"], queryFn: () => api("/api/admin/backups"), enabled: can });
  const [pass, setPass] = useState("");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (!can) return <Notice tone="warn">Requires a system administrator.</Notice>;
  const call = async (fn: () => Promise<any>) => { setErr(null); setBusy(true); try { setRes(await fn()); list.refetch(); } catch (e) { setErr(e); } finally { setBusy(false); } };
  const action = (path: string, filename: string, confirm = false) => {
    const passphrase = filename.endsWith(".enc") ? prompt("Backup passphrase:") ?? undefined : undefined;
    return call(() => api(`/api/admin/backups/${path}`, { body: { filename, passphrase, confirm } }));
  };
  return (
    <div className="grid gap-3 xl:grid-cols-[1fr_380px]">
      <Card bodyClass="">
        <Table columns={["Archive", "Kind", "Size", "Encrypted", "Records", "Verified", ""]} rows={(list.data ?? []).map((b: any) => [
          <code className="font-mono text-xxs">{b.filename}</code>, b.kind, fmtBytes(b.size_bytes), b.encrypted ? <Badge tone="ok">AES-256-GCM</Badge> : <Badge tone="warn">no</Badge>,
          b.counts?.records ?? "?", b.verified_at ? fmtTime(b.verified_at) : "—",
          <span className="flex gap-1"><button className="btn" onClick={() => action("verify", b.filename)}>Verify</button>
            <button className="btn" onClick={() => action("restore", b.filename)}>Restore preview</button>
            <button className="btn btn-danger" onClick={() => { if (confirm(`Restore ${b.filename}? The current database and files are moved aside first.`)) action("restore", b.filename, true); }}>Restore</button></span>])} empty="No backups yet" />
      </Card>
      <div className="space-y-3">
        <Card title="Create backup">
          <Field label="Passphrase (optional, ≥12 chars → encrypted archive)"><input className="input" type="password" value={pass} onChange={(e) => setPass(e.target.value)} /></Field>
          <button className="btn btn-primary mt-2" disabled={busy} onClick={() => call(() => api("/api/admin/backups", { body: { passphrase: pass || null } }))}>Back up now</button>
          <p className="mt-2 text-xxs text-muted">Consistent SQLite snapshot (online backup API) + uploaded files + columnar copies + exports + audit checkpoints. Scheduled backups: <code>ATLAS_BACKUP_INTERVAL_HOURS</code>.</p>
        </Card>
        <ErrorBox error={err} />
        {res && <Card title="Result"><Json value={res} max={360} /></Card>}
      </div>
    </div>
  );
}

function Models() {
  const can = useGlobalCan("admin.models");
  const st = useQuery({ queryKey: ["ai-status"], queryFn: () => api("/api/ai/status") });
  const [form, setForm] = useState({ name: "", version: "", kind: "chat", runtime: "ollama", runtime_model_name: "", file_path: "", sha256: "", quantization: "", license: "", ram_mb: "" });
  const [err, setErr] = useState<unknown>(null);
  const call = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); st.refetch(); } catch (e) { setErr(e); } };
  return (
    <div className="grid gap-3 xl:grid-cols-[1fr_340px]">
      <Card bodyClass="">
        <div className="p-3"><Notice>{st.data?.note} Status: AI {st.data?.enabled ? "enabled" : "disabled"}{st.data?.base_url ? ` at ${st.data.base_url}` : ""}.</Notice></div>
        <ErrorBox error={err} />
        <Table columns={["Model", "Kind", "Quantization", "License", "RAM", "Checksum", "Health", ""]} rows={(st.data?.models ?? []).map((m: any) => [
          <span><b>{m.name}</b> {m.version} <span className="text-muted">({m.runtime}:{m.runtime_model_name})</span></span>, m.kind, m.quantization ?? "—", m.license,
          m.ram_mb ? `${m.ram_mb} MB` : "—", m.sha256 ? <code className="font-mono text-xxs">{m.sha256.slice(0, 10)}</code> : "—",
          <span title={m.health_detail}><Badge tone={m.health === "healthy" ? "ok" : m.health === "unknown" ? "neutral" : "danger"}>{m.health}</Badge></span>,
          can && <span className="flex gap-1"><button className="btn" onClick={() => call(() => api(`/api/ai/models/${m.id}/check`, { method: "POST" }))}>Check</button>
            <button className="btn" onClick={() => call(() => api(`/api/ai/models/${m.id}`, { method: "PATCH", params: { enabled: !m.enabled } }))}>{m.enabled ? "Disable" : "Enable"}</button></span>])} empty="No models registered. AI is optional." />
      </Card>
      {can && <Card title="Register local model">
        <div className="space-y-1.5">
          {(["name", "version", "runtime_model_name", "file_path", "sha256", "quantization", "license", "ram_mb"] as const).map((k) =>
            <Field key={k} label={k.replaceAll("_", " ")}><input className="input" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></Field>)}
          <Field label="Kind"><select className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{["chat", "embedding", "reranker", "ocr"].map((k) => <option key={k}>{k}</option>)}</select></Field>
          <button className="btn btn-primary" onClick={() => call(() => api("/api/ai/models", { body: Object.fromEntries(Object.entries({ ...form, ram_mb: form.ram_mb ? Number(form.ram_mb) : undefined }).filter(([, v]) => v !== "")) }))}>Register</button>
        </div>
      </Card>}
    </div>
  );
}
