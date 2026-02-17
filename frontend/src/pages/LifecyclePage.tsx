import { useState, useEffect } from "react";
import { RefreshCw, Rocket, HeartPulse, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { apiGet, apiPost } from "@/api/client";

interface Deployment {
  id: string;
  agent_id: string;
  version_id: string;
  environment: string;
  strategy: string;
  replicas: number;
  status: string;
  created_at: string;
  updated_at: string;
}

interface HealthCheck {
  status: string;
  latency_ms: number;
  checked_at: string;
  details: Record<string, unknown>;
}

function stageBadge(stage: string) {
  const cls: Record<string, string> = { dev: "bg-gray-500/20 text-gray-400", staging: "bg-blue-500/20 text-blue-400", canary: "bg-yellow-500/20 text-yellow-400", production: "bg-green-500/20 text-green-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[stage] ?? "bg-gray-500/20 text-gray-400"}`}>{stage}</span>;
}

function statusBadge(status: string) {
  const cls: Record<string, string> = { pending: "bg-gray-500/20 text-gray-400", deploying: "bg-blue-500/20 text-blue-400", active: "bg-green-500/20 text-green-400", draining: "bg-yellow-500/20 text-yellow-400", failed: "bg-red-500/20 text-red-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[status] ?? "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}

function healthDot(status: string) {
  const cls: Record<string, string> = { healthy: "bg-green-400", degraded: "bg-yellow-400", unhealthy: "bg-red-400" };
  return <span className={`inline-block h-2 w-2 rounded-full ${cls[status] ?? "bg-gray-400"}`} />;
}

export function LifecyclePage() {
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [environment, setEnvironment] = useState("staging");
  const [strategy, setStrategy] = useState("rolling");
  const [replicas, setReplicas] = useState("2");
  const [creating, setCreating] = useState(false);
  const [healthChecks, setHealthChecks] = useState<Record<string, HealthCheck>>({});
  const [checkingHealth, setCheckingHealth] = useState<string | null>(null);

  async function fetchDeployments() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<Deployment[]>("/lifecycle/deployments");
      setDeployments(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load deployments.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchDeployments(); }, []);

  async function handleDeploy() {
    if (!agentId.trim() || !versionId.trim()) return;
    setCreating(true);
    try {
      await apiPost("/lifecycle/deployments", {
        agent_id: agentId,
        version_id: versionId,
        environment,
        strategy,
        replicas: parseInt(replicas) || 1,
      });
      setShowForm(false);
      setAgentId(""); setVersionId(""); setReplicas("2");
      await fetchDeployments();
    } catch {
      setError("Failed to create deployment.");
    } finally {
      setCreating(false);
    }
  }

  async function handleHealthCheck(id: string) {
    setCheckingHealth(id);
    try {
      const res = await apiPost<HealthCheck>(`/lifecycle/deployments/${id}/health`, {});
      setHealthChecks((prev) => ({ ...prev, [id]: res.data }));
    } catch {
      setError("Health check failed.");
    } finally {
      setCheckingHealth(null);
    }
  }

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
          <RefreshCw size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Lifecycle</h1>
        </div>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          <Rocket size={14} className="mr-1.5" />Deploy
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Manage deployments, promotions, and health monitoring across environments.</p>

      {showForm && (
        <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-sm font-semibold text-white">New Deployment</h3>
          <div className="flex flex-wrap gap-3">
            <Input placeholder="Agent ID *" value={agentId} onChange={(e) => setAgentId(e.target.value)} className="max-w-xs" />
            <Input placeholder="Version ID *" value={versionId} onChange={(e) => setVersionId(e.target.value)} className="max-w-xs" />
            <select value={environment} onChange={(e) => setEnvironment(e.target.value)} className="h-9 rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
              <option value="dev">Dev</option>
              <option value="staging">Staging</option>
              <option value="canary">Canary</option>
              <option value="production">Production</option>
            </select>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className="h-9 rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
              <option value="rolling">Rolling</option>
              <option value="blue-green">Blue-Green</option>
              <option value="canary">Canary</option>
            </select>
            <Input type="number" placeholder="Replicas" value={replicas} onChange={(e) => setReplicas(e.target.value)} className="max-w-[100px]" />
            <Button size="sm" onClick={handleDeploy} disabled={creating || !agentId.trim() || !versionId.trim()}>
              {creating && <Loader2 size={14} className="mr-1.5 animate-spin" />}
              Deploy
            </Button>
          </div>
        </div>
      )}

      {/* Deployments table */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Deployments ({deployments.length})</h2>
        </div>
        {deployments.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Rocket size={32} className="mb-2 text-gray-600" />
            <p className="text-sm text-gray-500">No deployments yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Agent</th>
                <th className="px-4 py-2 font-medium">Environment</th>
                <th className="px-4 py-2 font-medium">Strategy</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Replicas</th>
                <th className="px-4 py-2 font-medium">Health</th>
                <th className="px-4 py-2 font-medium" />
              </tr></thead>
              <tbody>{deployments.map((d) => (
                <tr key={d.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                  <td className="px-4 py-2">
                    <span className="font-medium text-white">{d.agent_id}</span>
                    <span className="text-gray-500"> v{d.version_id}</span>
                  </td>
                  <td className="px-4 py-2">{stageBadge(d.environment)}</td>
                  <td className="px-4 py-2 text-gray-400">{d.strategy}</td>
                  <td className="px-4 py-2">{statusBadge(d.status)}</td>
                  <td className="px-4 py-2 text-gray-400">{d.replicas}</td>
                  <td className="px-4 py-2">
                    {healthChecks[d.id] ? (
                      <div className="flex items-center gap-2">
                        {healthDot(healthChecks[d.id]!.status)}
                        <span className="capitalize text-xs">{healthChecks[d.id]!.status}</span>
                        <span className="text-xs text-gray-500">{healthChecks[d.id]!.latency_ms}ms</span>
                      </div>
                    ) : (
                      <span className="text-xs text-gray-500">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <Button variant="ghost" size="sm" onClick={() => handleHealthCheck(d.id)} disabled={checkingHealth === d.id}>
                      {checkingHealth === d.id ? <Loader2 size={12} className="animate-spin" /> : <HeartPulse size={12} className="mr-1" />}
                      Check
                    </Button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
