import { useState, useCallback } from "react";
import {
  ScrollText,
  Search,
  Download,
  ShieldOff,
  Calendar,
  Filter,
  X,
} from "lucide-react";
import { useAuth } from "@/providers/auth-provider";
import { apiGet } from "@/api/client";
import { useApiQuery } from "@/hooks/useApi";

// ─── Types ───────────────────────────────────────────────────────────

interface AuditEntry {
  id: string;
  actor: string;
  actor_email: string;
  action: string;
  resource_type: string;
  resource_id: string;
  result: "success" | "failure" | "denied";
  timestamp: string;
  details: Record<string, unknown> | null;
  ip_address: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────

const RESULT_COLORS: Record<string, string> = {
  success: "bg-green-500/20 text-green-400",
  failure: "bg-red-500/20 text-red-400",
  denied: "bg-yellow-500/20 text-yellow-400",
};

function resultBadge(result: string) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${RESULT_COLORS[result] ?? "bg-gray-500/20 text-gray-400"}`}
    >
      {result}
    </span>
  );
}

function formatAction(action: string): string {
  return action.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function toISODateStr(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function exportToCsv(entries: AuditEntry[]) {
  const headers = ["Timestamp", "Actor", "Email", "Action", "Resource Type", "Resource ID", "Result", "IP Address"];
  const rows = entries.map((e) => [
    e.timestamp,
    e.actor,
    e.actor_email,
    e.action,
    e.resource_type,
    e.resource_id,
    e.result,
    e.ip_address,
  ]);
  const csv = [headers.join(","), ...rows.map((r) => r.map((v) => `"${v}"`).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `audit-log-${toISODateStr(new Date())}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Component ───────────────────────────────────────────────────────

export function AuditLogPage() {
  const { hasRole } = useAuth();
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState<string>("all");
  const [resultFilter, setResultFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(0);
  const limit = 30;

  // ── RBAC gate — admin or auditor ───────────────────────────────────
  if (!hasRole("admin") && !hasRole("auditor")) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2">
        <ShieldOff size={32} className="text-red-400" />
        <p className="text-red-400">Admin or Auditor access required</p>
      </div>
    );
  }

  // ── Data fetching ──────────────────────────────────────────────────
  const params: Record<string, string | number> = { limit, offset: page * limit };
  if (search) params.search = search;
  if (actionFilter !== "all") params.action = actionFilter;
  if (resultFilter !== "all") params.result = resultFilter;
  if (dateFrom) params.from = dateFrom;
  if (dateTo) params.to = dateTo;

  const { data, isLoading, error } = useApiQuery<AuditEntry[]>(
    ["audit-log", params],
    () => apiGet<AuditEntry[]>("/admin/audit-log", params),
  );

  const entries = data?.data ?? [];
  const total = data?.meta?.pagination?.total ?? entries.length;

  // ── Distinct actions for filter dropdown ───────────────────────────
  const distinctActions = Array.from(new Set(entries.map((e) => e.action)));

  // ── Loading / Error ────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading audit log...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          Failed to load audit log.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ScrollText size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Audit Log</h1>
        </div>
        <button
          onClick={() => exportToCsv(entries)}
          disabled={entries.length === 0}
          className="flex items-center gap-2 rounded-lg border border-[#2a2d37] px-4 py-2 text-sm text-gray-300 hover:bg-white/5 disabled:opacity-40"
        >
          <Download size={16} />
          Export CSV
        </button>
      </div>

      {/* Search & Filter Toggle */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search by actor, action, or resource..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-2 pl-9 pr-3 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none"
          />
        </div>
        <button
          onClick={() => setShowFilters((v) => !v)}
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
            showFilters
              ? "border-purple-500 text-purple-400"
              : "border-[#2a2d37] text-gray-400 hover:bg-white/5"
          }`}
        >
          <Filter size={16} />
          Filters
        </button>
      </div>

      {/* Expanded Filters */}
      {showFilters && (
        <div className="mb-4 grid grid-cols-1 gap-3 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-xs text-gray-400">Action</label>
            <select
              value={actionFilter}
              onChange={(e) => { setActionFilter(e.target.value); setPage(0); }}
              className="w-full rounded-lg border border-[#2a2d37] bg-[#12141e] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">All Actions</option>
              {distinctActions.map((a) => (
                <option key={a} value={a}>
                  {formatAction(a)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Result</label>
            <select
              value={resultFilter}
              onChange={(e) => { setResultFilter(e.target.value); setPage(0); }}
              className="w-full rounded-lg border border-[#2a2d37] bg-[#12141e] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">All Results</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
              <option value="denied">Denied</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">From Date</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setPage(0); }}
              className="w-full rounded-lg border border-[#2a2d37] bg-[#12141e] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">To Date</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setPage(0); }}
              className="w-full rounded-lg border border-[#2a2d37] bg-[#12141e] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            />
          </div>
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="overflow-x-auto">
          {entries.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <ScrollText size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No audit log entries found.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Timestamp</th>
                  <th className="px-4 py-2 font-medium">Actor</th>
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Resource</th>
                  <th className="px-4 py-2 font-medium">Result</th>
                  <th className="px-4 py-2 font-medium">IP</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="whitespace-nowrap px-4 py-2 text-gray-400">
                      {new Date(e.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-2">
                      <div>
                        <span className="font-medium text-white">{e.actor}</span>
                        <span className="ml-2 text-xs text-gray-500">{e.actor_email}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-gray-300">{formatAction(e.action)}</td>
                    <td className="px-4 py-2">
                      <span className="text-gray-400">{e.resource_type}</span>
                      <span className="ml-1 font-mono text-xs text-gray-600">
                        {e.resource_id.slice(0, 8)}
                      </span>
                    </td>
                    <td className="px-4 py-2">{resultBadge(e.result)}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-500">{e.ip_address}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {total > limit && (
          <div className="flex items-center justify-between border-t border-[#2a2d37] px-4 py-3">
            <span className="text-xs text-gray-500">
              {page * limit + 1}–{Math.min((page + 1) * limit, total)} of {total}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                className="rounded border border-[#2a2d37] px-3 py-1 text-xs text-gray-400 hover:bg-white/5 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                disabled={(page + 1) * limit >= total}
                onClick={() => setPage((p) => p + 1)}
                className="rounded border border-[#2a2d37] px-3 py-1 text-xs text-gray-400 hover:bg-white/5 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
