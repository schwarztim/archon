import type { ApiResponse } from "@/types";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

// ── Types ────────────────────────────────────────────────────────────

export type SecretType = "api_key" | "oauth_token" | "password" | "certificate" | "custom";

export type RotationStatus =
  | "approaching"
  | "overdue"
  | "recently_rotated"
  | "never_rotated"
  | "ok";

export interface SecretMetadata {
  id: string;
  path: string;
  version: number;
  created_at: string;
  updated_at: string | null;
  expires_at: string | null;
  rotation_policy: string | null;
  secret_type: SecretType;
  last_rotated_at: string | null;
  rotation_policy_days: number | null;
  auto_rotate: boolean;
  notify_before_days: number;
}

export interface VaultStatus {
  mode: "connected" | "stub" | "sealed" | "disconnected";
  initialized: boolean;
  sealed: boolean;
  cluster_name: string;
  message: string;
}

export interface RotationDashboardItem {
  path: string;
  secret_type: SecretType;
  rotation_status: RotationStatus;
  last_rotated_at: string | null;
  next_rotation_at: string | null;
  days_until_rotation: number | null;
}

export interface SecretAccessEntry {
  id: string;
  secret_path: string;
  user_id: string | null;
  user_email: string;
  action: string;
  component: string;
  ip_address: string | null;
  details: string | null;
  created_at: string;
}

export interface RotationPolicyPayload {
  rotation_policy_days: number;
  auto_rotate: boolean;
  notify_before_days: number;
}

// ── API functions ────────────────────────────────────────────────────

/** List secrets with optional prefix filter */
export async function listSecrets(
  params: PaginationParams & { prefix?: string } = {},
): Promise<ApiResponse<SecretMetadata[]>> {
  return apiGet<SecretMetadata[]>("/secrets", params);
}

/** Get a single secret value */
export async function getSecret(
  id: string,
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiGet<Record<string, unknown>>(`/secrets/${encodeURIComponent(id)}`);
}

/** Create a new secret */
export async function createSecret(payload: {
  path: string;
  data: Record<string, unknown>;
  secret_type?: SecretType;
  rotation_policy_days?: number;
  auto_rotate?: boolean;
  notify_before_days?: number;
}): Promise<ApiResponse<SecretMetadata>> {
  return apiPost<SecretMetadata>("/secrets", payload);
}

/** Update a secret */
export async function updateSecret(
  id: string,
  payload: {
    data: Record<string, unknown>;
    rotation_policy_days?: number;
  },
): Promise<ApiResponse<SecretMetadata>> {
  return apiPut<SecretMetadata>(`/secrets/${encodeURIComponent(id)}`, payload);
}

/** Delete a secret */
export async function deleteSecret(id: string): Promise<void> {
  return apiDelete(`/secrets/${encodeURIComponent(id)}`);
}

/** Rotate a secret */
export async function rotateSecret(
  id: string,
  payload: { reason?: string; new_value?: Record<string, unknown> } = {},
): Promise<ApiResponse<SecretMetadata>> {
  return apiPost<SecretMetadata>(
    `/secrets/${encodeURIComponent(id)}/rotate`,
    payload,
  );
}

/** Get access log for a secret */
export async function getAccessLog(
  id: string,
  params: PaginationParams = {},
): Promise<ApiResponse<SecretAccessEntry[]>> {
  return apiGet<SecretAccessEntry[]>(
    `/secrets/${encodeURIComponent(id)}/access-log`,
    params,
  );
}

/** Get Vault connection status */
export async function getVaultStatus(): Promise<ApiResponse<VaultStatus>> {
  return apiGet<VaultStatus>("/secrets/status");
}

/** Get rotation dashboard */
export async function getRotationDashboard(): Promise<
  ApiResponse<RotationDashboardItem[]>
> {
  return apiGet<RotationDashboardItem[]>("/secrets/rotation-dashboard");
}

/** Set rotation policy for a secret */
export async function setRotationPolicy(
  id: string,
  payload: RotationPolicyPayload,
): Promise<ApiResponse<{ path: string; rotation_policy_days: number; auto_rotate: boolean; notify_before_days: number; next_rotation_at: string }>> {
  return apiPut(`/secrets/${encodeURIComponent(id)}/rotation-policy`, payload);
}
