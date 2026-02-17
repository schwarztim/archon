import { useState, useEffect, useCallback } from "react";
import { FileWarning, Loader2, RefreshCw, Shield } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet } from "@/api/client";
import type { DLPDetectionItem } from "@/api/dlp";

function actionBadge(action: string) {
  const colors: Record<string, string> = {
    block: "bg-red-500/20 text-red-400",
    redact: "bg-purple-500/20 text-purple-400",
    allow: "bg-green-500/20 text-green-400",
    none: "bg-gray-500/20 text-gray-400",
    log: "bg-gray-500/20 text-gray-400",
    alert: "bg-yellow-500/20 text-yellow-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${colors[action] ?? colors.none}`}>
      {action}
    </span>
  );
}

export function DetectionsList() {
  const [detections, setDetections] = useState<DLPDetectionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  const fetchDetections = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGet<DLPDetectionItem[]>("/api/v1/dlp/detections", {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setDetections(Array.isArray(res.data) ? res.data : []);
      setTotal(res.meta?.pagination?.total ?? 0);
    } catch {
      // Silently handle — show empty state
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    void fetchDetections();
  }, [fetchDetections]);

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 size={20} className="animate-spin text-gray-500" />
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
        <div className="flex items-center gap-2">
          <FileWarning size={16} className="text-orange-400" />
          <h3 className="text-sm font-semibold text-white">Recent Detections</h3>
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-gray-400">
            {total} total
          </span>
        </div>
        <Button variant="ghost" size="sm" onClick={() => fetchDetections()}>
          <RefreshCw size={12} className="mr-1" /> Refresh
        </Button>
      </div>

      {detections.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12">
          <Shield size={28} className="mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">No detections recorded yet.</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Time</th>
                  <th className="px-4 py-2 font-medium">Types</th>
                  <th className="px-4 py-2 font-medium">Findings</th>
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody>
                {detections.map((d) => (
                  <tr key={d.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="whitespace-nowrap px-4 py-2 text-gray-400">
                      {d.created_at
                        ? new Date(d.created_at).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {d.entity_types.slice(0, 3).map((t) => (
                          <span key={t} className="inline-block rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] text-purple-300">
                            {t}
                          </span>
                        ))}
                        {d.entity_types.length > 3 && (
                          <span className="text-[10px] text-gray-500">+{d.entity_types.length - 3}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-white font-medium">{d.findings_count}</td>
                    <td className="px-4 py-2">{actionBadge(d.action_taken)}</td>
                    <td className="px-4 py-2 text-gray-400">{d.source}</td>
                    <td className="px-4 py-2">
                      <code className="text-[10px] text-gray-600">{d.text_hash ?? "—"}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-[#2a2d37] px-4 py-2">
              <span className="text-xs text-gray-500">
                Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={(page + 1) * PAGE_SIZE >= total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
