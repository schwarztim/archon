import {
  useQuery,
  useMutation,
  useQueryClient,
  type QueryKey,
  type UseQueryOptions,
} from "@tanstack/react-query";
import type { ApiResponse } from "@/types";

// ─── Generic helpers ─────────────────────────────────────────────────

/** Generic query hook — wraps useQuery with proper typing for API envelope */
export function useApiQuery<T>(
  key: QueryKey,
  fetcher: () => Promise<ApiResponse<T>>,
  options?: Omit<UseQueryOptions<ApiResponse<T>>, "queryKey" | "queryFn">,
) {
  return useQuery<ApiResponse<T>>({
    queryKey: key,
    queryFn: fetcher,
    ...options,
  });
}

/** Generic mutation hook — wraps useMutation and invalidates keys on success */
export function useApiMutation<TData, TVariables>(
  mutationFn: (variables: TVariables) => Promise<ApiResponse<TData> | void>,
  invalidateKeys?: QueryKey[],
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      invalidateKeys?.forEach((key) => {
        void qc.invalidateQueries({ queryKey: key });
      });
    },
  });
}

// ─── Domain-specific hooks ──────────────────────────────────────────

import { listModels } from "@/api/router";
import { listDeployments } from "@/api/lifecycle";
import { getBudgets } from "@/api/cost";
import { listPolicies as listDLPPolicies } from "@/api/dlp";
import { listPolicies as listGovPolicies } from "@/api/governance";
import { listScans } from "@/api/sentinelscan";
import { listTenants } from "@/api/tenancy";
import { searchListings } from "@/api/marketplace";
import { listExecutions } from "@/api/executions";
import type { PaginationParams } from "@/api/client";

const KEYS = {
  models: ["models"] as const,
  deployments: ["deployments"] as const,
  budgets: ["budgets"] as const,
  dlpPolicies: ["dlp-policies"] as const,
  govPolicies: ["gov-policies"] as const,
  scans: ["scans"] as const,
  tenants: ["tenants"] as const,
  marketplace: ["marketplace"] as const,
  executions: ["executions"] as const,
};

export function useModels(params: PaginationParams = {}) {
  return useApiQuery(
    [...KEYS.models, params],
    () => listModels(params),
  );
}

export function useDeployments(
  params: PaginationParams & { agent_id?: string } = {},
) {
  return useApiQuery(
    [...KEYS.deployments, params],
    () => listDeployments(params),
  );
}

export function useBudgets(
  params: PaginationParams & { tenant_id?: string } = {},
) {
  return useApiQuery(
    [...KEYS.budgets, params],
    () => getBudgets(params),
  );
}

export function useDLPPolicies(params: PaginationParams = {}) {
  return useApiQuery(
    [...KEYS.dlpPolicies, params],
    () => listDLPPolicies(params),
  );
}

export function useGovernancePolicies(params: PaginationParams = {}) {
  return useApiQuery(
    [...KEYS.govPolicies, params],
    () => listGovPolicies(params),
  );
}

export function useScans(params: PaginationParams = {}) {
  return useApiQuery(
    [...KEYS.scans, params],
    () => listScans(params),
  );
}

export function useTenants(params: PaginationParams = {}) {
  return useApiQuery(
    [...KEYS.tenants, params],
    () => listTenants(params),
  );
}

export function useMarketplace(
  params: PaginationParams & { search?: string; category?: string } = {},
) {
  return useApiQuery(
    [...KEYS.marketplace, params],
    () => searchListings(params),
  );
}

export function useExecutions(
  params: PaginationParams & { agent_id?: string } = {},
) {
  return useApiQuery(
    [...KEYS.executions, params],
    () => listExecutions(params),
  );
}
