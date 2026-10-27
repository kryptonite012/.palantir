import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../services/api";
import { useAtlas } from "./store";
import { Logo } from "../components/Logo";
import { Badge, Modal } from "../components/ui";
import type { Job, Project } from "../types/api";

export const NAV: { to: string; label: string; icon: string; key?: string }[] = [
  { to: "/", label: "Atlas Home", icon: "⌂", key: "h" },
  { to: "/catalog", label: "Data Catalog", icon: "▤", key: "c" },
  { to: "/ingestion", label: "Ingestion", icon: "⇪", key: "i" },
  { to: "/search", label: "Global Search", icon: "⌕", key: "s" },
  { to: "/entities", label: "Entity Explorer", icon: "◉", key: "e" },
  { to: "/graph", label: "Knowledge Graph", icon: "⛬", key: "g" },
  { to: "/timeline", label: "Timeline", icon: "⏱", key: "t" },
  { to: "/geo", label: "Geospatial Explorer", icon: "◍", key: "m" },
  { to: "/analytics", label: "Analytics", icon: "∑", key: "a" },
  { to: "/documents", label: "Documents", icon: "▧", key: "d" },
  { to: "/investigations", label: "Investigations", icon: "⚑", key: "v" },
  { to: "/workflows", label: "Workflows", icon: "⇄", key: "w" },
  { to: "/reports", label: "Reports", icon: "▦", key: "r" },
  { to: "/audit", label: "Audit Center", icon: "⛨", key: "u" },
  { to: "/admin", label: "Administration", icon: "⚙", key: "x" },
  { to: "/settings", label: "Settings", icon: "☰", key: "," },
];

function TopBar() {
  const { user, projectId, setProject, setSession } = useAtlas();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [menu, setMenu] = useState<"jobs" | "notes" | "user" | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const projects = useQuery<Project[]>({ queryKey: ["projects"], queryFn: () => api("/api/projects") });
  const health = useQuery({ queryKey: ["health"], queryFn: () => api("/api/health"), refetchInterval: 30_000 });
  const ai = useQuery({ queryKey: ["ai-status"], queryFn: () => api("/api/ai/status"), refetchInterval: 60_000 });
  const jobs = useQuery<Job[]>({
    queryKey: ["jobs", projectId], queryFn: () => api("/api/jobs", { params: { project_id: projectId, limit: 15 } }),
    enabled: !!projectId, refetchInterval: (query) => ((query.state.data ?? []).some((j) => ["running", "queued"].includes(j.status)) ? 1500 : 10_000),
  });
  const running = (jobs.data ?? []).filter((j) => j.status === "running" || j.status === "queued");
  const failed = (jobs.data ?? []).filter((j) => j.status === "failed");

  useEffect(() => {
    if (!projectId && projects.data?.length) setProject(projects.data[0].id);
    if (projectId && projects.data && !projects.data.some((p) => p.id === projectId)) setProject(projects.data[0]?.id ?? null);
  }, [projects.data, projectId, setProject]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      setSession(null, null);
      qc.clear();
    }
  };

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-line bg-panel px-3">
      <select aria-label="Active project" className="input w-56" value={projectId ?? ""}
        onChange={(e) => { setProject(e.target.value || null); qc.invalidateQueries(); }}>
        {(projects.data ?? []).length === 0 && <option value="">No projects</option>}
        {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <form className="flex-1" onSubmit={(e) => { e.preventDefault(); if (q.trim()) nav(`/search?q=${encodeURIComponent(q.trim())}`); }}>
        <input ref={searchRef} className="input max-w-xl" placeholder='Search everything…  ("/" to focus)' value={q}
          onChange={(e) => setQ(e.target.value)} aria-label="Global search" />
      </form>
      <div className="relative">
        <button className="btn btn-ghost" onClick={() => setMenu(menu === "jobs" ? null : "jobs")} aria-label="Jobs">
          {running.length ? <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> : <span className="h-2 w-2 rounded-full bg-ok" />}
          Jobs {running.length > 0 && <Badge tone="accent">{running.length}</Badge>}
        </button>
        {menu === "jobs" && (
          <div className="card absolute right-0 top-9 z-40 w-96 p-2 shadow-xl">
            {(jobs.data ?? []).length === 0 && <p className="p-2 text-xs text-muted">No jobs in this project yet.</p>}
            {(jobs.data ?? []).map((j) => (
              <div key={j.id} className="flex items-center justify-between gap-2 border-b border-line/50 py-1 text-xs last:border-0">
                <span className="truncate">{j.kind} <span className="text-muted">{j.message}</span></span>
                <span className="flex items-center gap-1">
                  {j.status === "running" && <span className="font-mono text-xxs">{Math.round(j.progress * 100)}%</span>}
                  <Badge tone={({ succeeded: "ok", failed: "danger", running: "accent" } as Record<string, string>)[j.status] ?? "neutral"}>{j.status}</Badge>
                  {(j.status === "running" || j.status === "queued") && (
                    <button className="btn btn-ghost" onClick={() => api(`/api/jobs/${j.id}/cancel`, { method: "POST" }).then(() => jobs.refetch())}>Cancel</button>
                  )}
                  {j.status === "failed" && (
                    <button className="btn btn-ghost" onClick={() => api(`/api/jobs/${j.id}/retry`, { method: "POST" }).then(() => jobs.refetch())}>Retry</button>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="relative">
        <button className="btn btn-ghost" aria-label="Notifications" onClick={() => setMenu(menu === "notes" ? null : "notes")}>
          Alerts {failed.length > 0 && <Badge tone="danger">{failed.length}</Badge>}
        </button>
        {menu === "notes" && (
          <div className="card absolute right-0 top-9 z-40 w-80 p-2 text-xs shadow-xl">
            {failed.length === 0 ? <p className="p-2 text-muted">No failed jobs.</p> :
              failed.map((j) => <p key={j.id} className="border-b border-line/50 py-1"><b>{j.kind}</b> failed: {j.error}</p>)}
          </div>
        )}
      </div>
      <span title={health.data?.offline_mode ? "Offline mode: outbound network blocked for Atlas" : "Offline mode disabled"}>
        <Badge tone={health.data?.offline_mode ? "ok" : "warn"}>{health.data?.offline_mode ? "● Offline" : "● Network"}</Badge>
      </span>
      <span title="Local AI availability"><Badge tone={ai.data?.available ? "hypo" : "neutral"}>AI {ai.data?.available ? "ready" : "off"}</Badge></span>
      <div className="relative">
        <button className="btn btn-ghost" onClick={() => setMenu(menu === "user" ? null : "user")}>
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent/20 text-xxs font-bold text-accent">
            {user?.display_name?.[0]?.toUpperCase()}
          </span>
          {user?.username}
        </button>
        {menu === "user" && (
          <div className="card absolute right-0 top-9 z-40 w-56 p-2 text-xs shadow-xl">
            <p className="px-1 font-semibold">{user?.display_name}</p>
            <p className="px-1 text-muted">{user?.global_role_label ?? "Project roles only"}</p>
            <hr className="my-2 border-line" />
            <button className="btn btn-ghost w-full" onClick={() => { setMenu(null); nav("/settings"); }}>Settings</button>
            <button className="btn btn-ghost w-full" onClick={logout}>Sign out</button>
          </div>
        )}
      </div>
    </header>
  );
}

function Tabs() {
  const { tabs, closeTab, openTab } = useAtlas();
  const loc = useLocation();
  const nav = useNavigate();
  useEffect(() => {
    const item = NAV.find((n) => (n.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.to)));
    const sub = loc.pathname.split("/").length > 2 ? " · detail" : "";
    if (item) openTab(loc.pathname + loc.search, item.label + sub);
  }, [loc.pathname, loc.search, openTab]);
  if (tabs.length < 2) return null;
  return (
    <div className="flex h-7 shrink-0 items-end gap-0.5 overflow-x-auto border-b border-line bg-bg px-2">
      {tabs.map((t) => {
        const active = t.path === loc.pathname + loc.search;
        return (
          <div key={t.path} className={`flex items-center gap-1 rounded-t border border-b-0 px-2 py-0.5 text-xxs ${active ? "border-line bg-panel" : "border-transparent text-muted"}`}>
            <button onClick={() => nav(t.path)}>{t.title}</button>
            <button aria-label={`Close ${t.title}`} className="opacity-60 hover:opacity-100" onClick={() => { closeTab(t.path); if (active) nav("/"); }}>×</button>
          </div>
        );
      })}
    </div>
  );
}

function Shortcuts() {
  const nav = useNavigate();
  const [help, setHelp] = useState(false);
  useEffect(() => {
    let pending = false;
    let timer: number | undefined;
    const h = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return;
      if (e.key === "?") return setHelp(true);
      if (e.key === "g" && !pending) {
        pending = true;
        timer = window.setTimeout(() => (pending = false), 900);
        return;
      }
      if (pending) {
        pending = false;
        window.clearTimeout(timer);
        const item = NAV.find((n) => n.key === e.key);
        if (item) nav(item.to);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [nav]);
  return (
    <Modal open={help} title="Keyboard shortcuts" onClose={() => setHelp(false)}>
      <ul className="grid grid-cols-2 gap-1 text-xs">
        <li><span className="kbd">/</span> focus search</li>
        <li><span className="kbd">?</span> this help</li>
        {NAV.map((n) => <li key={n.to}><span className="kbd">g</span> <span className="kbd">{n.key}</span> {n.label}</li>)}
      </ul>
    </Modal>
  );
}

export function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="flex h-full">
      <nav aria-label="Primary" className={`flex shrink-0 flex-col border-r border-line bg-panel ${collapsed ? "w-12" : "w-52"}`}>
        <div className="flex h-11 items-center justify-between border-b border-line px-2.5">
          <Logo compact={collapsed} />
          <button className="btn btn-ghost px-1" onClick={() => setCollapsed(!collapsed)} aria-label="Toggle sidebar">{collapsed ? "»" : "«"}</button>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} title={n.label}
              className={({ isActive }) => `mx-1 flex items-center gap-2 rounded px-2 py-1.5 text-xs ${isActive ? "bg-accent/15 text-ink" : "text-muted hover:bg-raised hover:text-ink"}`}>
              <span className="w-4 text-center text-sm">{n.icon}</span>
              {!collapsed && n.label}
            </NavLink>
          ))}
        </div>
        {!collapsed && <p className="border-t border-line px-3 py-2 text-[10px] text-muted">Project Atlas · local deployment</p>}
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <Tabs />
        <main className="min-h-0 flex-1 overflow-auto p-4">
          <Outlet />
        </main>
      </div>
      <Shortcuts />
    </div>
  );
}
