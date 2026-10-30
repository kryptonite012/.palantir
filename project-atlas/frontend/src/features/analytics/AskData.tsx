import { useState } from "react";
import { api, pp } from "../../services/api";
import { useProjectId } from "../../app/hooks";
import { Badge, Card, ErrorBox, Notice, Spinner, Table } from "../../components/ui";

/** Natural-language exploration: the local model drafts SQL, the analyst reviews it, then runs it explicitly. */
export function AskData() {
  const pid = useProjectId();
  const [q, setQ] = useState("");
  const [draft, setDraft] = useState<any>(null);
  const [sql, setSql] = useState("");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const call = async (label: string, fn: () => Promise<void>) => { setErr(null); setBusy(label); try { await fn(); } catch (e) { setErr(e); } finally { setBusy(null); } };
  return (
    <div className="space-y-3">
      <Card title="Ask your data (local AI)">
        <div className="flex gap-2">
          <input className="input text-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Which organizations received the most money in April?"
            onKeyDown={(e) => e.key === "Enter" && q.length > 2 && call("Drafting SQL…", async () => { setRes(null); const d = await api(pp(pid, "/ai/ask-data"), { body: { question: q } }); setDraft(d); setSql(d.sql); })} />
          <button className="btn btn-primary" disabled={q.length < 3 || !!busy}
            onClick={() => call("Drafting SQL…", async () => { setRes(null); const d = await api(pp(pid, "/ai/ask-data"), { body: { question: q } }); setDraft(d); setSql(d.sql); })}>Draft query</button>
        </div>
        <p className="mt-1 text-[10px] text-muted">Two steps by design: nothing runs until you review the SQL. Queries are read-only, row- and time-limited, and never see fields your role cannot read.</p>
      </Card>
      {busy && <Spinner label={busy} />}
      <ErrorBox error={err} />
      {draft && (
        <Card title={<span className="flex items-center gap-2">Proposed SQL <Badge tone="hypo">{draft.label}</Badge> {draft.valid ? <Badge tone="ok">passes validation</Badge> : <Badge tone="danger">rejected</Badge>}</span>}
          actions={<button className="btn btn-primary" disabled={!!busy} onClick={() => call("Running…", async () => setRes(await api(pp(pid, "/ai/ask-data"), { body: { question: q, sql, execute: true } })))}>Run reviewed SQL</button>}>
          <textarea className="input h-28 font-mono" value={sql} onChange={(e) => setSql(e.target.value)} spellCheck={false} aria-label="SQL to run" />
          {!draft.valid && <Notice tone="warn">{draft.validation_error}</Notice>}
        </Card>
      )}
      {res && (
        <Card title={<>{res.row_count} rows {res.truncated && <Badge tone="warn">truncated</Badge>} <span className="font-normal text-muted">{res.elapsed_ms} ms</span></>} bodyClass="">
          {res.narrative && <div className="border-b border-line p-3 text-xs"><Badge tone="hypo">model description of the result</Badge> <p className="mt-1">{res.narrative}</p></div>}
          <Table maxHeight={420} columns={res.columns} rows={res.rows.map((r: any[]) => r.map((v) => (v === null ? "∅" : String(v))))} />
          <p className="px-3 py-2 text-[10px] text-muted">{res.note}</p>
        </Card>
      )}
    </div>
  );
}
