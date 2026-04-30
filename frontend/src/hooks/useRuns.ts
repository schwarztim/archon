/**
 * useRuns / useRun
 *
 * TanStack Query hooks for the canonical run API (Phase 7 / WS14).
 *
 * - ``useRuns(params)`` — list runs (paginated, cursor-based) with auto
 *   polling every ``RUNNING_POLL_MS`` whenever the latest page contains a
 *   non-terminal status.
 * - ``useRun(id)`` — fetch a single run; polls every ``RUNNING_POLL_MS``
 *   while the run is in ``pending`` / ``queued`` / ``running`` / ``paused``.
 * - ``useCancelRun()`` — POST ``/api/v1/executions/{id}/cancel``.
 *
 * All keys are namespaced under ``["runs", ...]`` so other parts of the
 * app can ``invalidateQueries({ queryKey: ["runs"] })`` to force a refresh.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  cancelRun,
  getRun,
  listRuns,
  type ListRunsParams,
} from "@/api/runs";
import type {
  RunStatus,
  WorkflowRun,
  WorkflowRunListResponse,
  WorkflowRunSummary,
} from "@/types/workflow_run";

const RUNNING_POLL_MS = 5_000;

const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

/** Returns ``true`` when a run summary or full run is still progressing. */
export function isRunActive(
  status: RunStatus | string | null | undefined,
): boolean {
  if (!status) return false;
  return !TERMINAL_STATUSES.has(status as RunStatus);
}

/** Returns ``true`` if any run on the page is not in a terminal state. */
function pageHasActiveRun(items: readonly WorkflowRunSummary[]): boolean {
  return items.some((r) => isRunActive(r.status));
}

// ── List ────────────────────────────────────────────────────────────────

export interface UseRunsResult {
  data: WorkflowRunListResponse | undefined;
  items: WorkflowRunSummary[];
  nextCursor: string | null;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => Promise<unknown>;
}

/**
 * List runs (paginated). Polls every 5 s while at least one run on the
 * current page is still active.
 *
 * The query key includes the full ``params`` object so toggling filters
 * triggers a fresh fetch.
 */
export function useRuns(params: ListRunsParams = {}): UseRunsResult {
  const query: UseQueryResult<WorkflowRunListResponse> = useQuery({
    queryKey: ["runs", "list", params],
    queryFn: () => listRuns(params),
    refetchInterval: (q) => {
      const data = q.state.data as WorkflowRunListResponse | undefined;
      if (!data || !data.items) return false;
      return pageHasActiveRun(data.items) ? RUNNING_POLL_MS : false;
    },
    placeholderData: (prev) => prev,
  });

  return {
    data: query.data,
    items: query.data?.items ?? [],
    nextCursor: query.data?.next_cursor ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  };
}

// ── Single ──────────────────────────────────────────────────────────────

export interface UseRunResult {
  run: WorkflowRun | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => Promise<unknown>;
}

export function useRun(
  id: string | null | undefined,
  opts?: { canonical?: boolean },
): UseRunResult {
  const query: UseQueryResult<WorkflowRun> = useQuery({
    queryKey: ["runs", "single", id, opts?.canonical ?? true],
    queryFn: () => getRun(id as string, opts),
    enabled: Boolean(id),
    refetchInterval: (q) => {
      const data = q.state.data as WorkflowRun | undefined;
      if (!data) return false;
      return isRunActive(data.status) ? RUNNING_POLL_MS : false;
    },
  });

  return {
    run: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  };
}

// ── Cancel ──────────────────────────────────────────────────────────────

/** Invalidates the matching ``["runs", ...]`` keys on success. */
export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => cancelRun(runId),
    onSuccess: (_data, runId) => {
      void qc.invalidateQueries({ queryKey: ["runs", "single", runId] });
      void qc.invalidateQueries({ queryKey: ["runs", "list"] });
    },
  });
}
