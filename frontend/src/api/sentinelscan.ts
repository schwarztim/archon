import type { ApiResponse } from "@/types";
import type {
  DiscoveryScan,
  DiscoveredService,
  PostureReport,
} from "@/types/models";
import { apiGet, apiPost, type PaginationParams } from "./client";

/** Create a new discovery scan */
export async function createScan(payload: {
  name: string;
  target: string;
  scan_type: DiscoveryScan["scan_type"];
}): Promise<ApiResponse<DiscoveryScan>> {
  return apiPost<DiscoveryScan>("/sentinelscan/discovery", payload);
}

/** List scans */
export async function listScans(
  params: PaginationParams & { status?: DiscoveryScan["status"] } = {},
): Promise<ApiResponse<DiscoveryScan[]>> {
  return apiGet<DiscoveryScan[]>("/sentinelscan/discovery", params);
}

/** Get a single scan */
export async function getScan(
  scanId: string,
): Promise<ApiResponse<DiscoveryScan>> {
  return apiGet<DiscoveryScan>(`/sentinelscan/discovery/${scanId}`);
}

/** Run (execute) a scan */
export async function runScan(
  scanId: string,
): Promise<ApiResponse<DiscoveryScan>> {
  return apiPost<DiscoveryScan>(`/sentinelscan/discovery/${scanId}/run`, {});
}

/** List discovered services */
export async function listDiscoveredServices(
  scanId?: string,
  params: PaginationParams = {},
): Promise<ApiResponse<DiscoveredService[]>> {
  const queryParams = scanId ? { ...params, scan_id: scanId } : params;
  return apiGet<DiscoveredService[]>("/sentinelscan/inventory", queryParams);
}

/** Get posture report */
export async function getPostureReport(): Promise<ApiResponse<PostureReport>> {
  return apiGet<PostureReport>("/sentinelscan/posture");
}

/** List risk classifications */
export async function listRiskClassifications(
  params: PaginationParams = {},
): Promise<ApiResponse<unknown[]>> {
  return apiGet<unknown[]>("/sentinelscan/risk", params);
}

// ── Agent-14 Enhanced API Functions ────────────────────────────────

/** Service finding from discovery scan */
export interface ServiceFinding {
  id: string;
  service_name: string;
  service_type: "LLM" | "Embedding" | "Image" | "Voice" | "Code";
  provider: string;
  risk_level: "critical" | "high" | "medium" | "low";
  user_count: number;
  data_exposure: string;
  first_seen: string;
  last_seen: string;
  status: "Approved" | "Unapproved" | "Blocked" | "Monitoring" | "Ignored";
  detection_source: string;
  domain: string;
}

/** Scan result from enhanced discovery */
export interface ScanResult {
  id: string;
  tenant_id: string;
  sources: string[];
  scan_depth: string;
  status: string;
  findings: ServiceFinding[];
  summary: {
    total_findings: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
  started_at: string;
  completed_at: string;
}

/** Posture score result */
export interface PostureScoreResult {
  score: number;
  grade: string;
  color: "green" | "yellow" | "red";
  penalty: number;
  breakdown: {
    unauthorized: number;
    critical: number;
    data_exposure: number;
    policy_violations: number;
  };
  total_services: number;
  computed_at: string;
}

/** Risk breakdown category */
export interface RiskCategory {
  count: number;
  items: Array<{ id: string; service_name: string; detail: string }>;
}

/** Risk breakdown result */
export interface RiskBreakdownResult {
  categories: Record<string, RiskCategory>;
  total_findings: number;
  computed_at: string;
}

/** Remediation result */
export interface RemediationResult {
  finding_id: string;
  service_name: string;
  action: string;
  new_status: string;
  applied_by: string;
  applied_at: string;
  error?: string;
}

/** Bulk remediation result */
export interface BulkRemediationResult {
  action: string;
  total: number;
  succeeded: number;
  failed: number;
  results: RemediationResult[];
  applied_by: string;
  applied_at: string;
}

/** Scan history entry */
export interface ScanHistoryEntry {
  id: string;
  tenant_id: string;
  initiated_by: string;
  sources: string[];
  scan_depth: string;
  status: string;
  started_at: string;
  completed_at: string;
  findings_count: number;
  services_found: number;
}

/** Run a multi-source discovery scan */
export async function runDiscoveryScan(payload: {
  sources?: string[];
  scan_depth?: string;
}): Promise<ApiResponse<ScanResult>> {
  return apiPost<ScanResult>("/sentinelscan/scan", payload);
}

/** Get service inventory */
export async function getServiceInventory(
  params: PaginationParams & {
    risk_level?: string;
    status?: string;
    service_type?: string;
  } = {},
): Promise<ApiResponse<ServiceFinding[]>> {
  return apiGet<ServiceFinding[]>("/sentinelscan/services", params);
}

/** Get weighted posture score */
export async function getPostureScore(): Promise<ApiResponse<PostureScoreResult>> {
  return apiGet<PostureScoreResult>("/sentinelscan/posture");
}

/** Get risk breakdown by category */
export async function getRiskBreakdown(): Promise<ApiResponse<RiskBreakdownResult>> {
  return apiGet<RiskBreakdownResult>("/sentinelscan/risks");
}

/** Apply remediation to a single finding */
export async function remediateFinding(
  findingId: string,
  action: string,
): Promise<ApiResponse<RemediationResult>> {
  return apiPost<RemediationResult>(`/sentinelscan/remediate/${findingId}`, { action });
}

/** Apply bulk remediation */
export async function bulkRemediate(
  findingIds: string[],
  action: string,
): Promise<ApiResponse<BulkRemediationResult>> {
  return apiPost<BulkRemediationResult>("/sentinelscan/remediate/bulk", {
    finding_ids: findingIds,
    action,
  });
}

/** Get scan history */
export async function getScanHistory(
  params: PaginationParams = {},
): Promise<ApiResponse<ScanHistoryEntry[]>> {
  return apiGet<ScanHistoryEntry[]>("/sentinelscan/history", params);
}
