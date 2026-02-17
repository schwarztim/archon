import type { ApiResponse } from "@/types";
import type {
  Connector,
  ConnectionTestResult,
  ConnectorHealth,
} from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** Connector type schema from backend catalog */
export interface CredentialField {
  name: string;
  label: string;
  field_type: "text" | "password" | "select" | "number" | "checkbox" | "oauth";
  required: boolean;
  placeholder: string;
  default: string | null;
  options: string[];
  secret: boolean;
  description: string;
}

export interface ConnectorTypeSchema {
  name: string;
  label: string;
  category: string;
  icon: string;
  description: string;
  auth_methods: string[];
  credential_fields: CredentialField[];
  supports_oauth: boolean;
  supports_test: boolean;
}

/** List connectors */
export async function listConnectors(
  params: PaginationParams = {},
): Promise<ApiResponse<Connector[]>> {
  return apiGet<Connector[]>("/connectors/", params);
}

/** Get a single connector */
export async function getConnector(
  id: string,
): Promise<ApiResponse<Connector>> {
  return apiGet<Connector>(`/connectors/${id}`);
}

/** Create a connector */
export async function createConnector(payload: {
  name: string;
  type: string;
  config: Record<string, unknown>;
}): Promise<ApiResponse<Connector>> {
  return apiPost<Connector>("/connectors/", payload);
}

/** Update a connector */
export async function updateConnector(
  id: string,
  payload: Partial<{ name: string; type: string; config: Record<string, unknown>; status: string }>,
): Promise<ApiResponse<Connector>> {
  return apiPut<Connector>(`/connectors/${id}`, payload);
}

/** Delete a connector */
export async function deleteConnector(id: string): Promise<void> {
  return apiDelete(`/connectors/${id}`);
}

/** Test a connector's connection */
export async function testConnection(
  connectorId: string,
): Promise<ApiResponse<ConnectionTestResult>> {
  return apiPost<ConnectionTestResult>(`/connectors/${connectorId}/test-connection`, {});
}

/** Get connector health */
export async function getHealth(
  connectorId: string,
): Promise<ApiResponse<ConnectorHealth>> {
  return apiGet<ConnectorHealth>(`/connectors/${connectorId}/health`);
}

/** Get all connector type schemas (catalog) */
export async function listConnectorTypes(): Promise<ApiResponse<ConnectorTypeSchema[]>> {
  return apiGet<ConnectorTypeSchema[]>("/connectors/catalog/types");
}

/** Start OAuth authorize flow for a provider */
export async function oauthAuthorize(
  providerType: string,
  redirectUri: string,
): Promise<ApiResponse<{ authorization_url: string; state: string }>> {
  return apiGet<{ authorization_url: string; state: string }>(
    `/connectors/oauth/${providerType}/authorize`,
    { redirect_uri: redirectUri },
  );
}

/** Complete OAuth callback */
export async function oauthCallback(
  providerType: string,
  code: string,
  state: string,
): Promise<ApiResponse<{ token_type: string; vault_path: string }>> {
  return apiPost<{ token_type: string; vault_path: string }>(
    `/connectors/oauth/${providerType}/callback`,
    { code, state },
  );
}
