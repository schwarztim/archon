import type { ApiResponse } from "@/types";
import type {
  EdgeDevice,
  EdgeModelDeployment,
  FleetStatus,
} from "@/types/models";
import { apiGet, apiPost, type PaginationParams } from "./client";

/** List edge devices */
export async function listDevices(
  params: PaginationParams = {},
): Promise<ApiResponse<EdgeDevice[]>> {
  return apiGet<EdgeDevice[]>("/edge/devices", params);
}

/** Register a new edge device */
export async function registerDevice(payload: {
  name: string;
  device_type: string;
  firmware_version: string;
  metadata?: Record<string, unknown>;
}): Promise<ApiResponse<EdgeDevice>> {
  return apiPost<EdgeDevice>("/edge/devices", payload);
}

/** Deploy a model to an edge device */
export async function deployModel(payload: {
  device_id: string;
  model_id: string;
  version: string;
}): Promise<ApiResponse<EdgeModelDeployment>> {
  return apiPost<EdgeModelDeployment>("/edge/models", payload);
}

/** Get fleet-wide status */
export async function getFleetStatus(): Promise<ApiResponse<FleetStatus>> {
  return apiGet<FleetStatus>("/edge/fleet/status");
}
