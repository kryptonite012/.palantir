import { useEffect, useRef, useState } from "react";
import { create } from "zustand";

/* In-app toasts and dialogs (replace window.alert/prompt/confirm, which block the UI and cannot be styled). */

type Tone = "ok" | "danger" | "accent" | "warn";
type ToastItem = { id: number; tone: Tone; text: string; action?: { label: string; run: () => void } };
type Dialog =
  | { kind: "text"; title: string; label?: string; body?: string; defaultValue?: string; password?: boolean; mustEqual?: string;
      confirmText?: string; danger?: boolean; multiline?: boolean; resolve: (v: string | null) => void }
  | { kind: "confirm"; title: string; body?: string; confirmText?: string; danger?: boolean; resolve: (v: boolean) => void };

interface FeedbackState {
  toasts: ToastItem[];
  dialog: Dialog | null;
  push: (t: Omit<ToastItem, "id">) => void;
  dismiss: (id: number) => void;
  open: (d: Dialog) => void;
  close: () => void;
}

let seq = 0;
export const useFeedback = create<FeedbackState>((set, get) => ({
  toasts: [],
  dialog: null,
  push: (t) => {
    const id = ++seq;
    set({ toasts: [...get().toasts, { ...t, id }].slice(-3) });
    window.setTimeout(() => get().dismiss(id), t.tone === "danger" ? 8000 : 4500);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
  open: (dialog) => set({ dialog }),
  close: () => set({ dialog: null }),
}));

export const toast = {
  ok: (text: string, action?: ToastItem["action"]) => useFeedback.getState().push({ tone: "ok", text, action }),
  error: (text: string) => useFeedback.getState().push({ tone: "danger", text }),
  info: (text: string, action?: ToastItem["action"]) => useFeedback.getState().push({ tone: "accent", text, action }),
};

export function askText(opts: Omit<Extract<Dialog, { kind: "text" }>, "kind" | "resolve">): Promise<string | null> {
  return new Promise((resolve) => useFeedback.getState().open({ kind: "text", ...opts, resolve }));
}

export function askConfirm(opts: Omit<Extract<Dialog, { kind: "confirm" }>, "kind" | "resolve">): Promise<boolean> {
  return new Promise((resolve) => useFeedback.getState().open({ kind: "confirm", ...opts, resolve }));
}

const TONE: Record<Tone, string> = {
  ok: "border-ok/50 bg-ok/15", danger: "border-danger/50 bg-danger/15", accent: "border-accent/50 bg-accent/15", warn: "border-warn/50 bg-warn/15",
};

export function FeedbackHost() {
  const { toasts, dismiss, dialog, close } = useFeedback();
  const [value, setValue] = useState("");
  const input = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  useEffect(() => {
    if (dialog?.kind === "text") {
      setValue(dialog.defaultValue ?? "");
      window.setTimeout(() => input.current?.focus(), 0);
    }
  }, [dialog]);
  const finish = (ok: boolean) => {
    if (!dialog) return;
    if (dialog.kind === "text") dialog.resolve(ok ? value : null);
    else dialog.resolve(ok);
    close();
  };
  const blocked = dialog?.kind === "text" && dialog.mustEqual !== undefined && value !== dialog.mustEqual;
  return (
    <>
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-96 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role="status" className={`pointer-events-auto flex items-start gap-2 rounded-md border px-3 py-2 text-xs shadow-lg backdrop-blur ${TONE[t.tone]}`}>
            <span className="flex-1">{t.text}</span>
            {t.action && <button className="btn" onClick={() => { t.action!.run(); dismiss(t.id); }}>{t.action.label}</button>}
            <button aria-label="Dismiss" className="opacity-60 hover:opacity-100" onClick={() => dismiss(t.id)}>✕</button>
          </div>
        ))}
      </div>
      {dialog && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" onMouseDown={() => finish(false)}>
          <form role="dialog" aria-label={dialog.title} className="card w-full max-w-md p-4" onMouseDown={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); if (!blocked) finish(true); }}
            onKeyDown={(e) => { if (e.key === "Escape") finish(false); }}>
            <h2 className="mb-2 text-sm font-semibold">{dialog.title}</h2>
            {dialog.body && <p className="mb-3 whitespace-pre-line text-xs text-muted">{dialog.body}</p>}
            {dialog.kind === "text" && (
              <label className="block">
                {dialog.label && <span className="label">{dialog.label}</span>}
                {dialog.multiline
                  ? <textarea ref={input} className="input h-24" value={value} onChange={(e) => setValue(e.target.value)} />
                  : <input ref={input} className="input" type={dialog.password ? "password" : "text"} value={value} onChange={(e) => setValue(e.target.value)} />}
                {dialog.mustEqual !== undefined && <span className="mt-1 block text-xxs text-muted">Type <b>{dialog.mustEqual}</b> to confirm.</span>}
              </label>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="btn" onClick={() => finish(false)}>Cancel</button>
              <button type="submit" autoFocus={dialog.kind === "confirm"} disabled={blocked}
                className={`btn ${dialog.danger ? "btn-danger" : "btn-primary"}`}>{dialog.confirmText ?? "OK"}</button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
