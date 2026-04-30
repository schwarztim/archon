import type { ApiResponse } from "@/types";
import type {
  TokenLedger,
  Budget,
  CostReport,
  CostForecast,
} from "@/types/models";
import type { CostSummary, RunCost } from "@/types/artifacts";
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
  return apiPost<unknown>("/cost/record", payload);
}

/** Get cost summary (v1) — typed against the backend ``CostSummary`` model.
 *
 * Backend route: ``GET /api/v1/cost/summary``. Returns the standard envelope
 * with the summary in ``data``. ``getCostSummary`` returns the unwrapped
 * summary for ergonomics; ``getCostSummaryEnvelope`` is preserved for
 * legacy callers that want the full envelope with meta.
 */
export async function getCostSummary(params: {
  tenant_id?: string;
  period?: string;
  since?: string;
  until?: string;
  group_by?: string;
} = {}): Promise<CostSummary> {
  // ``period`` and ``tenant_id`` are accepted by the WS14c contract but the
  // backend's /cost/summary route only honours ``since``/``until``/``group_by``.
  // We map ``period`` (e.g. "2025-04") to a calendar-month window so callers
  // don't have to reach into date math themselves.
  const qp: Record<string, string | undefined> = {};
  if (params.since) qp.since = params.since;
  if (params.until) qp.until = params.until;
  if (params.group_by) qp.group_by = params.group_by;
  if (params.period && !params.since && !params.until) {
    const m = params.period.match(/^(\d{4})-(\d{2})$/);
    if (m && m[1] && m[2]) {
      const year = Number(m[1]);
      const monthIdx = Number(m[2]) - 1;
      const start = new Date(Date.UTC(year, monthIdx, 1));
      const end = new Date(Date.UTC(year, monthIdx + 1, 1));
      qp.since = start.toISOString();
      qp.until = end.toISOString();
    }
  }
  const res = (await apiGet<CostSummary>(
    "/cost/summary",
    qp,
  )) as ApiResponse<CostSummary>;
  return res.data;
}

/** Per-run cost rollup. Aggregates ``/cost/usage?execution_id=...`` ledger
 * entries into a ``RunCost`` shape. The backend has no single ``/cost/runs/{id}``
 * route, so we synthesise the rollup client-side from the ledger surface that
 * already exists. */
export async function getRunCost(run_id: string): Promise<RunCost> {
  const res = (await apiGet<unknown>("/cost/usage", {
    execution_id: run_id,
    limit: 100,
  })) as ApiResponse<Array<Record<string, unknown>>>;
  const entries = Array.isArray(res.data) ? res.data : [];

  let total_cost = 0;
  let total_input_tokens = 0;
  let total_output_tokens = 0;
  const by_provider: Record<string, number> = {};
  const by_model: Record<string, number> = {};

  for (const e of entries) {
    const cost = Number(e.total_cost ?? e.cost_usd ?? 0);
    const inTok = Number(e.input_tokens ?? 0);
    const outTok = Number(e.output_tokens ?? 0);
    const provider = String(e.provider ?? "");
    const model = String(e.model_id ?? e.model ?? "");
    total_cost += cost;
    total_input_tokens += inTok;
    total_output_tokens += outTok;
    if (provider) {
      by_provider[provider] = (by_provider[provider] ?? 0) + cost;
    }
    if (model) {
      by_model[model] = (by_model[model] ?? 0) + cost;
    }
  }

  return {
    run_id,
    total_cost: Math.round(total_cost * 1e6) / 1e6,
    total_input_tokens,
    total_output_tokens,
    call_count: entries.length,
    by_provider,
    by_model,
  };
}

/** Get cost breakdown by group (v1) */
export async function getCostBreakdown(params: {
  group_by?: string;
  since?: string;
  until?: string;
  limit?: number;
} = {}): Promise<ApiResponse<unknown>> {
  return apiGet<unknown>("/cost/breakdown", params);
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
  return apiGet<ChartData>("/cost/chart", params);
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
  return apiPost<unknown>("/cost/budgets", payload);
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
  return apiGet<BudgetWithUtilization[]>("/cost/budgets", params);
}

/** Get budget utilization (v1) */
export async function getBudgetUtilization(
  budgetId: string,
): Promise<ApiResponse<unknown>> {
  return apiGet<unknown>(`/cost/budgets/${budgetId}/utilization`);
}

/** Update budget (v1) */
export async function updateBudgetV1(
  budgetId: string,
  payload: Record<string, unknown>,
): Promise<ApiResponse<unknown>> {
  return apiPut<unknown>(`/cost/budgets/${budgetId}`, payload);
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
    const res = await fetch(`/api/v1/cost/export?${sp.toString()}`, {
      credentials: "include",
    });
    if (!res.ok) throw new Error("Export failed");
    return res.blob();
  }
  return apiGet<unknown>("/cost/export", params);
}
