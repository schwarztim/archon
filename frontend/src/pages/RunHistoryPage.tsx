/**
 * RunHistoryPage
 *
 * Phase 7 / WS14 — top-level run history view backed by the canonical
 * ``GET /api/v1/workflow-runs`` endpoint.
 *
 * Features
 *  - Status filter (queued/running/completed/failed/cancelled/paused)
 *  - Kind filter (workflow/agent)
 *  - Date range (since)
 *  - Cursor pagination (forward only — server returns ``next_cursor``)
 *  - Sortable columns: id, started_at, duration, status, tenant
 *  - Status badges with colour coding + spinner for running
 *  - Click row → ``/executions/{id}``
 *
 * Routing: register at ``/runs`` (see App.tsx — the route does not exist
 * yet; ExecutionsPage owns ``/executions``). When you wire it up:
 *   ``<Route path="runs" element={<RunHistoryPage />} />``
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Clock,
  Filter,
  History,
  Loader2,
  Pause,
  RefreshCcw,
  XCircle,
} from "lucide-react";

import { useRuns } from "@/hooks/useRuns";
import type {
  RunKind,
  RunStatus,
  WorkflowRunSummary,
} from "@/types/workflow_run";

type SortField = "id" | "started_at" | "duration" | "status" | "tenant";
type SortDir = "asc" | "desc";

const STATUS_OPTIONS: ReadonlyArray<{ value: "" | RunStatus; label: string }> = [
  { value: "", label: "Any status" },
  { value: "pending", label: "Pending" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "paused", label: "Paused" },
];

const KIND_OPTIONS: ReadonlyArray<{ value: "" | RunKind; label: string }> = [
  { value: "", label: "Any kind" },
  { value: "workflow", label: "Workflow" },
  { value: "agent", label: "Agent" },
];

const STATUS_BADGE: Record<string, { cls: string; Icon: typeof CheckCircle2 }> = {
  pending: { cls: "bg-gray-500/20 text-gray-300", Icon: Clock },
  queued: { cls: "bg-yellow-500/20 text-yellow-300", Icon: Clock },
  running: { cls: "bg-blue-500/20 text-blue-300", Icon: Loader2 },
  completed: { cls: "bg-green-500/20 text-green-300", Icon: CheckCircle2 },
  failed: { cls: "bg-red-500/20 text-red-300", Icon: XCircle },
  cancelled: { cls: "bg-orange-500/20 text-orange-300", Icon: AlertCircle },
  paused: { cls: "bg-purple-500/20 text-purple-300", Icon: Pause },
};

function StatusBadge({ status }: { status: string }) {
  const conf = STATUS_BADGE[status] ?? STATUS_BADGE.pending;
  if (!conf) return <span className="text-xs text-gray-400">{status}</span>;
  const { cls, Icon } = conf;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${cls}`}
    >
      <Icon size={11} className={status === "running" ? "animate-spin" : ""} />
      {status}
    </span>
  );
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1_000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1_000)}s`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

interface SortHeaderProps {
  field: SortField;
  current: SortField;
  dir: SortDir;
  onSort: (f: SortField) => void;
  children: React.ReactNode;
}

function SortHeader({ field, current, dir, onSort, children }: SortHeaderProps) {
  const active = field === current;
  return (
    <th
      scope="col"
      onClick={() => onSort(field)}
      className="cursor-pointer select-none px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-gray-500 hover:text-white"
      data-testid={`sort-${field}`}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {active &&
          (dir === "asc" ? (
            <ArrowUp size={10} />
          ) : (
            <ArrowDown size={10} />
          ))}
      </span>
    </th>
  );
}

interface FiltersState {
  status: "" | RunStatus;
  kind: "" | RunKind;
  since: string; // YYYY-MM-DDTHH:MM (datetime-local)
}

export function RunHistoryPage() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState<FiltersState>({
    status: "",
    kind: "",
    since: "",
  });
  const [sortField, setSortField] = useState<SortField>("started_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [cursor, setCursor] = useState<string | undefined>(undefined);

  const queryParams = useMemo(() => {
    const p: {
      status?: RunStatus;
      kind?: RunKind;
      since?: string;
      cursor?: string;
      limit?: number;
    } = { limit: 50 };
    if (filters.status) p.status = filters.status;
    if (filters.kind) p.kind = filters.kind;
    if (filters.since) {
      // datetime-local → ISO
      const d = new Date(filters.since);
      if (!Number.isNaN(d.getTime())) p.since = d.toISOString();
    }
    if (cursor) p.cursor = cursor;
    return p;
  }, [filters, cursor]);

  const { items, nextCursor, isLoading, isError, refetch } = useRuns(queryParams);

  const sorted = useMemo(() => {
    const copy: WorkflowRunSummary[] = [...items];
    copy.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "id":
          cmp = a.id.localeCompare(b.id);
          break;
        case "duration":
          cmp = (a.duration_ms ?? 0) - (b.duration_ms ?? 0);
          break;
        case "status":
          cmp = a.status.localeCompare(b.status);
          break;
        case "tenant":
          cmp = (a.tenant_id ?? "").localeCompare(b.tenant_id ?? "");
          break;
        case "started_at":
        default: {
          const sa = a.started_at ? new Date(a.started_at).getTime() : 0;
          const sb = b.started_at ? new Date(b.started_at).getTime() : 0;
          cmp = sa - sb;
          break;
        }
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [items, sortField, sortDir]);

  function toggleSort(f: SortField) {
    if (sortField === f) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(f);
      setSortDir(f === "started_at" ? "desc" : "asc");
    }
  }

  function applyFilter<K extends keyof FiltersState>(key: K, value: FiltersState[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setCursor(undefined);
  }

  return (
    <div className="p-6" data-testid="run-history-page">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-white">
            <History size={20} className="text-purple-400" /> Run History
          </h1>
          <p className="text-xs text-gray-500">
            All workflow and agent runs across tenants.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refetch()}
          className="inline-flex items-center gap-1 rounded-md border border-surface-border bg-surface-raised px-3 py-1.5 text-xs text-gray-300 hover:text-white"
          data-testid="refresh-runs"
        >
          <RefreshCcw size={12} className={isLoading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-surface-border bg-surface-raised p-3">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Filter size={12} /> Filters
        </div>
        <div>
          <label
            htmlFor="status-filter"
            className="block text-[10px] uppercase tracking-wide text-gray-500"
          >
            Status
          </label>
          <select
            id="status-filter"
            data-testid="status-filter"
            value={filters.status}
            onChange={(e) =>
              applyFilter("status", e.target.value as "" | RunStatus)
            }
            className="rounded border border-surface-border bg-surface-base px-2 py-1 text-xs text-white"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label
            htmlFor="kind-filter"
            className="block text-[10px] uppercase tracking-wide text-gray-500"
          >
            Kind
          </label>
          <select
            id="kind-filter"
            data-testid="kind-filter"
            value={filters.kind}
            onChange={(e) =>
              applyFilter("kind", e.target.value as "" | RunKind)
            }
            className="rounded border border-surface-border bg-surface-base px-2 py-1 text-xs text-white"
          >
            {KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label
            htmlFor="since-filter"
            className="block text-[10px] uppercase tracking-wide text-gray-500"
          >
            Since
          </label>
          <input
            id="since-filter"
            data-testid="since-filter"
            type="datetime-local"
            value={filters.since}
            onChange={(e) => applyFilter("since", e.target.value)}
            className="rounded border border-surface-border bg-surface-base px-2 py-1 text-xs text-white"
          />
        </div>
      </div>

      {/* Error */}
      {isError && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          Failed to load runs.
        </div>
      )}

      {/* Empty state */}
      {!isLoading && sorted.length === 0 && !isError && (
        <div
          data-testid="empty-state"
          className="rounded-lg border border-dashed border-surface-border p-12 text-center text-sm text-gray-500"
        >
          <History size={28} className="mx-auto mb-2 text-gray-600" />
          No runs match the current filters.
        </div>
      )}

      {/* Table */}
      {sorted.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-surface-border bg-surface-raised">
          <table className="w-full text-sm">
            <thead className="border-b border-surface-border bg-surface-base">
              <tr>
                <SortHeader
                  field="id"
                  current={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                >
                  Run ID
                </SortHeader>
                <SortHeader
                  field="status"
                  current={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                >
                  Status
                </SortHeader>
                <th
                  scope="col"
                  className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-gray-500"
                >
                  Kind
                </th>
                <SortHeader
                  field="started_at"
                  current={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                >
                  Started
                </SortHeader>
                <SortHeader
                  field="duration"
                  current={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                >
                  Duration
                </SortHeader>
                <SortHeader
                  field="tenant"
                  current={sortField}
                  dir={sortDir}
                  onSort={toggleSort}
                >
                  Tenant
                </SortHeader>
                <th
                  scope="col"
                  className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-gray-500"
                >
                  Trigger
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => navigate(`/executions/${r.id}`)}
                  data-testid="run-row"
                  className="cursor-pointer border-b border-surface-border last:border-b-0 hover:bg-white/5"
                >
                  <td className="px-3 py-2 font-mono text-[11px] text-gray-200">
                    {r.id}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-3 py-2 text-xs capitalize text-gray-400">
                    {r.kind}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-300">
                    {fmtDate(r.started_at)}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-300">
                    {fmtDuration(r.duration_ms)}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {r.tenant_id ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-xs capitalize text-gray-400">
                    {r.trigger_type}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      <div className="mt-4 flex items-center justify-between text-xs text-gray-400">
        <div>
          {sorted.length > 0 && (
            <span>
              Showing {sorted.length} run{sorted.length === 1 ? "" : "s"}
              {cursor && " (paginated)"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {cursor && (
            <button
              type="button"
              onClick={() => setCursor(undefined)}
              className="rounded border border-surface-border bg-surface-base px-3 py-1 text-xs text-gray-300 hover:text-white"
              data-testid="page-reset"
            >
              First page
            </button>
          )}
          <button
            type="button"
            onClick={() => nextCursor && setCursor(nextCursor)}
            disabled={!nextCursor}
            className="rounded border border-surface-border bg-surface-base px-3 py-1 text-xs text-gray-300 hover:text-white disabled:opacity-40"
            data-testid="page-next"
          >
            Next page →
          </button>
        </div>
      </div>
    </div>
  );
}

export default RunHistoryPage;
