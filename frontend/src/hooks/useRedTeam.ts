import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  startScan,
  getScanResult,
  getScanSarif,
  getAgentSecurityHistory,
} from "@/api/redteam";

const SECURITY_SCAN_KEY = ["security-scan"] as const;

export function useScanResult(scanId: string | null) {
  return useQuery({
    queryKey: [...SECURITY_SCAN_KEY, scanId],
    queryFn: () => getScanResult(scanId!),
    enabled: !!scanId,
    refetchInterval: (query) => {
      const data = query.state.data?.data;
      const status = data && 'status' in data ? (data as { status?: string }).status : undefined;
      return status === "running" || status === "pending" ? 3000 : false;
    },
  });
}

export function useScanSarif(scanId: string | null) {
  return useQuery({
    queryKey: [...SECURITY_SCAN_KEY, scanId, "sarif"],
    queryFn: () => getScanSarif(scanId!),
    enabled: !!scanId,
  });
}

export function useAgentSecurityHistory(agentId: string | null) {
  return useQuery({
    queryKey: [...SECURITY_SCAN_KEY, "history", agentId],
    queryFn: () => getAgentSecurityHistory(agentId!),
    enabled: !!agentId,
  });
}

export function useStartScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      agent_id: string;
      attack_types: string[];
      name?: string;
    }) => startScan(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SECURITY_SCAN_KEY });
    },
  });
}
