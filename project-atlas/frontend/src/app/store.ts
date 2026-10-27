import { create } from "zustand";
import type { User } from "../types/api";

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* storage unavailable: preferences are non-critical */
  }
}

type Theme = "dark" | "light";

interface AtlasState {
  token: string | null;
  user: User | null;
  projectId: string | null;
  theme: Theme;
  recentProjects: string[];
  tabs: { path: string; title: string }[];
  setSession: (token: string | null, user: User | null) => void;
  setUser: (u: User | null) => void;
  setProject: (id: string | null) => void;
  setTheme: (t: Theme) => void;
  openTab: (path: string, title: string) => void;
  closeTab: (path: string) => void;
}

// The session token lives in sessionStorage (cleared when the window closes), never in localStorage.
const initialToken = (() => {
  try {
    return sessionStorage.getItem("atlas.token");
  } catch {
    return null;
  }
})();

export const useAtlas = create<AtlasState>((set, get) => ({
  token: initialToken,
  user: null,
  projectId: read<string | null>("atlas.project", null),
  theme: read<Theme>("atlas.theme", "dark"),
  recentProjects: read<string[]>("atlas.recent", []),
  tabs: read<{ path: string; title: string }[]>("atlas.tabs", []),
  setSession: (token, user) => {
    try {
      if (token) sessionStorage.setItem("atlas.token", token);
      else sessionStorage.removeItem("atlas.token");
    } catch {
      /* ignore */
    }
    set({ token, user });
  },
  setUser: (user) => set({ user }),
  setProject: (id) => {
    const recent = id ? [id, ...get().recentProjects.filter((x) => x !== id)].slice(0, 6) : get().recentProjects;
    write("atlas.project", id);
    write("atlas.recent", recent);
    set({ projectId: id, recentProjects: recent });
  },
  setTheme: (theme) => {
    write("atlas.theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
    set({ theme });
  },
  openTab: (path, title) => {
    const tabs = get().tabs;
    if (tabs.some((t) => t.path === path)) return;
    const next = [...tabs, { path, title }].slice(-8);
    write("atlas.tabs", next);
    set({ tabs: next });
  },
  closeTab: (path) => {
    const next = get().tabs.filter((t) => t.path !== path);
    write("atlas.tabs", next);
    set({ tabs: next });
  },
}));
