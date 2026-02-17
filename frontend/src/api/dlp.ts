import type { ApiResponse } from "@/types";
import type { DLPPolicy, DLPScanResult } from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** Scan text for sensitive entities */
export async function scanText(payload: {
  text: string;
  policy_ids?: string[];
}): Promise<ApiResponse<DLPScanResult>> {
  return apiPost<DLPScanResult>("/api/v1/dlp/scan", payload);
}

/** Redact sensitive entities from text */
export async function redactText(payload: {
  text: string;
  policy_ids?: string[];
}): Promise<ApiResponse<{ clean_text: string; entities_redacted: number }>> {
  return apiPost<{ clean_text: string; entities_redacted: number }>(
    "/api/v1/dlp/redact",
    payload,
  );
}

/** List DLP policies */
export async function listPolicies(
  params: PaginationParams = {},
): Promise<ApiResponse<DLPPolicy[]>> {
  return apiGet<DLPPolicy[]>("/api/v1/dlp/policies", params);
}

/** Create a DLP policy */
export async function createPolicy(
  payload: Omit<DLPPolicy, "id" | "created_at" | "updated_at">,
): Promise<ApiResponse<DLPPolicy>> {
  return apiPost<DLPPolicy>("/api/v1/dlp/policies", payload);
}

/** Update a DLP policy */
export async function updatePolicy(
  id: string,
  payload: Partial<Omit<DLPPolicy, "id" | "created_at" | "updated_at">>,
): Promise<ApiResponse<DLPPolicy>> {
  return apiPut<DLPPolicy>(`/api/v1/dlp/policies/${id}`, payload);
}

/** Delete a DLP policy */
export async function deletePolicy(id: string): Promise<void> {
  return apiDelete(`/api/v1/dlp/policies/${id}`);
}

/** Check guardrails */
export async function checkGuardrails(payload: {
  content: string;
  direction: string;
}): Promise<ApiResponse<unknown>> {
  return apiPost<unknown>("/api/v1/dlp/guardrails", payload);
}

/** Detector type definition */
export interface DetectorType {
  id: string;
  name: string;
  category: string;
  sensitivity: string;
}

/** List built-in detector types */
export async function listDetectorTypes(): Promise<ApiResponse<DetectorType[]>> {
  return apiGet<DetectorType[]>("/api/v1/dlp/detectors");
}
