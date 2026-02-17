import type { ApiResponse } from "@/types";
import type {
  Connector,
  ConnectionTestResult,
  ConnectorHealth,
} from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

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

/** Test a connector (local validation — no backend endpoint) */
export async function testConnection(
  connectorId: string,
): Promise<ApiResponse<ConnectionTestResult>> {
  return apiGet<ConnectionTestResult>(`/connectors/${connectorId}`);
}

/** Get connector health (returns connector details) */
export async function getHealth(
  connectorId: string,
): Promise<ApiResponse<ConnectorHealth>> {
  return apiGet<ConnectorHealth>(`/connectors/${connectorId}`);
}
