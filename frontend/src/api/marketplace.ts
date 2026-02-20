import type { ApiResponse } from "@/types";
import type { MarketplaceListing, MarketplaceReview } from "@/types/models";
import { apiGet, apiPost, type PaginationParams } from "./client";

/** Search marketplace listings */
export async function searchListings(
  params: PaginationParams & {
    search?: string;
    category?: string;
    tag?: string;
  } = {},
): Promise<ApiResponse<MarketplaceListing[]>> {
  return apiGet<MarketplaceListing[]>("/marketplace/listings", params);
}

/** Browse the public marketplace catalog with search and sorting */
export async function browseCatalog(
  params: PaginationParams & {
    query?: string;
    category?: string;
    sort?: string;
  } = {},
): Promise<ApiResponse<MarketplaceListing[]>> {
  return apiGet<MarketplaceListing[]>("/marketplace/catalog", params);
}

/** Get a single listing */
export async function getListing(
  id: string,
): Promise<ApiResponse<MarketplaceListing>> {
  return apiGet<MarketplaceListing>(`/marketplace/listings/${id}`);
}

/** Create (publish) a listing */
export async function createListing(
  payload: Omit<
    MarketplaceListing,
    "id" | "install_count" | "avg_rating" | "created_at" | "updated_at"
  >,
): Promise<ApiResponse<MarketplaceListing>> {
  return apiPost<MarketplaceListing>("/marketplace/listings", payload);
}

/** Install a listing by ID — creates an agent in the user's workspace */
export async function installListing(
  listingId: string,
  tenantId: string,
): Promise<ApiResponse<{ installation_id: string }>> {
  return apiPost<{ installation_id: string }>(
    `/marketplace/${listingId}/install`,
    { tenant_id: tenantId },
  );
}

/** Install a marketplace package by ID */
export async function installPackage(
  listingId: string,
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>(
    `/marketplace/${listingId}/install`,
    {},
  );
}

/** List reviews for a listing */
export async function listReviews(
  listingId: string,
  params: PaginationParams = {},
): Promise<ApiResponse<MarketplaceReview[]>> {
  return apiGet<MarketplaceReview[]>(
    `/marketplace/listings/${listingId}/reviews`,
    params,
  );
}

/** Create a review */
// TODO: Backend POST /reviews expects { listing_id, user_id, rating, comment } — field names differ from frontend payload
export async function createReview(
  listingId: string,
  payload: {
    rating: number;
    title: string;
    body: string;
  },
): Promise<ApiResponse<MarketplaceReview>> {
  return apiPost<MarketplaceReview>(
    `/marketplace/reviews`,
    { listing_id: listingId, ...payload },
  );
}
