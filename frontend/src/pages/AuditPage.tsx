import { useState, useMemo, useEffect } from "react";
import { ClipboardList } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import { AuditTimeline } from "@/components/audit/AuditTimeline";
import { AuditFilters, type AuditFilterValues } from "@/components/audit/AuditFilters";
import { ExportButton } from "@/components/audit/ExportButton";
import type { AuditEntry } from "@/components/audit/AuditEventCard";

const PAGE_SIZE = 20;

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
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

  // Reset to first page whenever filters change
  useEffect(() => {
    setOffset(0);
    setEntries([]);
  }, [queryParams]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["audit-logs", queryParams, offset],
    queryFn: () =>
      apiGet<AuditEntry[]>("/audit-logs/", {
        limit: PAGE_SIZE,
        offset,
        ...queryParams,
      }),
  });

  // Accumulate results when offset advances (load more)
  useEffect(() => {
    if (!data) return;
    const fetched = Array.isArray(data.data) ? data.data : [];
    setTotal(data.meta?.pagination?.total ?? fetched.length);
    setEntries((prev) => (offset === 0 ? fetched : [...prev, ...fetched]));
    setLoadingMore(false);
  }, [data, offset]);

  const handleLoadMore = () => {
    if (entries.length < total) {
      setLoadingMore(true);
      setOffset(entries.length);
    }
  };

  const handleFiltersChange = (next: AuditFilterValues) => {
    setFilters(next);
  };

  if (isLoading && offset === 0) {
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
          Failed to load audit logs.
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

      <AuditFilters filters={filters} onChange={handleFiltersChange} />

      <AuditTimeline
        entries={entries}
        hasMore={entries.length < total}
        onLoadMore={handleLoadMore}
        loadingMore={loadingMore}
      />
    </div>
  );
}
