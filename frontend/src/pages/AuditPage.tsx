import { useState, useEffect, useCallback, useMemo } from "react";
import { ClipboardList } from "lucide-react";
import { apiGet } from "@/api/client";
import { AuditTimeline } from "@/components/audit/AuditTimeline";
import { AuditFilters, type AuditFilterValues } from "@/components/audit/AuditFilters";
import { ExportButton } from "@/components/audit/ExportButton";
import type { AuditEntry } from "@/components/audit/AuditEventCard";

const PAGE_SIZE = 20;

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<AuditFilterValues>({
    search: "",
    action: "",
    resourceType: "",
    dateFrom: "",
    dateTo: "",
  });

  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    if (filters.action) p.action = filters.action;
    if (filters.resourceType) p.resource_type = filters.resourceType;
    if (filters.search) p.search = filters.search;
    if (filters.dateFrom) p.date_from = new Date(filters.dateFrom).toISOString();
    if (filters.dateTo) p.date_to = new Date(filters.dateTo + "T23:59:59").toISOString();
    return p;
  }, [filters]);

  const fetchAuditLogs = useCallback(
    async (offset: number, append: boolean) => {
      if (!append) setLoading(true);
      else setLoadingMore(true);
      setError(null);
      try {
        const params: Record<string, string | number> = {
          limit: PAGE_SIZE,
          offset,
          ...queryParams,
        };
        const res = await apiGet<AuditEntry[]>("/audit-logs/", params);
        const data = Array.isArray(res.data) ? res.data : [];
        setEntries((prev) => (append ? [...prev, ...data] : data));
        setTotal(res.meta?.pagination?.total ?? data.length);
      } catch {
        if (!append) setEntries([]);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [queryParams],
  );

  useEffect(() => {
    void fetchAuditLogs(0, false);
  }, [fetchAuditLogs]);

  const handleLoadMore = useCallback(() => {
    if (entries.length < total) {
      void fetchAuditLogs(entries.length, true);
    }
  }, [entries.length, total, fetchAuditLogs]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ClipboardList size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Audit Trail</h1>
        </div>
        <ExportButton queryParams={queryParams} />
      </div>
      <p className="mb-6 text-gray-400">
        Comprehensive log of all actions, configuration changes, and access
        events.
      </p>

      <AuditFilters filters={filters} onChange={setFilters} />

      <AuditTimeline
        entries={entries}
        hasMore={entries.length < total}
        onLoadMore={handleLoadMore}
        loadingMore={loadingMore}
      />
    </div>
  );
}
