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
