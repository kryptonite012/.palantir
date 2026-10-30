import { useAtlas } from "../app/store";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; params?: Record<string, unknown>; raw?: boolean };

export function buildUrl(path: string, params?: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => qs.append(k, String(x)));
    else qs.append(k, String(v));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const token = useAtlas.getState().token;
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(buildUrl(path, opts.params), { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && token) {
    useAtlas.getState().setSession(null, null);
  }
  if (!res.ok) {
    let code = "error";
    let message = res.statusText;
    let details = {};
    try {
      const j = await res.json();
      code = j.error?.code ?? code;
      message = j.error?.message ?? message;
      details = j.error?.details ?? {};
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, code, message, details);
  }
  if (opts.raw) return res as unknown as T;
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export async function download(path: string, filename: string, opts: Opts = {}) {
  const res = await api<Response>(path, { ...opts, raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const errs = (e.details?.errors as unknown[]) ?? [];
    if (errs.length) return `${e.message}: ${errs.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join("; ")}`;
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

/** Poll a job until it reaches a terminal state. */
export async function waitForJob(jobId: string, onUpdate?: (j: any) => void, intervalMs = 600): Promise<any> {
  for (;;) {
    const j = await api(`/api/jobs/${jobId}`);
    onUpdate?.(j);
    if (["succeeded", "failed", "cancelled"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export const pp = (pid: string | null, rest: string) => `/api/projects/${pid}${rest}`;
