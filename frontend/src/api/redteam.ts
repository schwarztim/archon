import type { ApiResponse } from "@/types";
import type { RedTeamCampaign, RedTeamResult } from "@/types/models";
import { apiGet, apiPost, type PaginationParams } from "./client";

/** Run a red-team campaign */
export async function runCampaign(payload: {
  name: string;
  target_agent_id: string;
  attack_types: string[];
}): Promise<ApiResponse<RedTeamCampaign>> {
  return apiPost<RedTeamCampaign>("/redteam/campaigns", payload);
}

/** List campaigns */
export async function listCampaigns(
  params: PaginationParams = {},
): Promise<ApiResponse<RedTeamCampaign[]>> {
  return apiGet<RedTeamCampaign[]>("/redteam/campaigns", params);
}

/** Get results for a campaign */
export async function getCampaignResults(
  campaignId: string,
): Promise<ApiResponse<RedTeamResult>> {
  return apiGet<RedTeamResult>(`/redteam/campaigns/${campaignId}/results`);
}
