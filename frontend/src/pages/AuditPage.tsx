import { useState, useEffect, useCallback } from "react";
import { ClipboardList, Download, ChevronDown, ChevronUp, Calendar } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { apiGet } from "@/api/client";

interface AuditEntry {
  id: string;
  timestamp: string;
  action: string;
  resource_type: string;
  resource_id: string;
  actor_id: string;
  outcome: string;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

function outcomeBadge(outcome: string) {
  const isFail = outcome === "failure" || outcome === "error";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${isFail ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"}`}>
      {outcome}
    </span>
  );
}

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    async function fetchAuditLogs() {
      setLoading(true);
      setError(null);
      try {
        const res = await apiGet<AuditEntry[]>("/audit-logs/");
        setEntries(Array.isArray(res.data) ? res.data : []);
      } catch {
        setEntries([]);
      } finally {
        setLoading(false);
      }
    }
    void fetchAuditLogs();
  }, []);

  const handleExport = useCallback(() => {
    const link = document.createElement("a");
    link.href = "/api/v1/audit-logs/export?format=csv&limit=10000";
    link.download = "audit_logs.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, []);

  const filtered = entries.filter((e) => {
    if (actionFilter && !e.action.toLowerCase().includes(actionFilter.toLowerCase())) return false;
    if (resourceFilter && !e.resource_type.toLowerCase().includes(resourceFilter.toLowerCase())) return false;
    const ts = e.timestamp ?? e.created_at;
    if (dateFrom && ts < dateFrom) return false;
    if (dateTo && ts > dateTo + "T23:59:59") return false;
    return true;
  });

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><p className="text-gray-400">Loading...</p></div>;
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ClipboardList size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Audit Trail</h1>
        </div>
        <Button variant="secondary" size="sm" onClick={handleExport}>
          <Download size={14} className="mr-1.5" />Export CSV
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Comprehensive log of all actions, configuration changes, and access events.</p>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input placeholder="Filter by action…" value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} className="max-w-[200px]" />
        <Input placeholder="Filter by resource…" value={resourceFilter} onChange={(e) => setResourceFilter(e.target.value)} className="max-w-[200px]" />
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <Calendar size={14} />
          <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="max-w-[150px]" placeholder="From" />
          <span>–</span>
          <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="max-w-[150px]" placeholder="To" />
        </div>
      </div>

      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
              <th className="px-4 py-2 font-medium w-5" />
              <th className="px-4 py-2 font-medium">Timestamp</th>
              <th className="px-4 py-2 font-medium">Actor</th>
              <th className="px-4 py-2 font-medium">Action</th>
              <th className="px-4 py-2 font-medium">Resource</th>
              <th className="px-4 py-2 font-medium">Outcome</th>
            </tr></thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id} className="border-b border-[#2a2d37] hover:bg-white/5 cursor-pointer" onClick={() => setExpandedId(expandedId === e.id ? null : e.id)}>
                  <td className="px-4 py-2 text-gray-500">{expandedId === e.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</td>
                  <td className="px-4 py-2 text-gray-400">{new Date(e.timestamp ?? e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-2 font-medium text-white">{e.actor_id}</td>
                  <td className="px-4 py-2"><code className="rounded bg-white/10 px-1.5 py-0.5 text-xs">{e.action}</code></td>
                  <td className="px-4 py-2 text-gray-400">{e.resource_type}</td>
                  <td className="px-4 py-2">{outcomeBadge(e.outcome ?? (e.action.includes("fail") ? "failure" : "success"))}</td>
                </tr>
              ))}
              {filtered.map((e) => expandedId === e.id && (
                <tr key={`${e.id}-detail`} className="border-b border-[#2a2d37] bg-[#0f1117]">
                  <td colSpan={6} className="px-6 py-3">
                    <div className="grid grid-cols-2 gap-4 text-xs">
                      <div><span className="text-gray-500">Resource ID:</span> <span className="text-gray-300">{e.resource_id}</span></div>
                      <div><span className="text-gray-500">IP Address:</span> <span className="text-gray-300">{e.ip_address ?? "—"}</span></div>
                      {e.details && (
                        <div className="col-span-2"><span className="text-gray-500">Details:</span> <pre className="mt-1 rounded bg-black/30 p-2 text-gray-300">{JSON.stringify(e.details, null, 2)}</pre></div>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  {entries.length === 0 ? "No audit events yet." : "No audit entries match your filters."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
