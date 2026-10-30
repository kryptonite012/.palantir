import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../services/api";
import { useAtlas } from "../../app/store";
import { Badge, Card, ErrorBox, Field, Notice, PageHeader, Table, fmtTime } from "../../components/ui";
import { NAV } from "../../app/Layout";

export function SettingsPage() {
  const { theme, setTheme, user, setUser } = useAtlas();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api("/api/auth/sessions") });
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [mfa, setMfa] = useState<any>(null);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const call = async (fn: () => Promise<void>) => { setErr(null); setMsg(null); try { await fn(); } catch (e) { setErr(e); } };
  return (
    <div className="space-y-3">
      <PageHeader title="Settings" subtitle={`Signed in as ${user?.display_name} (${user?.username})`} />
      <ErrorBox error={err} />
      {msg && <Notice tone="ok">{msg}</Notice>}
      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Appearance">
          <div className="flex gap-2">{(["dark", "light"] as const).map((t) => <button key={t} className={`btn ${theme === t ? "btn-primary" : ""}`} onClick={() => setTheme(t)}>{t}</button>)}</div>
          <p className="mt-2 text-xxs text-muted">Preferences (theme, panel sizes, tabs, recent projects) are stored only in this browser.</p>
        </Card>
        <Card title="Change password">
          <div className="space-y-2">
            <Field label="Current password"><input className="input" type="password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
            <Field label="New password"><input className="input" type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <Field label="Confirm"><input className="input" type="password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
            <button className="btn btn-primary" disabled={!pw.new_password || pw.new_password !== pw.confirm} onClick={() => call(async () => {
              await api("/api/auth/password", { body: { current_password: pw.current_password, new_password: pw.new_password } });
              setPw({ current_password: "", new_password: "", confirm: "" }); setMsg("Password changed; other sessions were signed out."); sessions.refetch(); })}>Update</button>
          </div>
        </Card>
        <Card title={<>Multi-factor authentication {user?.mfa_enabled ? <Badge tone="ok">enabled</Badge> : <Badge>off</Badge>}</>}>
          {!user?.mfa_enabled && !mfa && <button className="btn" onClick={() => call(async () => setMfa(await api("/api/auth/mfa/enroll", { method: "POST" })))}>Set up authenticator (TOTP)</button>}
          {mfa && !user?.mfa_enabled && <div className="space-y-2 text-xs">
            <p>Add this secret to an offline authenticator app, then enter the current 6-digit code.</p>
            <code className="block select-all break-all rounded bg-bg p-2 font-mono">{mfa.secret}</code>
            <code className="block select-all break-all font-mono text-xxs text-muted">{mfa.provisioning_uri}</code>
            <input className="input font-mono" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
            <button className="btn btn-primary" onClick={() => call(async () => { await api("/api/auth/mfa/activate", { body: { code } }); setUser({ ...user!, mfa_enabled: true }); setMfa(null); setMsg("MFA enabled."); })}>Activate</button>
          </div>}
          {user?.mfa_enabled && <div className="flex gap-2"><input className="input font-mono" placeholder="current code" value={code} onChange={(e) => setCode(e.target.value)} />
            <button className="btn btn-danger" onClick={() => call(async () => { await api("/api/auth/mfa/disable", { body: { code } }); setUser({ ...user!, mfa_enabled: false }); setMsg("MFA disabled."); })}>Disable</button></div>}
        </Card>
        <Card title="Active sessions" className="xl:col-span-2" bodyClass="">
          <Table columns={["Started", "Expires", "Client", ""]} rows={(sessions.data ?? []).map((s: any) => [fmtTime(s.created_at), fmtTime(s.expires_at), <span className="text-muted">{s.client?.slice(0, 60)}</span>,
            s.current ? <Badge tone="accent">this session</Badge> : <button className="btn" onClick={() => call(async () => { await api(`/api/auth/sessions/${s.id}`, { method: "DELETE" }); sessions.refetch(); })}>Revoke</button>])} />
        </Card>
        <Card title="Keyboard shortcuts">
          <ul className="space-y-0.5 text-xs"><li><span className="kbd">/</span> focus global search</li><li><span className="kbd">?</span> show shortcuts</li>
            {NAV.slice(0, 8).map((n) => <li key={n.to}><span className="kbd">g</span> <span className="kbd">{n.key}</span> {n.label}</li>)}</ul>
        </Card>
      </div>
    </div>
  );
}
