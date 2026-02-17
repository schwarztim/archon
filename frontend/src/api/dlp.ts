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
  description?: string;
  icon?: string;
}

/** List built-in detector types */
export async function listDetectorTypes(): Promise<ApiResponse<DetectorType[]>> {
  return apiGet<DetectorType[]>("/api/v1/dlp/detectors");
}

// ── New endpoints for Agent 12 ──────────────────────────────────────

/** DLP Metrics response */
export interface DLPMetricsData {
  scans_today: number;
  detections: number;
  blocked: number;
  redacted: number;
  type_breakdown: Record<string, number>;
  trend: Array<{ date: string; detections: number }>;
}

/** Fetch DLP metrics */
export async function fetchMetrics(): Promise<ApiResponse<DLPMetricsData>> {
  return apiGet<DLPMetricsData>("/api/v1/dlp/metrics");
}

/** Detection list item */
export interface DLPDetectionItem {
  id: string;
  source: string;
  entity_types: string[];
  findings_count: number;
  action_taken: string;
  created_at: string;
  text_hash: string | null;
}

/** Fetch recent detections */
export async function fetchDetections(
  params: PaginationParams = {},
): Promise<ApiResponse<DLPDetectionItem[]>> {
  return apiGet<DLPDetectionItem[]>("/api/v1/dlp/detections", params);
}

/** Manual scan / policy test request */
export interface ManualScanPayload {
  content: string;
  policy_id?: string;
  detector_types?: string[];
  custom_patterns?: Record<string, string>;
}

/** Manual scan detection */
export interface ScanDetection {
  type: string;
  category: string;
  preview: string;
  position: [number, number];
  confidence: number;
  severity: string;
}

/** Manual scan result */
export interface ManualScanResult {
  detections: ScanDetection[];
  total_findings: number;
  risk_level: string;
  action: string;
  redacted_text: string;
  processing_time_ms: number;
}

/** Run manual policy test scan */
export async function manualScan(
  payload: ManualScanPayload,
): Promise<ApiResponse<ManualScanResult>> {
  return apiPost<ManualScanResult>("/api/v1/dlp/scan/test", payload);
}

/** Policy stats response */
export interface PolicyStats {
  policy_id: string;
  policy_name: string;
  total_scans: number;
  total_findings: number;
  action_breakdown: Record<string, number>;
  is_active: boolean;
}

/** Fetch policy detection stats */
export async function fetchPolicyStats(
  policyId: string,
): Promise<ApiResponse<PolicyStats>> {
  return apiGet<PolicyStats>(`/api/v1/dlp/policies/${policyId}/stats`);
}
