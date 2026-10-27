import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../services/api";

export function Card({ title, actions, children, className = "", bodyClass = "p-3" }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title !== undefined && (
        <header className="card-h">
          <span>{title}</span>
          <div className="flex items-center gap-1.5">{actions}</div>
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <div>
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

export function Stat({ label, value, hint, onClick }: { label: string; value: ReactNode; hint?: ReactNode; onClick?: () => void }) {
  return (
    <button onClick={onClick} disabled={!onClick}
      className="card flex flex-col items-start gap-0.5 px-3 py-2.5 text-left transition-colors hover:border-accent/60 disabled:hover:border-line">
      <span className="text-xxs font-semibold uppercase tracking-wider text-muted">{label}</span>
      <span className="font-mono text-xl font-semibold tabular-nums">{value}</span>
      {hint && <span className="text-xxs text-muted">{hint}</span>}
    </button>
  );
}

const TONES: Record<string, string> = {
  neutral: "bg-raised text-muted", accent: "bg-accent/15 text-accent", ok: "bg-ok/15 text-ok", warn: "bg-warn/15 text-warn",
  danger: "bg-danger/15 text-danger", hypo: "bg-hypo/15 text-hypo",
};
export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: keyof typeof TONES | string; title?: string }) {
  return <span title={title} className={`chip ${TONES[tone] ?? TONES.neutral}`}>{children}</span>;
}

export const ASSERTION_TONE: Record<string, string> = { observed: "ok", inferred: "accent", model_suggested: "hypo", manual: "warn" };
export const ASSERTION_LABEL: Record<string, string> = {
  observed: "Observed", inferred: "Deterministic inference", model_suggested: "Model hypothesis", manual: "Manual assertion",
};
export function AssertionBadge({ kind, status }: { kind: string; status?: string }) {
  return (
    <span className="inline-flex gap-1">
      <Badge tone={ASSERTION_TONE[kind]}>{ASSERTION_LABEL[kind] ?? kind}</Badge>
      {status && status !== "active" && <Badge tone={status === "rejected" ? "danger" : "hypo"}>{status}</Badge>}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone = { succeeded: "ok", failed: "danger", running: "accent", queued: "neutral", cancelled: "warn",
    confirmed_by_reviewer: "ok", disputed: "warn", rejected: "danger", under_review: "accent", draft: "neutral",
    superseded: "neutral", pending: "accent", accepted: "ok", strong: "ok", ambiguous: "warn" }[status] ?? "neutral";
  return <Badge tone={tone}>{status.replaceAll("_", " ")}</Badge>;
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line px-6 py-10 text-center">
      <img src="/atlas-icon.svg" alt="" className="h-8 w-8 opacity-60" />
      <p className="text-sm font-medium">{title}</p>
      {children && <p className="max-w-md text-xs text-muted">{children}</p>}
      {action}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-3 text-xs text-muted">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      {label ?? "Loading…"}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">{errorText(error)}</div>;
}

export function Notice({ tone = "accent", children }: { tone?: string; children: ReactNode }) {
  const cls = { accent: "border-accent/40 bg-accent/10", warn: "border-warn/40 bg-warn/10", hypo: "border-hypo/40 bg-hypo/10",
    ok: "border-ok/40 bg-ok/10" }[tone] ?? "border-line";
  return <div className={`rounded-md border px-3 py-2 text-xs ${cls}`}>{children}</div>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div>
      <label className="block">
        <span className="label">{label}</span>
        {children}
      </label>
      {hint && <span className="mt-0.5 block text-xxs text-muted">{hint}</span>}
    </div>
  );
}

export function Modal({ open, title, onClose, children, wide }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div role="dialog" aria-label={title} className={`card max-h-[90vh] w-full overflow-auto ${wide ? "max-w-4xl" : "max-w-lg"}`}
        onClick={(e) => e.stopPropagation()}>
        <header className="card-h">
          <span>{title}</span>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <div className="p-3">{children}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="mb-3 flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${value === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Horizontally resizable two-pane layout; the split ratio is remembered per id. */
export function SplitPane({ id, left, right, initial = 0.6 }: { id: string; left: ReactNode; right: ReactNode; initial?: number }) {
  const key = `atlas.split.${id}`;
  const [ratio, setRatio] = useState<number>(() => {
    try {
      return Number(localStorage.getItem(key)) || initial;
    } catch {
      return initial;
    }
  });
  const ref = useRef<HTMLDivElement>(null);
  const onDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const move = (ev: MouseEvent) => {
      const r = ref.current?.getBoundingClientRect();
      if (!r) return;
      const v = Math.min(0.85, Math.max(0.15, (ev.clientX - r.left) / r.width));
      setRatio(v);
      try {
        localStorage.setItem(key, String(v));
      } catch {
        /* ignore */
      }
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }, [key]);
  return (
    <div ref={ref} className="flex h-full min-h-0 w-full">
      <div style={{ width: `${ratio * 100}%` }} className="min-w-0 overflow-auto">{left}</div>
      <div role="separator" aria-orientation="vertical" onMouseDown={onDown}
        className="w-1.5 shrink-0 cursor-col-resize bg-transparent hover:bg-accent/40" />
      <div className="min-w-0 flex-1 overflow-auto">{right}</div>
    </div>
  );
}

export function Json({ value, max = 400 }: { value: unknown; max?: number }) {
  return <pre className="overflow-auto rounded bg-bg p-2 font-mono text-xxs text-muted" style={{ maxHeight: max }}>{JSON.stringify(value, null, 2)}</pre>;
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function fmtBytes(n: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function fmtTime(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || /[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? s : d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

export function Table({ columns, rows, empty = "No rows", maxHeight }: {
  columns: ReactNode[]; rows: ReactNode[][]; empty?: string; maxHeight?: number;
}) {
  return (
    <div className="overflow-auto" style={{ maxHeight }}>
      <table className="tbl">
        <thead><tr>{columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={columns.length} className="py-6 text-center text-muted">{empty}</td></tr>}
          {rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}
