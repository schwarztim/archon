import type { ApiResponse } from "@/types";

const API_BASE = "/api/v1";

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<ApiResponse<T>> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }));
    throw error;
  }
  return res.json() as Promise<ApiResponse<T>>;
}

/** Param values accepted in query strings */
type QsValue = string | number | boolean | undefined | null;

/** Build a query-string from an object of params, ignoring nullish values */
function qs(params: Record<string, QsValue>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null) sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** Pagination params accepted by list endpoints */
export interface PaginationParams {
  limit?: number;
  offset?: number;
  [key: string]: QsValue;
}

/** GET request — returns full envelope */
export async function apiGet<T>(
  path: string,
  params?: PaginationParams,
): Promise<ApiResponse<T>> {
  return request<T>(`${path}${params ? qs(params) : ""}`);
}

/** POST request */
export async function apiPost<T>(
  path: string,
  body: unknown,
): Promise<ApiResponse<T>> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** PUT request */
export async function apiPut<T>(
  path: string,
  body: unknown,
): Promise<ApiResponse<T>> {
  return request<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** PATCH request */
export async function apiPatch<T>(
  path: string,
  body: unknown,
): Promise<ApiResponse<T>> {
  return request<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** DELETE request */
export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE", credentials: "include" });
  if (!res.ok) {
    const error = await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }));
    throw error;
  }
}
