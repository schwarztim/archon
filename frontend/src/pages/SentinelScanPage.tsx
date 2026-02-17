import { useState, useEffect } from "react";
import {
  Scan,
  Play,
  Loader2,
  AlertTriangle,
  Server,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost } from "@/api/client";

interface DiscoveryScan {
  id: string;
  name: string;
  scan_type: string;
  target: string;
  config: Record<string, unknown>;
  status: string;
  progress_pct?: number;
  services_found?: number;
  created_at: string;
  completed_at: string | null;
}

interface DiscoveredService {
  id: string;
  name: string;
  service_type: string;
  endpoint: string;
  risk_level: string;
  risk_score: number;
  discovered_at: string;
}

interface PostureSummary {
  total_services: number;
  risk_summary: Record<string, number>;
  recommendations: string[];
}

interface RiskOverview {
  overall_score: number;
  risk_breakdown: Record<string, number>;
}

function riskBadge(level: string) {
  const colors: Record<string, string> = {
    critical: "bg-red-500/20 text-red-400",
    high: "bg-orange-500/20 text-orange-400",
    medium: "bg-yellow-500/20 text-yellow-400",
    low: "bg-green-500/20 text-green-400",
    info: "bg-blue-500/20 text-blue-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colors[level] ?? "bg-gray-500/20 text-gray-400"}`}>
      {level}
    </span>
  );
}

function scanStatusBadge(status: string) {
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

function postureScoreColor(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-yellow-400";
  if (score >= 40) return "text-orange-400";
  return "text-red-400";
}

export function SentinelScanPage() {
  const [scans, setScans] = useState<DiscoveryScan[]>([]);
  const [services, setServices] = useState<DiscoveredService[]>([]);
  const [posture, setPosture] = useState<PostureSummary | null>(null);
  const [risk, setRisk] = useState<RiskOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scanName, setScanName] = useState("");
  const [scanTarget, setScanTarget] = useState("");
  const [scanType, setScanType] = useState("full");
  const [creating, setCreating] = useState(false);

  async function fetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [scansRes, inventoryRes, postureRes, riskRes] = await Promise.allSettled([
        apiGet<DiscoveryScan[]>("/sentinelscan/discovery"),
        apiGet<DiscoveredService[]>("/sentinelscan/inventory"),
        apiGet<PostureSummary>("/sentinelscan/posture"),
        apiGet<RiskOverview>("/sentinelscan/risk"),
      ]);
      if (scansRes.status === "fulfilled") setScans(Array.isArray(scansRes.value.data) ? scansRes.value.data : []);
      if (inventoryRes.status === "fulfilled") setServices(Array.isArray(inventoryRes.value.data) ? inventoryRes.value.data : []);
      if (postureRes.status === "fulfilled") setPosture(postureRes.value.data as PostureSummary);
      if (riskRes.status === "fulfilled") setRisk(riskRes.value.data as RiskOverview);
    } catch {
      setError("Failed to load SentinelScan data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchAll(); }, []);

  async function handleCreateScan() {
    if (!scanName.trim() || !scanTarget.trim()) return;
    setCreating(true);
    try {
      await apiPost("/sentinelscan/discovery", {
        name: scanName,
        scan_type: scanType,
        target: scanTarget,
        config: {},
      });
      setScanName(""); setScanTarget("");
      await fetchAll();
    } catch {
      setError("Failed to create scan.");
    } finally {
      setCreating(false);
    }
  }

  const riskSummary = posture?.risk_summary ?? {};
  const totalRisks = Object.values(riskSummary).reduce((a, b) => a + b, 0);
  const criticalHighCount = (riskSummary["critical"] ?? 0) + (riskSummary["high"] ?? 0);
  const postureScore = totalRisks > 0 ? Math.max(0, Math.min(100, Math.round(((totalRisks - criticalHighCount * 2) / totalRisks) * 100))) : 100;

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><p className="text-gray-400">Loading...</p></div>;
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <Scan size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">SentinelScan</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Discover shadow AI services, assess security posture, and monitor your organization&apos;s AI landscape.
      </p>

      {/* Top row: Posture Score + Risk Summary + Quick Scan */}
      <div className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-4">
        {/* Posture Score */}
        <div className="flex flex-col items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6">
          <p className="mb-1 text-xs text-gray-500 uppercase tracking-wider">Security Posture</p>
          <div className="relative my-2">
            <svg className="h-28 w-28" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="50" fill="none" stroke="currentColor" strokeWidth="8" className="text-white/10" />
              <circle cx="60" cy="60" r="50" fill="none" strokeWidth="8" stroke="currentColor" className={postureScoreColor(postureScore)} strokeDasharray={`${postureScore * 3.14} ${(100 - postureScore) * 3.14}`} strokeLinecap="round" transform="rotate(-90 60 60)" />
            </svg>
            <span className={`absolute inset-0 flex items-center justify-center text-3xl font-bold ${postureScoreColor(postureScore)}`}>
              {postureScore}
            </span>
          </div>
          <p className="text-xs text-gray-500">{posture?.total_services ?? 0} services monitored</p>
        </div>

        {/* Risk Distribution */}
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Risk Distribution</h3>
          <div className="space-y-3">
            {(["critical", "high", "medium", "low"] as const).map((level) => {
              const count = riskSummary[level] ?? 0;
              const pct = totalRisks > 0 ? (count / totalRisks) * 100 : 0;
              const barColors: Record<string, string> = { critical: "bg-red-500", high: "bg-orange-500", medium: "bg-yellow-500", low: "bg-green-500" };
              return (
                <div key={level}>
                  <div className="mb-1 flex items-center justify-between">
                    {riskBadge(level)}
                    <span className="text-sm font-semibold text-white">{count}</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-white/10">
                    <div className={`h-full rounded-full ${barColors[level]}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
          {risk && (
            <div className="mt-3 text-xs text-gray-500">Overall risk score: {risk.overall_score}</div>
          )}
        </div>

        {/* Quick Scan Launcher */}
        <div className="lg:col-span-2 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Run Discovery Scan</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Scan Name *</label>
              <input className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={scanName} onChange={(e) => setScanName(e.target.value)} placeholder="Quick Discovery Scan" />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Target *</label>
              <input className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={scanTarget} onChange={(e) => setScanTarget(e.target.value)} placeholder="10.0.0.0/8 or hostname" />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Scan Type</label>
              <select className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={scanType} onChange={(e) => setScanType(e.target.value)}>
                <option value="full">Full Scan</option>
                <option value="network">Network</option>
                <option value="api">API</option>
                <option value="agent">Agent</option>
              </select>
            </div>
            <div className="flex items-end">
              <Button className="w-full" size="sm" onClick={handleCreateScan} disabled={creating || !scanName.trim() || !scanTarget.trim()}>
                {creating ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Play size={14} className="mr-1.5" />}
                Run Discovery Scan
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Discovered Services Inventory */}
      <div className="mb-8 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Discovered Services ({services.length})</h2>
        </div>
        {services.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Server size={32} className="mb-2 text-gray-600" />
            <p className="text-sm text-gray-500">No services discovered yet. Run a scan to get started.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Service</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Endpoint</th>
                  <th className="px-4 py-2 font-medium">Risk Level</th>
                  <th className="px-4 py-2 font-medium">Risk Score</th>
                  <th className="px-4 py-2 font-medium text-right">Discovered</th>
                </tr>
              </thead>
              <tbody>
                {services.map((svc) => (
                  <tr key={svc.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <Server size={14} className="text-gray-500" />
                        <span className="font-medium text-white">{svc.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      <span className="inline-block rounded bg-white/10 px-1.5 py-0.5 text-xs text-gray-400">{svc.service_type}</span>
                    </td>
                    <td className="px-4 py-2">
                      <code className="text-xs text-gray-500">{svc.endpoint}</code>
                    </td>
                    <td className="px-4 py-2">{riskBadge(svc.risk_level)}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-16 rounded-full bg-white/10">
                          <div className={`h-full rounded-full ${svc.risk_score >= 70 ? "bg-red-500" : svc.risk_score >= 40 ? "bg-yellow-500" : "bg-green-500"}`} style={{ width: `${svc.risk_score}%` }} />
                        </div>
                        <span className="text-xs text-gray-500">{svc.risk_score}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-right text-gray-400">
                      {new Date(svc.discovered_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recommendations + Scan History */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="border-b border-[#2a2d37] px-4 py-3">
            <h2 className="text-sm font-semibold text-white">Recommendations</h2>
          </div>
          <div className="p-4 space-y-2">
            {(posture?.recommendations ?? []).length === 0 ? (
              <p className="text-sm text-gray-500">No recommendations at this time.</p>
            ) : (
              posture!.recommendations.map((rec, i) => (
                <div key={i} className="flex items-start gap-3 rounded-md border border-[#2a2d37] bg-[#0f1117] p-3">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0 text-yellow-400" />
                  <span className="text-sm text-gray-300">{rec}</span>
                </div>
              ))
            )}
          </div>
        </div>

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
                    <th className="px-4 py-2 font-medium">Scan</th>
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Found</th>
                    <th className="px-4 py-2 font-medium text-right">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {scans.map((s) => (
                    <tr key={s.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                      <td className="px-4 py-2">
                        <div className="font-medium text-white">{s.name}</div>
                        <div className="text-xs text-gray-500">{s.target}</div>
                      </td>
                      <td className="px-4 py-2">
                        <span className="inline-block rounded bg-white/10 px-1.5 py-0.5 text-xs text-gray-400">{s.scan_type}</span>
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          {scanStatusBadge(s.status)}
                          {s.status === "running" && s.progress_pct != null && (
                            <span className="text-xs text-gray-500">{s.progress_pct}%</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-gray-400">{s.services_found ?? "—"}</td>
                      <td className="px-4 py-2 text-right text-gray-400">
                        {new Date(s.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
