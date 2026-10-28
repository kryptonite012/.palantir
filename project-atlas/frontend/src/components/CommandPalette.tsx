import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, pp } from "../services/api";
import { useAtlas } from "../app/store";
import { askText, toast } from "./feedback";

type Item = { id: string; group: string; label: string; hint?: string; run: () => void | Promise<void> };

export function CommandPalette({ nav: navItems }: { nav: { to: string; label: string; icon: string }[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const { projectId, theme, setTheme } = useAtlas();

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const opener = () => setOpen(true);
    window.addEventListener("keydown", h);
    window.addEventListener("atlas:palette", opener);
    return () => { window.removeEventListener("keydown", h); window.removeEventListener("atlas:palette", opener); };
  }, []);
  useEffect(() => { if (open) { setQ(""); setSel(0); window.setTimeout(() => input.current?.focus(), 0); } }, [open]);

  const views = useQuery<any[]>({ queryKey: ["views", projectId], queryFn: () => api("/api/views", { params: { project_id: projectId } }), enabled: open });
  const datasets = useQuery<any[]>({ queryKey: [projectId, "datasets", undefined], queryFn: () => api(pp(projectId, "/datasets")), enabled: open && !!projectId });
  const docs = useQuery<any[]>({ queryKey: [projectId, "documents", undefined], queryFn: () => api(pp(projectId, "/documents")), enabled: open && !!projectId });
  const term = q.trim();
  const ents = useQuery<any>({ queryKey: ["palette-ents", projectId, term], queryFn: () => api(pp(projectId, "/entities"), { params: { q: term, limit: 8 } }),
    enabled: open && !!projectId && term.length >= 2 });

  const saveView = async () => {
    const name = await askText({ title: "Save current view", label: "Name", defaultValue: document.title.replace(" — Project Atlas", ""), confirmText: "Save" });
    if (!name) return;
    await api("/api/views", { body: { name, path: loc.pathname + loc.search, project_id: projectId } });
    qc.invalidateQueries({ queryKey: ["views"] });
    toast.ok(`View “${name}” saved — find it with Ctrl+K`);
  };

  const items: Item[] = useMemo(() => {
    const go = (to: string) => () => navigate(to);
    const list: Item[] = [
      ...navItems.map((n) => ({ id: `nav${n.to}`, group: "Go to", label: `${n.icon}  ${n.label}`, run: go(n.to) })),
      { id: "a-import", group: "Actions", label: "Import a dataset", run: go("/ingestion") },
      { id: "a-search", group: "Actions", label: term ? `Search everything for “${term}”` : "Global search", run: go(term ? `/search?q=${encodeURIComponent(term)}` : "/search") },
      { id: "a-view", group: "Actions", label: "Save current view…", hint: loc.pathname, run: saveView },
      { id: "a-inv", group: "Actions", label: "New investigation", run: go("/investigations?new=1") },
      { id: "a-demo", group: "Actions", label: "Create the synthetic demo workspace", run: go("/projects?demo=1") },
      { id: "a-theme", group: "Actions", label: `Switch to ${theme === "dark" ? "light" : "dark"} theme`, run: () => setTheme(theme === "dark" ? "light" : "dark") },
      { id: "a-offline", group: "Actions", label: "Run offline verification", run: go("/admin?tab=system") },
      ...(views.data ?? []).map((v) => ({ id: `v${v.id}`, group: "Saved views", label: v.name, hint: v.path, run: go(v.path) })),
      ...(datasets.data ?? []).map((d) => ({ id: `d${d.id}`, group: "Datasets", label: d.name, hint: `v${d.current_version} · ${d.latest?.record_count ?? 0} records`, run: go(`/catalog/${d.id}`) })),
      ...(docs.data ?? []).map((d) => ({ id: `doc${d.id}`, group: "Documents", label: d.title, hint: d.media_type, run: go(`/documents?doc=${d.id}`) })),
      ...((ents.data?.entities ?? []) as any[]).map((e) => ({ id: `e${e.id}`, group: "Entities", label: e.display_name, hint: e.entity_type, run: go(`/entities/${e.id}`) })),
    ];
    if (!term) return list.filter((i) => i.group !== "Entities");
    const t = term.toLowerCase();
    const order = ["Entities", "Saved views", "Datasets", "Documents", "Go to", "Actions"];
    return list.filter((i) => i.group === "Entities" || i.id === "a-search" || `${i.label} ${i.hint ?? ""}`.toLowerCase().includes(t))
      .sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group));
  }, [navItems, term, views.data, datasets.data, docs.data, ents.data, theme, loc.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => setSel(0), [term]);
  if (!open) return null;
  const run = async (i: Item) => { setOpen(false); try { await i.run(); } catch (e: any) { toast.error(e?.message ?? String(e)); } };
  let lastGroup = "";
  return (
    <div className="fixed inset-0 z-[65] flex items-start justify-center bg-black/50 p-4 pt-[12vh]" onMouseDown={() => setOpen(false)}>
      <div role="dialog" aria-label="Command palette" className="card w-full max-w-xl overflow-hidden shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <input ref={input} className="w-full border-b border-line bg-transparent px-4 py-3 text-sm outline-none" placeholder="Type a page, dataset, entity, view or action…"
          value={q} onChange={(e) => setQ(e.target.value)} aria-label="Command"
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(items.length - 1, s + 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
            if (e.key === "Enter" && items[sel]) run(items[sel]);
          }} />
        <ul className="max-h-[55vh] overflow-y-auto py-1" role="listbox">
          {items.map((i, idx) => {
            const header = i.group !== lastGroup ? (lastGroup = i.group) : null;
            return (
              <li key={i.id}>
                {header && <div className="px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted">{header}</div>}
                <button role="option" aria-selected={idx === sel} onMouseEnter={() => setSel(idx)} onClick={() => run(i)}
                  className={`flex w-full items-center justify-between gap-3 px-4 py-1.5 text-left text-xs ${idx === sel ? "bg-accent/15" : ""}`}>
                  <span className="truncate">{i.label}</span>
                  {i.hint && <span className="shrink-0 truncate font-mono text-[10px] text-muted">{i.hint}</span>}
                </button>
              </li>
            );
          })}
          {items.length === 0 && <li className="px-4 py-6 text-center text-xs text-muted">No matches</li>}
        </ul>
        <div className="flex gap-3 border-t border-line px-4 py-1.5 text-[10px] text-muted"><span><span className="kbd">↑↓</span> move</span><span><span className="kbd">Enter</span> open</span><span><span className="kbd">Esc</span> close</span></div>
      </div>
    </div>
  );
}
