import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listAgents,
  getAgent,
  createAgent,
  updateAgent,
  deleteAgent,
} from "@/api/agents";
import type { AppNode, AppEdge } from "@/types";

const AGENTS_KEY = ["agents"] as const;

export function useAgentsList(limit = 20, offset = 0) {
  return useQuery({
    queryKey: [...AGENTS_KEY, limit, offset],
    queryFn: () => listAgents(limit, offset),
  });
}

export function useAgent(id: string | null) {
  return useQuery({
    queryKey: [...AGENTS_KEY, id],
    queryFn: () => getAgent(id!),
    enabled: !!id,
  });
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      name: string;
      description?: string;
      nodes: AppNode[];
      edges: AppEdge[];
    }) => createAgent(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: AGENTS_KEY });
    },
  });
}

export function useUpdateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string;
      name?: string;
      description?: string;
      nodes?: AppNode[];
      edges?: AppEdge[];
    }) => updateAgent(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: AGENTS_KEY });
    },
  });
}

export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteAgent(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: AGENTS_KEY });
    },
  });
}
