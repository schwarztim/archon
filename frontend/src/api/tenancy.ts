import type { ApiResponse } from "@/types";
import type { Tenant, TenantQuota, UsageMeteringRecord } from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** List tenants */
export async function listTenants(
  params: PaginationParams = {},
): Promise<ApiResponse<Tenant[]>> {
  return apiGet<Tenant[]>("/tenants", params);
}

/** Create a tenant */
export async function createTenant(payload: {
  name: string;
  slug: string;
  plan: string;
  settings?: Record<string, unknown>;
}): Promise<ApiResponse<Tenant>> {
  return apiPost<Tenant>("/tenants", payload);
}

/** Get a single tenant */
export async function getTenant(
  id: string,
): Promise<ApiResponse<Tenant>> {
  return apiGet<Tenant>(`/tenants/${id}`);
}

/** Update a tenant */
export async function updateTenant(
  id: string,
  payload: Partial<Omit<Tenant, "id" | "created_at" | "updated_at">>,
): Promise<ApiResponse<Tenant>> {
  return apiPut<Tenant>(`/tenants/${id}`, payload);
}

/** Get quotas for a tenant */
export async function getQuota(
  tenantId: string,
): Promise<ApiResponse<TenantQuota[]>> {
  return apiGet<TenantQuota[]>(`/tenants/${tenantId}/quota`);
}

/** Check if a tenant is within a specific resource limit */
export async function checkLimit(
  tenantId: string,
  resource: string,
): Promise<ApiResponse<{ allowed: boolean; remaining: number }>> {
  return apiPost<{ allowed: boolean; remaining: number }>(
    `/tenants/${tenantId}/check-limit`,
    { resource_type: resource, quantity: 1 },
  );
}

/** List usage records for a tenant */
export async function listUsage(
  tenantId: string,
  params: PaginationParams = {},
): Promise<ApiResponse<UsageMeteringRecord[]>> {
  return apiGet<UsageMeteringRecord[]>(`/tenants/${tenantId}/usage`, params);
}

/** Delete (deactivate) a tenant */
export async function deleteTenant(id: string): Promise<void> {
  return apiDelete(`/tenants/${id}`);
}
