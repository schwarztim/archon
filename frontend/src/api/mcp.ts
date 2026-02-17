/**
 * MCP Interactive Components API client.
 *
 * Maps to backend routes at /api/v1/components/…
 */

import type { ApiResponse } from "@/types";
import { apiGet, apiPost, apiDelete, type PaginationParams } from "./client";

// ── Types ────────────────────────────────────────────────────────────

export type ComponentCategory =
  | "chart"
  | "form"
  | "table"
  | "approval"
  | "code_editor"
  | "map"
  | "timeline";

export interface MCPSession {
  session_id: string;
  user_id: string;
  tenant_id: string;
  component_type: ComponentCategory;
  permissions: string[];
  created_at: string;
  expires_at: string | null;
  status: string;
}

export interface RenderedComponent {
  session_id: string;
  html_content: string;
  scripts: string[];
  styles: string[];
  csp_nonce: string;
  data: Record<string, unknown>;
}

export interface ActionResult {
  success: boolean;
  data: Record<string, unknown>;
  error: string | null;
  next_render: RenderedComponent | null;
}

export interface ComponentTypeDefinition {
  id: string;
  name: string;
  category: ComponentCategory;
  schema: Record<string, unknown>;
  default_config: Record<string, unknown>;
  rbac_requirements: string[];
  tenant_id: string;
  created_by: string;
  created_at: string;
}

export interface MCPApp {
  id: string;
  name: string;
  description: string;
  category: ComponentCategory;
  icon?: string;
}

// ── Chat message types used by frontend ─────────────────────────────

export type MCPComponentType =
  | "data_table"
  | "chart"
  | "form"
  | "approval"
  | "code"
  | "markdown"
  | "image_gallery";

export interface MCPComponentPayload {
  type: MCPComponentType;
  props: Record<string, unknown>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  components?: MCPComponentPayload[];
  timestamp: string;
}

// ── Session Endpoints ───────────────────────────────────────────────

export async function createSession(
  componentType: ComponentCategory,
): Promise<ApiResponse<MCPSession>> {
  return apiPost<MCPSession>("/components/sessions", {
    component_type: componentType,
  });
}

export async function getSession(
  sessionId: string,
): Promise<ApiResponse<MCPSession>> {
  return apiGet<MCPSession>(`/components/sessions/${sessionId}`);
}

export async function closeSession(sessionId: string): Promise<void> {
  return apiDelete(`/components/sessions/${sessionId}`);
}

// ── Render Endpoint ─────────────────────────────────────────────────

export async function renderComponent(
  sessionId: string,
  config: {
    type: ComponentCategory;
    data_source?: string;
    filters?: Record<string, unknown>;
    display_options?: Record<string, unknown>;
  },
): Promise<ApiResponse<RenderedComponent>> {
  return apiPost<RenderedComponent>("/components/render", {
    session_id: sessionId,
    component_config: config,
  });
}

// ── Action Endpoint ─────────────────────────────────────────────────

export async function submitAction(
  sessionId: string,
  actionType: string,
  payload: Record<string, unknown> = {},
): Promise<ApiResponse<ActionResult>> {
  return apiPost<ActionResult>("/components/action", {
    session_id: sessionId,
    action_type: actionType,
    payload,
  });
}

// ── Component Type Endpoints ────────────────────────────────────────

export async function listComponentTypes(): Promise<
  ApiResponse<ComponentTypeDefinition[]>
> {
  return apiGet<ComponentTypeDefinition[]>("/components/types");
}

export async function registerComponentType(payload: {
  name: string;
  category: ComponentCategory;
  schema?: Record<string, unknown>;
  default_config?: Record<string, unknown>;
  rbac_requirements?: string[];
}): Promise<ApiResponse<ComponentTypeDefinition>> {
  return apiPost<ComponentTypeDefinition>("/components/types", payload);
}
