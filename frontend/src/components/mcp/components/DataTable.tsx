import { useState, useMemo } from "react";
import { ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/utils/cn";

// ── Types ────────────────────────────────────────────────────────────

interface Column {
  key: string;
  label: string;
  sortable?: boolean;
}

interface DataTableProps {
  columns: Column[];
  rows: Record<string, unknown>[];
  pageSize?: number;
  onRowClick?: (row: Record<string, unknown>) => void;
  onAction?: (action: string, payload: Record<string, unknown>) => void;
}

// ── Component ────────────────────────────────────────────────────────

export function DataTable({
  columns,
  rows,
  pageSize = 10,
  onRowClick,
  onAction,
}: DataTableProps) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    return [...rows].sort((a, b) => {
      const av = String(a[sortKey] ?? "");
      const bv = String(b[sortKey] ?? "");
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    });
  }, [rows, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const paginated = sorted.slice(page * pageSize, (page + 1) * pageSize);

  function handleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    onAction?.("sort", { column: key, direction: sortDir });
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[#2a2d37]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#2a2d37] bg-[#0f1117]">
            {columns.map((col) => (
              <th
                key={col.key}
                className={cn(
                  "px-4 py-2.5 text-left text-xs font-medium text-gray-400 uppercase tracking-wider",
                  col.sortable !== false && "cursor-pointer hover:text-white",
                )}
                onClick={() => col.sortable !== false && handleSort(col.key)}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {col.sortable !== false && (
                    <ArrowUpDown
                      size={12}
                      className={cn(
                        sortKey === col.key ? "text-purple-400" : "text-gray-600",
                      )}
                    />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {paginated.map((row, i) => (
            <tr
              key={i}
              className={cn(
                "border-b border-[#2a2d37] transition-colors",
                onRowClick && "cursor-pointer hover:bg-purple-500/5",
                !onRowClick && "hover:bg-white/5",
              )}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
                <td key={col.key} className="px-4 py-2 text-gray-300">
                  {String(row[col.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
          {paginated.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-4 py-6 text-center text-gray-500"
              >
                No data available
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-[#2a2d37] bg-[#0f1117] px-4 py-2">
          <span className="text-xs text-gray-500">
            {sorted.length} row{sorted.length !== 1 && "s"} · Page {page + 1} of{" "}
            {totalPages}
          </span>
          <div className="flex gap-1">
            <button
              className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white disabled:opacity-30"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              aria-label="Previous page"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white disabled:opacity-30"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              aria-label="Next page"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
