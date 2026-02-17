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
