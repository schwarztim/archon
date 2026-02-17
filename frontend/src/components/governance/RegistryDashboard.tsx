import { useState, useEffect } from "react";
import { ShieldCheck, Search, RefreshCw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { listRegistry, scanAgent, type RegistryAgent } from "@/api/governance";
import { AgentDetail } from "./AgentDetail";

function complianceBadge(status: string) {
  if (status === "compliant")
    return <span className="inline-flex items-center gap-1 rounded-full bg-green-500/20 px-2 py-0.5 text-xs font-medium text-green-400">✅ Compliant</span>;
  if (status === "non_compliant")
    return <span className="inline-flex items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-medium text-red-400">⚠️ Non-Compliant</span>;
  if (status === "at_risk")
    return <span className="inline-flex items-center gap-1 rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs font-medium text-yellow-400">🔶 At Risk</span>;
  return <span className="inline-flex items-center gap-1 rounded-full bg-gray-500/20 px-2 py-0.5 text-xs font-medium text-gray-400">❓ Unknown</span>;
}

function riskScoreBar(score: number) {
  const color = score >= 70 ? "bg-red-500" : score >= 40 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs text-gray-400">{score}</span>
    </div>
  );
}

function riskBadge(level: string) {
  const cls: Record<string, string> = {
    critical: "bg-red-500/20 text-red-400",
    high: "bg-orange-500/20 text-orange-400",
    medium: "bg-yellow-500/20 text-yellow-400",
    low: "bg-green-500/20 text-green-400",
  };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[level] ?? "bg-gray-500/20 text-gray-400"}`}>{level}</span>;
}

export function RegistryDashboard() {
  const [agents, setAgents] = useState<RegistryAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [scanning, setScanning] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  async function fetchAgents() {
    setLoading(true);
    try {
      const res = await listRegistry({ limit: 100 });
      setAgents(Array.isArray(res.data) ? res.data : []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchAgents(); }, []);

  async function handleScan(agentId: string) {
    setScanning(agentId);
    try {
      await scanAgent(agentId);
      await fetchAgents();
    } catch {
      /* ignore */
    } finally {
      setScanning(null);
    }
  }

  const filtered = agents.filter(
    (a) =>
      a.owner.toLowerCase().includes(search.toLowerCase()) ||
      a.agent_id.toLowerCase().includes(search.toLowerCase()) ||
      a.department.toLowerCase().includes(search.toLowerCase()),
  );

  if (selectedAgent) {
    return <AgentDetail agentId={selectedAgent} onBack={() => setSelectedAgent(null)} />;
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <ShieldCheck size={16} />
          Agent Registry ({filtered.length})
        </h2>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2.5 text-gray-500" />
            <Input
              placeholder="Search agents..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 pl-8 text-xs"
            />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 size={20} className="animate-spin text-gray-500" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12">
          <ShieldCheck size={32} className="mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">No agents registered yet.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Agent</th>
                <th className="px-4 py-2 font-medium">Owner</th>
                <th className="px-4 py-2 font-medium">Compliance Status</th>
                <th className="px-4 py-2 font-medium">Risk Score</th>
                <th className="px-4 py-2 font-medium">Risk Level</th>
                <th className="px-4 py-2 font-medium">Last Scan</th>
                <th className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr
                  key={a.id}
                  className="cursor-pointer border-b border-[#2a2d37] hover:bg-white/5"
                  onClick={() => setSelectedAgent(a.agent_id)}
                >
                  <td className="px-4 py-2">
                    <div className="font-medium text-white">{a.agent_id}</div>
                    <div className="text-xs text-gray-500">{a.department}</div>
                  </td>
                  <td className="px-4 py-2 text-gray-400">{a.owner}</td>
                  <td className="px-4 py-2">{complianceBadge(a.compliance_status)}</td>
                  <td className="px-4 py-2">{riskScoreBar(a.risk_score)}</td>
                  <td className="px-4 py-2">{riskBadge(a.risk_level)}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {a.total_scans > 0
                      ? new Date(a.updated_at).toLocaleDateString()
                      : "Never"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleScan(a.agent_id);
                      }}
                      disabled={scanning === a.agent_id}
                    >
                      {scanning === a.agent_id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <RefreshCw size={12} />
                      )}
                      <span className="ml-1">Scan</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
