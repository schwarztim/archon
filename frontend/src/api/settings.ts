import type { ApiResponse } from "@/types";
import { apiGet, apiPost, apiPut, apiDelete } from "./client";

// ── Types ────────────────────────────────────────────────────────────

export interface PlatformSettings {
  platform_name: string;
  default_language: string;
  timezone: string;
  version?: string;
  api_prefix?: string;
  [key: string]: unknown;
}

export interface FeatureFlag {
  name: string;
  description: string;
  enabled: boolean;
}

export interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  key?: string;
  scopes: string[];
  created_at: string;
}

export interface NotificationTestResult {
  success: boolean;
  message: string;
}

// ── API functions ────────────────────────────────────────────────────

/** GET /settings — platform settings */
export async function getSettings(): Promise<ApiResponse<PlatformSettings>> {
  return apiGet<PlatformSettings>("/settings");
}

/** PUT /settings — update platform settings */
export async function updateSettings(
  payload: Partial<PlatformSettings>,
): Promise<ApiResponse<PlatformSettings>> {
  return apiPut<PlatformSettings>("/settings", payload);
}

/** GET /settings/feature-flags */
export async function getFeatureFlags(): Promise<ApiResponse<FeatureFlag[]>> {
  return apiGet<FeatureFlag[]>("/settings/feature-flags");
}

/** PUT /settings/feature-flags/{flag_name} */
export async function toggleFeatureFlag(
  flagName: string,
  enabled: boolean,
): Promise<ApiResponse<FeatureFlag>> {
  return apiPut<FeatureFlag>(`/settings/feature-flags/${flagName}`, { enabled });
}

/** GET /settings/api-keys */
export async function listApiKeys(): Promise<ApiResponse<ApiKeyItem[]>> {
  return apiGet<ApiKeyItem[]>("/settings/api-keys");
}

/** POST /settings/api-keys */
export async function createApiKey(payload: {
  name: string;
  scopes: string[];
}): Promise<ApiResponse<ApiKeyItem>> {
  return apiPost<ApiKeyItem>("/settings/api-keys", payload);
}

/** DELETE /settings/api-keys/{key_id} */
export async function deleteApiKey(keyId: string): Promise<void> {
  return apiDelete(`/settings/api-keys/${keyId}`);
}

/** POST /settings/notifications/test */
export async function testNotification(payload: {
  channel: string;
  recipient?: string;
}): Promise<ApiResponse<NotificationTestResult>> {
  return apiPost<NotificationTestResult>("/settings/notifications/test", payload);
}
