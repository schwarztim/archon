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

// ── Credential schemas ─────────────────────────────────────────────

export interface CredentialField {
  name: string;
  label: string;
  field_type: "password" | "text" | "url" | "select";
  required: boolean;
  placeholder: string;
  description: string;
}

export interface ProviderCredentialSchema {
  provider_type: string;
  label: string;
  fields: CredentialField[];
}

/** Get per-provider credential form schemas */
export async function getCredentialSchemas(): Promise<
  ApiResponse<Record<string, ProviderCredentialSchema>>
> {
  return apiGet<Record<string, ProviderCredentialSchema>>(
    "/router/providers/credential-schemas",
  );
}

/** Save provider credentials to Vault */
export async function saveProviderCredentials(
  providerId: string,
  credentials: Record<string, string>,
): Promise<ApiResponse<{ provider_id: string; vault_path: string; credentials_saved: boolean }>> {
  return apiPut<{ provider_id: string; vault_path: string; credentials_saved: boolean }>(
    `/router/providers/${providerId}/credentials`,
    { credentials },
  );
}

/** Delete a provider and clean up Vault secrets */
export async function deleteProvider(id: string): Promise<void> {
  return apiDelete(`/router/providers/${id}`);
}

// ── Test Connection ────────────────────────────────────────────────

export interface TestConnectionResult {
  success: boolean;
  latency_ms: number;
  models_found: number;
  message: string;
  error: string | null;
}

/** Test connection to a provider */
export async function testConnection(
  providerId: string,
): Promise<ApiResponse<TestConnectionResult>> {
  return apiPost<TestConnectionResult>(
    `/router/providers/${providerId}/test`,
    {},
  );
}

// ── Provider Health Detail ─────────────────────────────────────────

export interface ProviderHealthDetail {
  provider_id: string;
  provider_name: string;
  status: "healthy" | "degraded" | "unhealthy" | "circuit_open";
  metrics: {
    avg_latency_ms: number;
    p95_latency_ms: number;
    p99_latency_ms: number;
    error_rate_percent: number;
    requests_last_hour: number;
    total_tokens_last_hour: number;
    total_cost_last_hour: number;
  };
  circuit_breaker: {
    state: "closed" | "open" | "half_open";
    failure_count: number;
    threshold: number;
    last_failure_at: string | null;
  };
}

/** Get detailed health for a single provider */
export async function getProviderHealthDetail(
  providerId: string,
): Promise<ApiResponse<ProviderHealthDetail>> {
  return apiGet<ProviderHealthDetail>(
    `/router/providers/${providerId}/health`,
  );
}

/** Get detailed health for all tenant providers */
export async function getAllProviderHealthDetail(): Promise<
  ApiResponse<ProviderHealthDetail[]>
> {
  return apiGet<ProviderHealthDetail[]>("/router/providers/health/detail");
}

// ── Visual Routing Rules ───────────────────────────────────────────

export interface RoutingCondition {
  field: string;
  operator: string;
  value: string | number | string[];
}

export interface VisualRoutingRule {
  id: string | null;
  name: string;
  description: string | null;
  conditions: RoutingCondition[];
  target_model_id: string;
  priority: number;
  enabled: boolean;
}

export interface VisualRouteDecision {
  model_id: string;
  model_name: string;
  provider_id: string;
  provider_name: string;
  reason: string;
  alternatives: Array<{ model_name: string; reason: string }>;
}

/** Get visual routing rules */
export async function getVisualRules(): Promise<
  ApiResponse<VisualRoutingRule[]>
> {
  return apiGet<VisualRoutingRule[]>("/router/rules/visual");
}

/** Save visual routing rules (bulk) */
export async function saveVisualRules(
  rules: VisualRoutingRule[],
): Promise<ApiResponse<VisualRoutingRule[]>> {
  return apiPut<VisualRoutingRule[]>("/router/rules/visual", rules);
}

/** Route with visual rules and get explanation */
export async function routeVisual(payload: {
  capability?: string;
  sensitivity_level?: string;
  max_cost?: number;
  min_context?: number;
  tenant_tier?: string;
  preferred_model?: string | null;
}): Promise<ApiResponse<VisualRouteDecision>> {
  return apiPost<VisualRouteDecision>("/router/route/visual", payload);
}

// ── Fallback Chain ─────────────────────────────────────────────────

export interface FallbackChainConfig {
  model_ids: string[];
}

/** Get fallback chain configuration */
export async function getFallbackChain(): Promise<
  ApiResponse<FallbackChainConfig>
> {
  return apiGet<FallbackChainConfig>("/router/fallback");
}

/** Save fallback chain ordering */
export async function saveFallbackChain(
  config: FallbackChainConfig,
): Promise<ApiResponse<FallbackChainConfig>> {
  return apiPut<FallbackChainConfig>("/router/fallback", config);
}
