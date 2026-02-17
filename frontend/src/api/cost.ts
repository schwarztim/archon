import type { ApiResponse } from "@/types";
import type {
  TokenLedger,
  Budget,
  CostReport,
  CostForecast,
} from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** Record token usage */
export async function recordUsage(payload: {
  tenant_id: string;
  agent_id: string;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
}): Promise<ApiResponse<TokenLedger>> {
  return apiPost<TokenLedger>("/cost/usage", payload);
}

/** List usage records */
export async function listUsage(
  params: PaginationParams & { tenant_id?: string; agent_id?: string } = {},
): Promise<ApiResponse<TokenLedger[]>> {
  return apiGet<TokenLedger[]>("/cost/usage", params);
}

/** Get budgets */
export async function getBudgets(
  params: PaginationParams & { tenant_id?: string } = {},
): Promise<ApiResponse<Budget[]>> {
  return apiGet<Budget[]>("/cost/budgets", params);
}

/** Create a budget */
export async function createBudget(
  payload: Omit<Budget, "id" | "spent_amount" | "created_at" | "updated_at">,
): Promise<ApiResponse<Budget>> {
  return apiPost<Budget>("/cost/budgets", payload);
}

/** Update a budget */
export async function updateBudget(
  id: string,
  payload: Partial<Omit<Budget, "id" | "spent_amount" | "created_at" | "updated_at">>,
): Promise<ApiResponse<Budget>> {
  return apiPut<Budget>(`/cost/budgets/${id}`, payload);
}

/** Get cost report */
export async function getCostReport(params: {
  tenant_id?: string;
  period_start: string;
  period_end: string;
}): Promise<ApiResponse<CostReport>> {
  return apiGet<CostReport>("/cost/report", params);
}

/** Get cost forecast */
export async function getForecast(params: {
  tenant_id?: string;
  period_start: string;
  period_end: string;
}): Promise<ApiResponse<CostForecast>> {
  return apiPost<CostForecast>("/cost/forecast", params);
}

/** Delete a budget */
export async function deleteBudget(id: string): Promise<void> {
  return apiDelete(`/cost/budgets/${id}`);
}

/** List pricing */
export async function listPricing(
  params: PaginationParams & { provider?: string } = {},
): Promise<ApiResponse<unknown[]>> {
  return apiGet<unknown[]>("/cost/pricing", params);
}

/** List cost alerts */
export async function listAlerts(
  params: PaginationParams & { budget_id?: string } = {},
): Promise<ApiResponse<unknown[]>> {
  return apiGet<unknown[]>("/cost/alerts", params);
}

// ── Agent 11: Cost Engine v1 endpoints ─────────────────────────────

/** Record token usage (v1 authenticated) */
export async function recordUsageV1(payload: {
  provider: string;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  execution_id?: string;
  agent_id?: string;
  cost_usd?: number;
  metadata?: Record<string, unknown>;
}): Promise<ApiResponse<unknown>> {
  return apiPost<unknown>("/cost/api/v1/cost/record", payload);
}

/** Get cost summary (v1) */
export async function getCostSummary(params: {
  since?: string;
  until?: string;
  group_by?: string;
} = {}): Promise<ApiResponse<unknown>> {
  return apiGet<unknown>("/cost/api/v1/cost/summary", params);
}

/** Get cost breakdown by group (v1) */
export async function getCostBreakdown(params: {
  group_by?: string;
  since?: string;
  until?: string;
  limit?: number;
} = {}): Promise<ApiResponse<unknown>> {
  return apiGet<unknown>("/cost/api/v1/cost/breakdown", params);
}

/** Get time-series chart data (v1) */
export interface ChartPoint {
  date: string;
  [provider: string]: string | number;
}

export interface ChartData {
  granularity: string;
  providers: string[];
  series: ChartPoint[];
}

export async function getCostChart(params: {
  granularity?: string;
  since?: string;
  until?: string;
} = {}): Promise<ApiResponse<ChartData>> {
  return apiGet<ChartData>("/cost/api/v1/cost/chart", params);
}

/** Create budget via wizard (v1) */
export async function createBudgetV1(payload: {
  name: string;
  scope: string;
  scope_id?: string;
  limit_amount: number;
  period: string;
  enforcement: string;
  alert_thresholds?: number[];
}): Promise<ApiResponse<unknown>> {
  return apiPost<unknown>("/cost/api/v1/cost/budgets", payload);
}

/** List budgets with utilization (v1) */
export interface BudgetWithUtilization {
  id: string;
  name: string;
  scope: string;
  limit_amount: number;
  spent_amount: number;
  period: string;
  enforcement: string;
  alert_thresholds: number[];
  utilization_pct: number;
  utilization_color: string;
  remaining: number;
}

export async function listBudgetsV1(
  params: PaginationParams = {},
): Promise<ApiResponse<BudgetWithUtilization[]>> {
  return apiGet<BudgetWithUtilization[]>("/cost/api/v1/cost/budgets", params);
}

/** Get budget utilization (v1) */
export async function getBudgetUtilization(
  budgetId: string,
): Promise<ApiResponse<unknown>> {
  return apiGet<unknown>(`/cost/api/v1/cost/budgets/${budgetId}/utilization`);
}

/** Update budget (v1) */
export async function updateBudgetV1(
  budgetId: string,
  payload: Record<string, unknown>,
): Promise<ApiResponse<unknown>> {
  return apiPut<unknown>(`/cost/api/v1/cost/budgets/${budgetId}`, payload);
}

/** Export cost report (v1) */
export async function exportCostReport(params: {
  format?: string;
  since?: string;
  until?: string;
  group_by?: string;
}): Promise<Blob | ApiResponse<unknown>> {
  if (params.format === "csv") {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v != null) sp.set(k, String(v));
    }
    const res = await fetch(`/api/v1/cost/api/v1/cost/export?${sp.toString()}`, {
      credentials: "include",
    });
    if (!res.ok) throw new Error("Export failed");
    return res.blob();
  }
  return apiGet<unknown>("/cost/api/v1/cost/export", params);
}
