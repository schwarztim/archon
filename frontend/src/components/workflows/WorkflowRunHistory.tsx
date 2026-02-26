import { useState } from "react";
import {
  Clock, Play, CheckCircle2, XCircle, Loader2,
  ChevronRight, Filter, Calendar, ArrowUpDown,
} from "lucide-react";
import type { WorkflowRun, WorkflowRunStep } from "@/api/workflows";

// ─── Helpers ─────────────────────────────────────────────────────────

function runStatusBadge(status: string) {
  const styles: Record<string, string> = {
    pending: "bg-yellow-500/20 text-yellow-400",
    running: "bg-blue-500/20 text-blue-400",
    completed: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
  };
  const icons: Record<string, React.ReactNode> = {
    pending: <Clock size={10} />,
    running: <Loader2 size={10} className="animate-spin" />,
    completed: <CheckCircle2 size={10} />,
    failed: <XCircle size={10} />,
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] ?? styles.pending}`}>
      {icons[status] ?? icons.pending}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

// ─── Step Timeline ───────────────────────────────────────────────────

function StepTimeline({ steps }: { steps: WorkflowRunStep[] }) {
  if (!steps || steps.length === 0) {
    return <p className="text-xs text-gray-500 py-2">No step data available</p>;
  }

  return (
    <div className="space-y-1 py-2">
      {steps.map((step, i) => (
        <div
          key={step.id}
          className="flex items-center gap-3 rounded-lg border border-surface-border bg-surface-overlay px-3 py-2"
        >
          <div className="flex items-center gap-1.5 min-w-[24px]">
            <span className="text-[10px] text-gray-600">{i + 1}</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-white truncate">{step.name}</span>
              {runStatusBadge(step.status)}
            </div>
            <div className="mt-0.5 flex items-center gap-3 text-[10px] text-gray-500">
              <span>Duration: {formatDuration(step.duration_ms)}</span>
              {step.agent_execution_id && (
                <span>Exec: {step.agent_execution_id.slice(0, 8)}…</span>
              )}
            </div>
          </div>
          {/* Expandable I/O */}
          <StepIO step={step} />
        </div>
      ))}
    </div>
  );
}

function StepIO({ step }: { step: WorkflowRunStep }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-gray-500 hover:text-white"
      >
        <ChevronRight size={12} className={`transform transition-transform ${expanded ? "rotate-90" : ""}`} />
      </button>
      {expanded && (
        <div className="absolute right-4 mt-1 z-10 w-80 rounded-lg border border-surface-border bg-surface-raised p-3 shadow-xl">
          <div className="mb-2">
            <p className="text-[10px] font-medium text-gray-400 mb-0.5">Input</p>
            <pre className="text-[9px] text-gray-500 bg-surface-overlay rounded p-1.5 max-h-24 overflow-auto">
              {JSON.stringify(step.input_data, null, 2)}
            </pre>
          </div>
          <div>
            <p className="text-[10px] font-medium text-gray-400 mb-0.5">Output</p>
            <pre className="text-[9px] text-gray-500 bg-surface-overlay rounded p-1.5 max-h-24 overflow-auto">
              {JSON.stringify(step.output_data, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Component ───────────────────────────────────────────────────────

interface WorkflowRunHistoryProps {
  runs: WorkflowRun[];
  isLoading?: boolean;
  onRunClick?: (run: WorkflowRun) => void;
}

export function WorkflowRunHistory({ runs, isLoading, onRunClick }: WorkflowRunHistoryProps) {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [triggerFilter, setTriggerFilter] = useState<string>("all");
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [sortField, setSortField] = useState<"started_at" | "duration_ms">("started_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Filter
  let filtered = [...runs];
  if (statusFilter !== "all") {
    filtered = filtered.filter((r) => r.status === statusFilter);
  }
  if (triggerFilter !== "all") {
    filtered = filtered.filter((r) => r.trigger_type === triggerFilter);
  }

  // Sort
  filtered.sort((a, b) => {
    let cmp = 0;
    if (sortField === "started_at") {
      cmp = new Date(a.started_at).getTime() - new Date(b.started_at).getTime();
    } else {
      cmp = (a.duration_ms ?? 0) - (b.duration_ms ?? 0);
    }
    return sortDir === "asc" ? cmp : -cmp;
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 size={20} className="animate-spin text-gray-500" />
      </div>
    );
  }

  return (
    <div>
      {/* Filters */}
      <div className="mb-3 flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <Filter size={12} className="text-gray-500" />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-surface-border bg-surface-raised px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
          >
            <option value="all">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <Play size={12} className="text-gray-500" />
          <select
            value={triggerFilter}
            onChange={(e) => setTriggerFilter(e.target.value)}
            className="rounded border border-surface-border bg-surface-raised px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
          >
            <option value="all">All Triggers</option>
            <option value="manual">Manual</option>
            <option value="schedule">Schedule</option>
            <option value="webhook">Webhook</option>
          </select>
        </div>
        <button
          onClick={() => {
            if (sortField === "started_at") {
              setSortDir(sortDir === "asc" ? "desc" : "asc");
            } else {
              setSortField("started_at");
              setSortDir("desc");
            }
          }}
          className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-white"
        >
          <ArrowUpDown size={10} />
          {sortField === "started_at" ? "Time" : "Duration"} {sortDir === "asc" ? "↑" : "↓"}
        </button>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 rounded-lg border border-surface-border bg-surface-raised">
          <Calendar size={24} className="mb-2 text-gray-600" />
          <p className="text-xs text-gray-500">No runs found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-surface-border bg-surface-raised">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs text-gray-500">
                <th className="px-3 py-2 font-medium">Run ID</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Trigger</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                <th className="px-3 py-2 font-medium">Started At</th>
                <th className="px-3 py-2 font-medium w-8" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((run) => (
                <>
                  <tr
                    key={run.id}
                    className="border-b border-surface-border hover:bg-white/5 cursor-pointer"
                    onClick={() => {
                      setExpandedRunId(expandedRunId === run.id ? null : run.id);
                      onRunClick?.(run);
                    }}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-gray-400">
                      {run.id.slice(0, 8)}…
                    </td>
                    <td className="px-3 py-2">{runStatusBadge(run.status)}</td>
                    <td className="px-3 py-2 text-xs text-gray-400 capitalize">
                      {run.trigger_type ?? "manual"}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-400">
                      {formatDuration(run.duration_ms)}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-400">
                      {formatDate(run.started_at)}
                    </td>
                    <td className="px-3 py-2">
                      <ChevronRight
                        size={12}
                        className={`text-gray-500 transform transition-transform ${expandedRunId === run.id ? "rotate-90" : ""}`}
                      />
                    </td>
                  </tr>
                  {expandedRunId === run.id && run.steps && (
                    <tr key={`${run.id}-steps`}>
                      <td colSpan={6} className="px-4 bg-surface-overlay">
                        <StepTimeline steps={run.steps} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
