import type { ApiResponse } from "@/types";
import { apiGet, apiPost, apiDelete, type PaginationParams } from "./client";

// ── Types ────────────────────────────────────────────────────────────

export interface Document {
  id: string;
  name: string;
  source: string;
  status: string;
  chunk_count?: number;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
}

export interface DocumentSearchResult {
  id: string;
  name: string;
  snippet: string;
  score: number;
  metadata?: Record<string, unknown>;
}

export interface Collection {
  id: string;
  name: string;
  description?: string;
  document_count?: number;
  created_at: string;
}

// ── API functions ────────────────────────────────────────────────────

/** POST /documents/ingest — upload/ingest a document */
export async function ingestDocument(payload: {
  name: string;
  content: string;
  collection_id?: string;
  metadata?: Record<string, unknown>;
}): Promise<ApiResponse<Document>> {
  return apiPost<Document>("/documents/ingest", payload);
}

/** POST /documents/search — search documents */
export async function searchDocuments(payload: {
  query: string;
  collection_id?: string;
  limit?: number;
}): Promise<ApiResponse<DocumentSearchResult[]>> {
  return apiPost<DocumentSearchResult[]>("/documents/search", payload);
}

/** GET /documents — list documents */
export async function listDocuments(
  params: PaginationParams = {},
): Promise<ApiResponse<Document[]>> {
  return apiGet<Document[]>("/documents", params);
}

/** GET /documents/{id} — get document */
export async function getDocument(id: string): Promise<ApiResponse<Document>> {
  return apiGet<Document>(`/documents/${id}`);
}

/** DELETE /documents/{id} — delete document */
export async function deleteDocument(id: string): Promise<void> {
  return apiDelete(`/documents/${id}`);
}

/** POST /documents/{id}/reprocess — reprocess document */
export async function reprocessDocument(id: string): Promise<ApiResponse<Document>> {
  return apiPost<Document>(`/documents/${id}/reprocess`, {});
}

/** GET /collections — list collections */
export async function listCollections(
  params: PaginationParams = {},
): Promise<ApiResponse<Collection[]>> {
  return apiGet<Collection[]>("/collections", params);
}

/** POST /collections — create collection */
export async function createCollection(payload: {
  name: string;
  description?: string;
}): Promise<ApiResponse<Collection>> {
  return apiPost<Collection>("/collections", payload);
}
