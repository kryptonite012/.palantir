import { useQuery } from "@tanstack/react-query";
import { api, pp } from "../services/api";
import { useAtlas } from "./store";
import type { Project } from "../types/api";

export function useProjectId(): string | null {
  return useAtlas((s) => s.projectId);
}

export function useProject() {
  const pid = useProjectId();
  return useQuery<Project>({ queryKey: ["project", pid], queryFn: () => api(pp(pid, "")), enabled: !!pid });
}

export function useCan(perm: string): boolean {
  const { data } = useProject();
  return !!data?.permissions?.includes(perm);
}

export function useGlobalCan(perm: string): boolean {
  const u = useAtlas((s) => s.user);
  return !!u?.global_permissions?.includes(perm);
}

export function usePQuery<T = any>(key: unknown[], rest: string, params?: Record<string, unknown>, enabled = true) {
  const pid = useProjectId();
  return useQuery<T>({ queryKey: [pid, ...key, params], queryFn: () => api<T>(pp(pid, rest), { params }), enabled: !!pid && enabled });
}
