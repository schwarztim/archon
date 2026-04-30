/**
 * TanStack Query hooks for the artifact surface.
 *
 * Pairs with ``api/artifacts.ts`` and ``api/cost.ts`` (typed). Keys are
 * declared at module scope so cache invalidation is symmetric across
 * components — the cost dashboard, artifact browser, and execution
 * detail page all share the same ``["artifacts"]`` namespace.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listArtifacts,
  getArtifact,
  getArtifactContent,
  deleteArtifact,
} from "@/api/artifacts";
import { getCostSummary, getRunCost } from "@/api/cost";
import type { ListArtifactsOptions } from "@/types/artifacts";

const KEYS = {
  all: ["artifacts"] as const,
  list: (opts: ListArtifactsOptions) => ["artifacts", "list", opts] as const,
  detail: (id: string) => ["artifacts", "detail", id] as const,
  content: (id: string) => ["artifacts", "content", id] as const,
  costSummary: (params: Record<string, unknown>) =>
    ["cost", "summary", params] as const,
  runCost: (runId: string) => ["cost", "run", runId] as const,
};

/** Cursor-paginated artifact listing. */
export function useArtifacts(opts: ListArtifactsOptions = {}) {
  return useQuery({
    queryKey: KEYS.list(opts),
    queryFn: () => listArtifacts(opts),
  });
}

/** Single artifact metadata. ``enabled`` controls when the query fires
 *  — pass ``false`` while no artifact is selected. */
export function useArtifact(id: string | null | undefined) {
  return useQuery({
    queryKey: KEYS.detail(id ?? ""),
    queryFn: () => getArtifact(id as string),
    enabled: Boolean(id),
  });
}

/** Artifact content fetch. Returns a string (text/json) or Blob. */
export function useArtifactContent(id: string | null | undefined) {
  return useQuery({
    queryKey: KEYS.content(id ?? ""),
    queryFn: () => getArtifactContent(id as string),
    enabled: Boolean(id),
    staleTime: 5 * 60 * 1000,
  });
}

/** Delete mutation that invalidates the list + detail queries on success. */
export function useDeleteArtifact() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteArtifact(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}

/** Cost summary query (typed). */
export function useCostSummary(params: {
  tenant_id?: string;
  period?: string;
  since?: string;
  until?: string;
  group_by?: string;
} = {}) {
  return useQuery({
    queryKey: KEYS.costSummary(params),
    queryFn: () => getCostSummary(params),
    staleTime: 30_000,
  });
}

/** Per-run cost rollup. */
export function useRunCost(runId: string | null | undefined) {
  return useQuery({
    queryKey: KEYS.runCost(runId ?? ""),
    queryFn: () => getRunCost(runId as string),
    enabled: Boolean(runId),
  });
}

export const ARTIFACT_KEYS = KEYS;
