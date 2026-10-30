import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../services/api";
import { useAtlas } from "../../app/store";
import { ErrorBox, Field, Spinner } from "../../components/ui";
import { Logo } from "../../components/Logo";

export function Login() {
  const setSession = useAtlas((s) => s.setSession);
  const status = useQuery({ queryKey: ["setup-status"], queryFn: () => api("/api/auth/setup-status") });
  const [form, setForm] = useState({ username: "", password: "", totp: "", display_name: "", setup_token: "", confirm: "" });
  const [mfa, setMfa] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  const setup = status.data?.needs_setup;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (setup) {
        if (form.password !== form.confirm) throw new Error("Passwords do not match");
        const r = await api("/api/auth/setup", { body: { setup_token: form.setup_token, username: form.username,
          display_name: form.display_name || form.username, password: form.password } });
        setSession(r.token, r.user);
      } else {
        const r = await api("/api/auth/login", { body: { username: form.username, password: form.password, totp: form.totp || undefined } });
        if (r.mfa_required) setMfa(true);
        else setSession(r.token, r.user);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-bg p-4"
      style={{ backgroundImage: "radial-gradient(circle at 20% 20%, rgb(var(--accent) / .08), transparent 40%), radial-gradient(circle at 80% 80%, rgb(var(--hypo) / .06), transparent 40%)" }}>
      <div className="card w-full max-w-sm p-6">
        <div className="mb-5 flex flex-col items-center gap-2">
          <Logo />
          <p className="text-xs text-muted">Offline Intelligence and Data Operations Platform</p>
        </div>
        {status.isLoading ? <Spinner /> : (
          <form onSubmit={submit} className="space-y-3">
            {setup && (
              <div className="rounded-md border border-accent/40 bg-accent/10 p-2 text-xs">
                <b>Initial setup.</b> Create the first system administrator. Enter the one-time setup token written to
                <code className="mx-1 break-all font-mono text-xxs">{status.data.setup_token_location}</code>on the Atlas host.
              </div>
            )}
            {setup && <Field label="Setup token"><input className="input font-mono" value={form.setup_token} onChange={set("setup_token")} required autoFocus /></Field>}
            <Field label="Username"><input className="input" autoComplete="username" value={form.username} onChange={set("username")} required autoFocus={!setup} /></Field>
            {setup && <Field label="Display name"><input className="input" value={form.display_name} onChange={set("display_name")} /></Field>}
            <Field label="Password" hint={setup ? "At least 12 characters mixing three of: lowercase, uppercase, digits, symbols." : undefined}>
              <input className="input" type="password" autoComplete={setup ? "new-password" : "current-password"} value={form.password} onChange={set("password")} required />
            </Field>
            {setup && <Field label="Confirm password"><input className="input" type="password" value={form.confirm} onChange={set("confirm")} required /></Field>}
            {mfa && <Field label="Authenticator code"><input className="input font-mono" inputMode="numeric" value={form.totp} onChange={set("totp")} autoFocus required /></Field>}
            <ErrorBox error={error} />
            <button className="btn btn-primary w-full justify-center py-1.5" disabled={busy}>
              {setup ? "Create administrator" : mfa ? "Verify" : "Sign in"}
            </button>
          </form>
        )}
        <p className="mt-4 text-center text-[10px] text-muted">Data stays on this machine. No cloud services are contacted.</p>
      </div>
    </div>
  );
}
