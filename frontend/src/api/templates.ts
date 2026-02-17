import type { ApiResponse } from "@/types";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** Template definition returned by the API */
export interface Template {
  id: string;
  name: string;
  description: string | null;
  category: string;
  definition: Record<string, unknown>;
  tags: string[];
  is_featured: boolean;
  usage_count: number;
  author_id: string;
  created_at: string;
  updated_at: string;
}

/** Parameters for listing templates */
export interface ListTemplatesParams {
  limit?: number;
  offset?: number;
  category?: string;
  tag?: string;
  is_featured?: boolean;
  search?: string;
}

/** Fetch templates with optional filters */
export async function listTemplates(
  params: ListTemplatesParams = {},
): Promise<ApiResponse<Template[]>> {
  return apiGet<Template[]>("/templates/", params as PaginationParams);
}

/** Fetch a single template */
export async function getTemplate(
  id: string,
): Promise<ApiResponse<Template>> {
  return apiGet<Template>(`/templates/${id}`);
}

/** Create a template */
export async function createTemplate(
  payload: Omit<Template, "id" | "usage_count" | "created_at" | "updated_at">,
): Promise<ApiResponse<Template>> {
  return apiPost<Template>("/templates/", payload);
}

/** Update a template */
export async function updateTemplate(
  id: string,
  payload: Partial<Omit<Template, "id" | "created_at" | "updated_at">>,
): Promise<ApiResponse<Template>> {
  return apiPut<Template>(`/templates/${id}`, payload);
}

/** Delete a template */
export async function deleteTemplate(id: string): Promise<void> {
  return apiDelete(`/templates/${id}`);
}

/** Instantiate a template — creates a new Agent */
export async function instantiateTemplate(
  templateId: string,
  ownerId: string,
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>(
    `/templates/${templateId}/instantiate`,
    { owner_id: ownerId },
  );
}

/** Search templates */
export async function searchTemplates(
  q: string,
  semantic = false,
): Promise<ApiResponse<Template[]>> {
  return apiGet<Template[]>("/templates/search", { q, semantic } as PaginationParams);
}

/** List template categories */
export async function listCategories(): Promise<ApiResponse<string[]>> {
  return apiGet<string[]>("/templates/categories");
}
