/**
 * WorkflowRunHistory
 *
 * Card-style alternate of the table view in ``RunHistoryPage`` — surfaces
 * ``paused`` and ``failed`` runs prominently and can be embedded inside
 * the workflow detail drawer.
 *
 * Backward-compatible signature: the ``runs`` prop accepts either the
 * canonical ``WorkflowRunSummary`` shape (Phase 7 / new types) OR the
 * legacy ``WorkflowRun`` shape from ``api/workflows.ts`` so existing
 * call-sites (e.g. ``WorkflowsPage``) continue to compile without changes.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Filter,
  Loader2,
  Pause,
  Play,
  XCircle,
} from "lucide-react";

import type {
  WorkflowRunSummary,
  RunStatus,
} from "@/types/workflow_run";

/**
 * Minimal subset both shapes satisfy. Anything heavier (e.g. step
 * inspection) lives on the dedicated ExecutionDetailPage.
 */
interface RunCardShape {
  id: string;
  status: string;
  trigger_type?: string | null;
  duration_ms: number | null;
  started_at: string | null;
  completed_at?: string | null;
  triggered_by?: string;
  workflow_id?: string | null;
  error_code?: string | null;
}

interface WorkflowRunHistoryProps {
  /**
   * Accepts either the new ``WorkflowRunSummary`` or the legacy
   * ``api/workflows.WorkflowRun``. Anything providing ``RunCardShape``
   * will render — additional fields are ignored.
   */
  runs: ReadonlyArray<RunCardShape | WorkflowRunSummary>;
  isLoading?: boolean;
  /** When supplied, the card click bubbles up before navigation. */
  onRunClick?: (run: RunCardShape) => void;
  /**
   * When ``true`` clicking a card navigates to ``/executions/{id}``.
   * Default: ``true``.
   */
  navigateOnClick?: boolean;
}

const STATUS_BADGE: Record<string, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  pending: { label: "Pending", cls: "bg-gray-500/20 text-gray-300", Icon: Clock },
  queued: { label: "Queued", cls: "bg-yellow-500/20 text-yellow-300", Icon: Clock },
  running: { label: "Running", cls: "bg-blue-500/20 text-blue-300", Icon: Loader2 },
  completed: { label: "Completed", cls: "bg-green-500/20 text-green-300", Icon: CheckCircle2 },
  failed: { label: "Failed", cls: "bg-red-500/20 text-red-300", Icon: XCircle },
  cancelled: { label: "Cancelled", cls: "bg-orange-500/20 text-orange-300", Icon: AlertCircle },
  paused: { label: "Paused", cls: "bg-purple-500/20 text-purple-300", Icon: Pause },
};

function StatusBadge({ status }: { status: string }) {
  const conf = STATUS_BADGE[status] ?? STATUS_BADGE.pending;
  if (!conf) return null;
  const { label, cls, Icon } = conf;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}
    >
      <Icon size={11} className={status === "running" ? "animate-spin" : ""} />
      {label}
    </span>
  );
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1_000)}s`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

const STATUSES: ReadonlyArray<{ key: "all" | RunStatus; label: string }> = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "paused", label: "Paused" },
  { key: "failed", label: "Failed" },
  { key: "completed", label: "Completed" },
  { key: "cancelled", label: "Cancelled" },
];

export function WorkflowRunHistory({
  runs,
  isLoading,
  onRunClick,
  navigateOnClick = true,
}: WorkflowRunHistoryProps) {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<"all" | RunStatus>("all");

  const counts = useMemo(() => {
    const c = { paused: 0, failed: 0, running: 0 };
    for (const r of runs) {
      if (r.status === "paused") c.paused += 1;
      else if (r.status === "failed") c.failed += 1;
      else if (r.status === "running") c.running += 1;
    }
    return c;
  }, [runs]);

  const filtered = useMemo(() => {
    if (statusFilter === "all") return runs;
    return runs.filter((r) => r.status === statusFilter);
  }, [runs, statusFilter]);

  function handleClick(run: RunCardShape) {
    onRunClick?.(run);
    if (navigateOnClick) {
      navigate(`/executions/${run.id}`);
    }
  }

  return (
    <div className="space-y-3" data-testid="workflow-run-history">
      {/* Top banner — paused / errors prominence */}
      {(counts.paused > 0 || counts.failed > 0) && (
        <div className="flex flex-wrap gap-2">
          {counts.paused > 0 && (
            <div
              data-testid="paused-banner"
              className="inline-flex items-center gap-2 rounded-md border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs text-purple-200"
            >
              <Pause size={12} /> {counts.paused} paused — awaiting input
            </div>
          )}
          {counts.failed > 0 && (
            <div
              data-testid="errors-banner"
              className="inline-flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-200"
            >
              <AlertCircle size={12} /> {counts.failed} failed
            </div>
          )}
          {counts.running > 0 && (
            <div className="inline-flex items-center gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-200">
              <Loader2 size={12} className="animate-spin" /> {counts.running}{" "}
              running
            </div>
          )}
        </div>
      )}

      {/* Filter chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <Filter size={12} className="text-gray-500" />
        {STATUSES.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setStatusFilter(s.key)}
            className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
              statusFilter === s.key
                ? "bg-purple-500/30 text-purple-100"
                : "bg-surface-base text-gray-400 hover:text-white"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Cards */}
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-gray-500" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed border-surface-border p-6 text-center text-xs text-gray-500">
          No runs match the current filter.
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {filtered.map((r) => (
            <li
              key={r.id}
              onClick={() => handleClick(r)}
              className="cursor-pointer rounded-lg border border-surface-border bg-surface-raised p-3 transition-colors hover:border-purple-500/40 hover:bg-white/5"
              data-testid="run-card"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-[11px] text-gray-300">
                  {r.id}
                </span>
                <StatusBadge status={r.status} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-gray-400">
                <div>
                  <div className="text-gray-500">Started</div>
                  <div>{fmtDate(r.started_at)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Duration</div>
                  <div>{fmtDuration(r.duration_ms)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Trigger</div>
                  <div className="capitalize flex items-center gap-1">
                    <Play size={10} /> {r.trigger_type ?? "manual"}
                  </div>
                </div>
                <div>
                  <div className="text-gray-500">Triggered by</div>
                  <div className="truncate">{r.triggered_by ?? "—"}</div>
                </div>
              </div>
              {r.error_code && (
                <div className="mt-2 truncate text-[10px] text-red-300">
                  error_code={r.error_code}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
