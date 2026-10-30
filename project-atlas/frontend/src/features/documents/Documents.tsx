import { useEffect, useState } from "react";
import { toast } from "../../components/feedback";
import { useSearchParams } from "react-router-dom";
import { api, download, pp, waitForJob } from "../../services/api";
import { useCan, usePQuery, useProjectId } from "../../app/hooks";
import { Badge, Card, Empty, ErrorBox, Notice, PageHeader, SplitPane, Spinner, Table, fmtTime } from "../../components/ui";
import type { Citation } from "../../types/api";

export function DocumentsPage() {
  const pid = useProjectId();
  const [params, setParams] = useSearchParams();
  const docId = params.get("doc");
  const page = Number(params.get("page") ?? 1);
  const docs = usePQuery<any[]>(["documents"], "/documents");
  const canWrite = useCan("document.write");
  const canAI = useCan("ai.use");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const upload = async (files: FileList) => {
    setErr(null);
    for (const f of Array.from(files)) {
      try {
        setBusy(`Processing ${f.name}…`);
        const fd = new FormData();
        fd.append("file", f);
        const up = await api(pp(pid, "/files"), { form: fd });
        const job = await api(pp(pid, "/documents"), { body: { file_id: up.id } });
        const done = await waitForJob(job.id);
        if (done.status !== "succeeded") throw new Error(done.error ?? "processing failed");
      } catch (e) { setErr(e); }
    }
    setBusy(null);
    docs.refetch();
  };

  return (
    <div className="flex h-full flex-col gap-2">
      <PageHeader title="Documents" subtitle="Local text extraction, language detection, keywords, entity candidates, duplicate detection and page-level evidence. Imported documents are treated as untrusted content."
        actions={canWrite && <label className="btn btn-primary cursor-pointer">Add documents<input type="file" multiple className="hidden" accept=".pdf,.docx,.txt,.md,.markdown,.eml" onChange={(e) => e.target.files && upload(e.target.files)} /></label>} />
      {busy && <Spinner label={busy} />}
      <ErrorBox error={err} />
      <div className="card min-h-0 flex-1 overflow-hidden">
        <SplitPane id="docs" initial={0.45} left={
          <div className="p-2">
            {!docs.data?.length ? <Empty title="No documents">Add PDF, DOCX, TXT, Markdown or EML files.</Empty> : (
              <Table columns={["Title", "Type", "Pages", "Lang", "Class", ""]} rows={docs.data.map((d) => [
                <button className={`text-left hover:underline ${d.id === docId ? "font-semibold text-accent" : "text-accent"}`} onClick={() => setParams({ doc: d.id })}>{d.title}</button>,
                d.media_type, d.page_count, d.language ?? "?", <Badge>{d.classification}</Badge>,
                <span className="flex gap-1">{d.duplicate_of_id && <Badge tone="warn">dup</Badge>}{d.ocr_status.startsWith("ocr_required") && <Badge tone="warn">needs OCR</Badge>}</span>])} />
            )}
            <Assistant canAI={canAI} onOpen={(d, p) => setParams({ doc: d, page: String(p) })} />
          </div>
        } right={docId ? <DocumentView id={docId} page={page} onPage={(p) => setParams({ doc: docId, page: String(p) })} canAI={canAI} /> : <p className="p-4 text-xs text-muted">Select a document.</p>} />
      </div>
    </div>
  );
}

function DocumentView({ id, page, onPage, canAI }: { id: string; page: number; onPage: (p: number) => void; canAI: boolean }) {
  const pid = useProjectId();
  const d = usePQuery<any>(["document", id], `/documents/${id}`);
  const pg = usePQuery<any>(["document-page", id, page], `/documents/${id}/pages/${page}`);
  const sim = usePQuery<any[]>(["document-sim", id], `/documents/${id}/similar`);
  const [summary, setSummary] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => setSummary(null), [id]);
  if (!d.data) return <Spinner />;
  const doc = d.data;
  return (
    <div className="space-y-3 p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{doc.title}</h2>
          <p className="text-muted">{doc.media_type} · {doc.page_count} {doc.page_label}(s) · language {doc.language ?? "undetermined"} {doc.language_confidence ? `(${doc.language_confidence})` : ""} · {doc.metadata.classification_method}</p>
          <p className="font-mono text-xxs text-muted">sha256 {doc.sha256}</p>
        </div>
        <div className="flex gap-1">
          <button className="btn" onClick={() => download(pp(pid, `/documents/${id}/original`), doc.title)}>Original</button>
          {canAI && <button className="btn" onClick={() => api(pp(pid, `/ai/documents/${id}/summary`), { method: "POST" }).then(setSummary).catch(setErr)}>Summarize (local AI)</button>}
          {canAI && <button className="btn" onClick={() => api(pp(pid, `/ai/documents/${id}/relationship-hypotheses`), { method: "POST" }).then((r) => toast.ok(`${r.created.length} unverified hypotheses created for review`)).catch(setErr)}>Suggest relationships</button>}
        </div>
      </div>
      <ErrorBox error={err} />
      {doc.metadata.injection_patterns_detected && <Notice tone="warn">This document contains text resembling instructions to an AI system. It is handled strictly as untrusted data and never executed.</Notice>}
      {doc.ocr_status.startsWith("ocr_required") && <Notice tone="warn">Some pages have no extractable text and no local OCR engine (tesseract) is installed.</Notice>}
      {doc.duplicate_of_id && <Notice tone="warn">Exact duplicate (same SHA-256) of document {doc.duplicate_of_id}.</Notice>}
      {summary && <Notice tone="hypo"><Badge tone="hypo">{summary.label}</Badge> <b>{summary.model}</b>: {summary.summary}</Notice>}
      <div className="flex items-center gap-2">
        <button className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹</button>
        <span>{doc.page_label} {page} / {doc.page_count}</span>
        <button className="btn" disabled={page >= doc.page_count} onClick={() => onPage(page + 1)}>›</button>
      </div>
      <div className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded border border-line bg-bg p-3 font-mono text-[11px] leading-relaxed">
        {(pg.data?.chunks ?? []).map((c: any) => <div key={c.id} id={c.id} className="mb-2 border-l-2 border-line pl-2">{c.text}</div>)}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="Entity candidates (unverified)" bodyClass="">
          <Table maxHeight={260} columns={["Text", "Kind", "Pages", "Method"]} rows={doc.entity_candidates.slice(0, 80).map((c: any) => [c.text,
            <Badge tone={c.kind === "known_entity" ? "accent" : "neutral"}>{c.kind}</Badge>, c.pages.join(", "), <span className="text-xxs text-muted">{c.method}</span>])} />
        </Card>
        <Card title="Keywords · similar documents">
          <div className="mb-2 flex flex-wrap gap-1">{doc.keywords.map((k: any) => <Badge key={k.term}>{k.term} {k.count}</Badge>)}</div>
          {(sim.data ?? []).slice(0, 6).map((s) => <p key={s.document_id}>{s.title} <span className="font-mono text-muted">{s.cosine}</span></p>)}
          <p className="text-[10px] text-muted">Similarity: TF-IDF cosine (lexical). Created {fmtTime(doc.created_at)}.</p>
        </Card>
      </div>
    </div>
  );
}

function Assistant({ onOpen, canAI }: { onOpen: (doc: string, page: number) => void; canAI: boolean }) {
  const pid = useProjectId();
  const [q, setQ] = useState("");
  const [useModel, setUseModel] = useState(true);
  const [ans, setAns] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const ask = async () => {
    setErr(null); setBusy(true);
    try { setAns(await api(pp(pid, "/documents/ask"), { body: { question: q, use_model: useModel } })); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Card title="Document assistant" className="mt-3">
      <div className="space-y-2 text-xs">
        <textarea className="input h-16" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question answered only from local documents…" />
        <div className="flex items-center gap-2">
          <button className="btn btn-primary" disabled={!q.trim() || busy} onClick={ask}>Ask</button>
          {canAI && <label className="flex items-center gap-1"><input type="checkbox" checked={useModel} onChange={(e) => setUseModel(e.target.checked)} /> use local model if available</label>}
        </div>
        <ErrorBox error={err} />
        {busy && <Spinner label="Retrieving evidence…" />}
        {ans && (
          <div className="space-y-2">
            <div className="flex gap-1"><Badge tone={ans.label === "direct_evidence" ? "ok" : ans.mode === "generative" ? "hypo" : "warn"}>{ans.label.replaceAll("_", " ")}</Badge><Badge>{ans.mode}</Badge>{ans.model && <Badge tone="hypo">{ans.model}</Badge>}</div>
            {ans.answer ? <p className="rounded border border-line bg-bg p-2">{ans.answer}</p> : <p className="text-muted">No answer given.</p>}
            <p className="text-muted">{ans.uncertainty}</p>
            {ans.warnings.map((w: string) => <Notice key={w} tone="warn">{w}</Notice>)}
            <h4 className="label">Evidence</h4>
            {ans.citations.map((c: Citation) => (
              <div key={c.chunk_id} className={`rounded border p-2 ${ans.cited?.includes(c.n) ? "border-accent/60" : "border-line"}`}>
                <button className="font-medium text-accent hover:underline" onClick={() => onOpen(c.document_id, c.page)}>[{c.n}] {c.title} · {c.page_label} {c.page}</button>
                {c.injection_warning && <Badge tone="warn">untrusted instructions detected</Badge>}
                <p className="mt-1 line-clamp-4 text-muted">{c.excerpt}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
