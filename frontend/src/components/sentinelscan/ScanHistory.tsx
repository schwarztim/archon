import { Scan, Play } from "lucide-react";
import type { ScanHistoryEntry } from "@/api/sentinelscan";

interface ScanHistoryProps {
  scans: ScanHistoryEntry[];
  onRerun?: (scan: ScanHistoryEntry) => void;
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    pending: "bg-gray-500/20 text-gray-400",
    running: "bg-blue-500/20 text-blue-400",
    completed: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? "bg-gray-500/20 text-gray-400"}`}>
      {status}
    </span>
  );
}

export function ScanHistory({ scans, onRerun }: ScanHistoryProps) {
  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="border-b border-[#2a2d37] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Scan History</h2>
      </div>
      {scans.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12">
          <Scan size={32} className="mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">No scans yet.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Scan ID</th>
                <th className="px-4 py-2 font-medium">Sources</th>
                <th className="px-4 py-2 font-medium">Depth</th>
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Findings</th>
                {onRerun && <th className="px-4 py-2 font-medium">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {scans.map((s) => (
                <tr key={s.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                  <td className="px-4 py-2 text-gray-400 font-mono text-xs">
                    {s.id.slice(0, 8)}…
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex gap-1 flex-wrap">
                      {s.sources.map((src) => (
                        <span key={src} className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-gray-400">
                          {src}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{s.scan_depth}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">
                    {new Date(s.started_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2">{statusBadge(s.status)}</td>
                  <td className="px-4 py-2 text-gray-400">{s.findings_count}</td>
                  {onRerun && (
                    <td className="px-4 py-2">
                      <button
                        onClick={() => onRerun(s)}
                        className="flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 transition-colors"
                        type="button"
                      >
                        <Play size={10} /> Re-run
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
