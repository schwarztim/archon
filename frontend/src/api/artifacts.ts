/**
 * Frontend client for the artifacts REST surface.
 *
 * Backend routes (``backend/app/routes/artifacts.py``):
 *   - GET    /api/v1/artifacts                  list (cursor-paginated)
 *   - GET    /api/v1/artifacts/{id}             metadata only
 *   - GET    /api/v1/artifacts/{id}/content     binary stream
 *   - DELETE /api/v1/artifacts/{id}             tenant-scoped delete
 *
 * Cross-tenant requests get a 404 (not 403) so we don't leak existence.
 * All error responses surface as thrown ``ApiError`` envelopes via ``apiGet``.
 */

import { apiGet, apiDelete } from "./client";
import type {
  Artifact,
  ArtifactListResult,
  ListArtifactsOptions,
} from "@/types/artifacts";
import type { ApiResponse } from "@/types";

const API_BASE = "/api/v1";

// ── List ─────────────────────────────────────────────────────────────

interface ListEnvelopeMeta {
  request_id: string;
  timestamp: string;
  count?: number;
  next_cursor?: string | null;
  pagination?: {
    total: number;
    limit: number;
    offset: number;
  };
}

interface ListEnvelope {
  data: Artifact[];
  meta: ListEnvelopeMeta;
}

/** Cursor-paginated listing.
 *
 * ``content_type`` is filtered client-side because the backend has no
 * matching query param. The cursor + limit still flow through to the
 * server so pagination remains stable.
 */
export async function listArtifacts(
  opts: ListArtifactsOptions = {},
): Promise<ArtifactListResult> {
  const params: Record<string, string | number | undefined> = {};
  if (opts.run_id) params.run_id = opts.run_id;
  if (opts.tenant_id) params.tenant_id = opts.tenant_id;
  if (opts.limit) params.limit = opts.limit;
  if (opts.cursor) params.cursor = opts.cursor;

  const res = (await apiGet<Artifact[]>(
    "/artifacts",
    params,
  )) as unknown as ListEnvelope;

  let items = Array.isArray(res.data) ? res.data : [];
  if (opts.content_type) {
    const needle = opts.content_type.toLowerCase();
    items = items.filter((a) =>
      (a.content_type || "").toLowerCase().includes(needle),
    );
  }

  return {
    items,
    next_cursor: res.meta?.next_cursor ?? null,
  };
}

// ── Get metadata ─────────────────────────────────────────────────────

/** Fetch artifact metadata. Throws on 404 (cross-tenant or missing). */
export async function getArtifact(id: string): Promise<Artifact> {
  const res = (await apiGet<Artifact>(
    `/artifacts/${encodeURIComponent(id)}`,
  )) as ApiResponse<Artifact>;
  return res.data;
}

// ── Get content ──────────────────────────────────────────────────────

/** Fetch artifact bytes. Returns a string for text/json content types,
 *  a Blob for everything else. Caller is responsible for revoking blob
 *  URLs they create. Throws on 404. */
export async function getArtifactContent(
  id: string,
): Promise<Blob | string> {
  const res = await fetch(
    `${API_BASE}/artifacts/${encodeURIComponent(id)}/content`,
    { credentials: "include" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }));
    throw err;
  }
  const ct = (res.headers.get("Content-Type") || "").toLowerCase();
  if (ct.startsWith("text/") || ct.includes("json")) {
    return res.text();
  }
  return res.blob();
}

// ── Delete ───────────────────────────────────────────────────────────

/** Tenant-scoped delete. Returns ``{ deleted: true }`` on success. */
export async function deleteArtifact(
  id: string,
): Promise<{ deleted: boolean }> {
  // The backend returns ``{ data: { id, deleted: true }, meta: {...} }``;
  // the shared ``apiDelete`` helper currently discards the body, so we
  // duplicate the fetch locally to surface the structured response.
  const res = await fetch(
    `${API_BASE}/artifacts/${encodeURIComponent(id)}`,
    { method: "DELETE", credentials: "include" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }));
    throw err;
  }
  // 204-no-content is also valid — fall back to a synthesised success.
  if (res.status === 204) return { deleted: true };
  const body = (await res.json().catch(() => ({
    data: { deleted: true },
  }))) as { data?: { deleted?: boolean } };
  return { deleted: body.data?.deleted ?? true };
}

// Re-export ``apiDelete`` only to silence unused-import linting if a
// caller imports it through this barrel later.
export { apiDelete };
