import type { ApiResponse } from "@/types";
import type { Tenant, TenantQuota, UsageMeteringRecord } from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

// ── Tenant CRUD ────────────────────────────────────────────────────

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

// ── SSO Configuration ──────────────────────────────────────────────

export interface SSOConfig {
  id: string;
  name: string;
  protocol: string;
  enabled: boolean;
  is_default: boolean;
  [key: string]: unknown;
}

/** List SSO configurations for a tenant */
export async function listSSOConfigs(
  tenantId: string,
): Promise<ApiResponse<SSOConfig[]>> {
  return apiGet<SSOConfig[]>(`/tenants/${tenantId}/sso`);
}

/** Create an SSO configuration */
export async function createSSOConfig(
  tenantId: string,
  payload: Record<string, unknown>,
): Promise<ApiResponse<SSOConfig>> {
  return apiPost<SSOConfig>(`/tenants/${tenantId}/sso`, payload);
}

/** Update an SSO configuration */
export async function updateSSOConfig(
  tenantId: string,
  ssoId: string,
  payload: Record<string, unknown>,
): Promise<ApiResponse<SSOConfig>> {
  return apiPut<SSOConfig>(`/tenants/${tenantId}/sso/${ssoId}`, payload);
}

/** Delete an SSO configuration */
export async function deleteSSOConfig(
  tenantId: string,
  ssoId: string,
): Promise<void> {
  return apiDelete(`/tenants/${tenantId}/sso/${ssoId}`);
}

/** Test an SSO connection */
export async function testSSOConnection(
  tenantId: string,
  ssoId: string,
): Promise<ApiResponse<{ status: string; message: string }>> {
  return apiPost<{ status: string; message: string }>(
    `/tenants/${tenantId}/sso/${ssoId}/test`,
    {},
  );
}

// ── Tenant Members ─────────────────────────────────────────────────

export interface TenantMember {
  id: string;
  name: string;
  email: string;
  role: string;
  last_login: string | null;
  status: string;
  sso_provisioned: boolean;
}

/** List members of a tenant */
export async function listTenantMembers(
  tenantId: string,
  params: PaginationParams = {},
): Promise<ApiResponse<TenantMember[]>> {
  return apiGet<TenantMember[]>(`/tenants/${tenantId}/members`, params);
}

// ── RBAC ───────────────────────────────────────────────────────────

export interface RBACMatrix {
  resources: string[];
  actions: string[];
  roles: Record<string, {
    id?: string;
    permissions: Record<string, string[]>;
    is_builtin: boolean;
    description: string;
  }>;
}

/** Get RBAC permission matrix */
export async function getRBACMatrix(): Promise<ApiResponse<RBACMatrix>> {
  return apiGet<RBACMatrix>("/rbac/matrix");
}

/** Create a custom RBAC role */
export async function createCustomRole(payload: {
  name: string;
  description: string;
  permissions: Record<string, string[]>;
}): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>("/rbac/roles", payload);
}

/** Update a custom RBAC role */
export async function updateCustomRole(
  roleId: string,
  payload: Record<string, unknown>,
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPut<Record<string, unknown>>(`/rbac/roles/${roleId}`, payload);
}

/** Delete a custom RBAC role */
export async function deleteCustomRole(roleId: string): Promise<void> {
  return apiDelete(`/rbac/roles/${roleId}`);
}

// ── Impersonation ──────────────────────────────────────────────────

/** Start an impersonation session */
export async function impersonateUser(
  userId: string,
  reason: string = "",
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>(`/users/${userId}/impersonate`, { reason });
}
