import type { ApiResponse } from "@/types";
import type { MeshNode, TrustRelationship, MeshMessage } from "@/types/models";
import { apiGet, apiPost, type PaginationParams } from "./client";

/** List peer nodes */
export async function listPeers(
  params: PaginationParams = {},
): Promise<ApiResponse<MeshNode[]>> {
  return apiGet<MeshNode[]>("/mesh/nodes", params);
}

/** Register this node in the mesh */
export async function registerNode(payload: {
  name: string;
  endpoint: string;
  region: string;
  capabilities: string[];
}): Promise<ApiResponse<MeshNode>> {
  return apiPost<MeshNode>("/mesh/nodes", payload);
}

/** Establish a trust relationship between nodes */
export async function establishTrust(payload: {
  source_node_id: string;
  target_node_id: string;
  trust_level: TrustRelationship["trust_level"];
  expires_at?: string;
}): Promise<ApiResponse<TrustRelationship>> {
  return apiPost<TrustRelationship>("/mesh/trust", payload);
}

/** Send a message to another node */
export async function sendMessage(payload: {
  target_node_id: string;
  payload: Record<string, unknown>;
}): Promise<ApiResponse<MeshMessage>> {
  return apiPost<MeshMessage>("/mesh/messages", payload);
}
