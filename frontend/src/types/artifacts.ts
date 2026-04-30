/**
 * Artifact + cost types for the WS14c Frontend Visibility surface.
 *
 * Backend pairing:
 *   - Artifact rows are produced by ``backend/app/services/artifact_service.py``
 *     and surfaced by ``backend/app/routes/artifacts.py``. The REST envelope
 *     uses ``metadata`` (the JSON column is named ``meta`` on the model
 *     internally — the route translates).
 *   - Cost summary types mirror ``backend/app/models/cost.py::CostSummary``
 *     and the ``GET /cost/summary`` envelope.
 */

/** Artifact metadata — matches the REST surface in ``artifacts.py``. */
export interface Artifact {
  id: string;
  run_id: string | null;
  step_id: string | null;
  tenant_id: string | null;
  content_type: string;
  content_hash: string;
  size_bytes: number;
  storage_backend: string;
  /** Filled in by the service after the bytes land. May be empty for very fresh rows. */
  storage_uri?: string;
  retention_days: number | null;
  /** ISO-8601 timestamp; ``null`` when the artifact has no expiry. */
  expires_at: string | null;
  /** ISO-8601 timestamp. */
  created_at: string;
  metadata: Record<string, unknown>;
}

/** Inline shim for large step outputs persisted as artifacts. */
export interface ArtifactRef {
  id: string;
  size_bytes: number;
  content_type: string;
  content_hash: string;
}

/** Cursor-paginated artifact listing response (data unwrapped). */
export interface ArtifactListResult {
  items: Artifact[];
  next_cursor: string | null;
}

/** Filter options accepted by ``listArtifacts``. */
export interface ListArtifactsOptions {
  run_id?: string;
  /** Admin-only — non-admins always have their own tenant forced server-side. */
  tenant_id?: string;
  /** Client-side filter applied after fetch (the backend has no native param). */
  content_type?: string;
  limit?: number;
  cursor?: string;
}

// ── Cost types ───────────────────────────────────────────────────────

/** Cost summary buckets — mirrors backend ``CostSummary``. */
export interface CostSummary {
  total_cost: number;
  total_input_tokens: number;
  total_output_tokens: number;
  call_count: number;
  by_provider: Record<string, number>;
  by_model: Record<string, number>;
  by_department: Record<string, number>;
  by_user: Record<string, number>;
  period: {
    since?: string;
    until?: string;
  };
}

/** Per-run cost rollup — used by ExecutionDetailPage and the dashboard's top-runs. */
export interface RunCost {
  run_id: string;
  total_cost: number;
  total_input_tokens: number;
  total_output_tokens: number;
  call_count: number;
  by_provider: Record<string, number>;
  by_model: Record<string, number>;
}

/** Routing decision recorded on a step's output (see node_executors). */
export interface RoutingDecision {
  model: string;
  provider: string;
  reason?: string;
  /** Optional: the alternatives the router considered. */
  candidates?: string[];
}

/** Step cost slice attached to ``StepData.output.cost`` when present. */
export interface StepCost {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  provider?: string;
  model?: string;
}
