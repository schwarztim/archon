import type { ApiResponse } from "@/types";
import type {
  ModelRegistryEntry,
  RoutingRule,
  RouteResponse,
} from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** List registered models */
export async function listModels(
  params: PaginationParams = {},
): Promise<ApiResponse<ModelRegistryEntry[]>> {
  return apiGet<ModelRegistryEntry[]>("/router/models", params);
}

/** Get a single model */
export async function getModel(
  id: string,
): Promise<ApiResponse<ModelRegistryEntry>> {
  return apiGet<ModelRegistryEntry>(`/router/models/${id}`);
}

/** Register a new model */
export async function createModel(
  payload: Omit<ModelRegistryEntry, "id" | "created_at" | "updated_at">,
): Promise<ApiResponse<ModelRegistryEntry>> {
  return apiPost<ModelRegistryEntry>("/router/models", payload);
}

/** Update a model */
export async function updateModel(
  id: string,
  payload: Partial<Omit<ModelRegistryEntry, "id" | "created_at" | "updated_at">>,
): Promise<ApiResponse<ModelRegistryEntry>> {
  return apiPut<ModelRegistryEntry>(`/router/models/${id}`, payload);
}

/** Delete a model */
export async function deleteModel(id: string): Promise<void> {
  return apiDelete(`/router/models/${id}`);
}

/** List routing rules */
export async function listRoutingRules(
  params: PaginationParams = {},
): Promise<ApiResponse<RoutingRule[]>> {
  return apiGet<RoutingRule[]>("/router/rules", params);
}

/** Create a routing rule */
export async function createRoutingRule(
  payload: Omit<RoutingRule, "id" | "created_at" | "updated_at">,
): Promise<ApiResponse<RoutingRule>> {
  return apiPost<RoutingRule>("/router/rules", payload);
}

/** Update a routing rule */
export async function updateRoutingRule(
  id: string,
  payload: Partial<Omit<RoutingRule, "id" | "created_at" | "updated_at">>,
): Promise<ApiResponse<RoutingRule>> {
  return apiPut<RoutingRule>(`/router/rules/${id}`, payload);
}

/** Delete a routing rule */
export async function deleteRoutingRule(id: string): Promise<void> {
  return apiDelete(`/router/rules/${id}`);
}

/** Get a single routing rule */
export async function getRoutingRule(
  id: string,
): Promise<ApiResponse<RoutingRule>> {
  return apiGet<RoutingRule>(`/router/rules/${id}`);
}

/** Route a request to the best model */
export async function routeRequest(
  payload: { prompt: string; capabilities?: string[]; max_cost?: number },
): Promise<ApiResponse<RouteResponse>> {
  return apiPost<RouteResponse>("/router/route", payload);
}

// ── Provider endpoints ─────────────────────────────────────────────

export interface Provider {
  id: string;
  name: string;
  api_type: string;
  model_ids: string[];
  capabilities: string[];
  cost_per_1k_tokens: number;
  avg_latency_ms: number;
  data_classification_level: string;
  geo_residency: string;
  is_active: boolean;
}

export interface ProviderHealth {
  provider_id: string;
  name: string;
  status: string;
  latency_ms?: number;
}

/** List registered providers */
export async function listProviders(
  params: PaginationParams = {},
): Promise<ApiResponse<Provider[]>> {
  return apiGet<Provider[]>("/router/providers", params);
}

/** Register a new provider */
export async function createProvider(
  payload: Omit<Provider, "id">,
): Promise<ApiResponse<Provider>> {
  return apiPost<Provider>("/router/providers", payload);
}

/** Check provider health */
export async function getProviderHealth(): Promise<ApiResponse<ProviderHealth[]>> {
  return apiGet<ProviderHealth[]>("/router/providers/health");
}
