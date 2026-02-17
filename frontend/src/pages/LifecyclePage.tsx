import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Rocket, HeartPulse, Loader2, ArrowLeftRight, Settings, Clock, Server } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost } from "@/api/client";
import { PipelineView } from "@/components/lifecycle/PipelineView";
import { DeployForm } from "@/components/lifecycle/DeployForm";
import { EnvironmentCard } from "@/components/lifecycle/EnvironmentCard";
import { DiffView } from "@/components/lifecycle/DiffView";
import { DeploymentHistory } from "@/components/lifecycle/DeploymentHistory";
import { ApprovalGateConfig } from "@/components/lifecycle/ApprovalGateConfig";
import type { EnvironmentInfo, ConfigDiff, DeploymentHistoryEntry, ApprovalGate, HealthMetrics } from "@/types/models";
import * as lifecycleApi from "@/api/lifecycle";

interface AgentDef {
  id: string;
  name: string;
  version: number;
}

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

interface PipelineStage {
  stage: string;
  label: string;
  deployments: Array<{
    id: string;
    agent_id: string;
    version_id: string;
    status: string;
    environment: string;
  }>;
  approval_gate: { enabled: boolean; required_approvers: number } | null;
}

type ActiveTab = "pipeline" | "environments" | "history" | "gates";

function statusBadge(status: string) {
  const cls: Record<string, string> = { pending: "bg-gray-500/20 text-gray-400", deploying: "bg-blue-500/20 text-blue-400", active: "bg-green-500/20 text-green-400", draining: "bg-yellow-500/20 text-yellow-400", failed: "bg-red-500/20 text-red-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[status] ?? "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}

function stageBadge(stage: string) {
  const cls: Record<string, string> = { dev: "bg-gray-500/20 text-gray-400", staging: "bg-yellow-500/20 text-yellow-400", canary: "bg-blue-500/20 text-blue-400", production: "bg-green-500/20 text-green-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[stage] ?? "bg-gray-500/20 text-gray-400"}`}>{stage}</span>;
}

function healthDot(status: string) {
  const cls: Record<string, string> = { healthy: "bg-green-400", degraded: "bg-yellow-400", unhealthy: "bg-red-400" };
  return <span className={`inline-block h-2 w-2 rounded-full ${cls[status] ?? "bg-gray-400"}`} />;
}

export function LifecyclePage() {
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [agents, setAgents] = useState<AgentDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [healthChecks, setHealthChecks] = useState<Record<string, HealthCheck>>({});
  const [checkingHealth, setCheckingHealth] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("pipeline");

  // Pipeline state
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>([]);
  const [pipelineLoading, setPipelineLoading] = useState(false);

  // Environment state
  const [environments, setEnvironments] = useState<EnvironmentInfo[]>([]);
  const [envsLoading, setEnvsLoading] = useState(false);

  // Diff state
  const [diffSource, setDiffSource] = useState("dev");
  const [diffTarget, setDiffTarget] = useState("staging");
  const [configDiff, setConfigDiff] = useState<ConfigDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  // History state
  const [historyEnv, setHistoryEnv] = useState("staging");
  const [historyEntries, setHistoryEntries] = useState<DeploymentHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Gates state
  const [gates, setGates] = useState<ApprovalGate[]>([]);
  const [gatesSaving, setGatesSaving] = useState(false);

  // Health metrics state
  const [healthMetrics, setHealthMetrics] = useState<Record<string, HealthMetrics>>({});

  const fetchDeployments = useCallback(async () => {
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
  }, []);

  const fetchAgents = useCallback(async () => {
    try {
      const res = await apiGet<AgentDef[]>("/agents/");
      setAgents(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
  }, []);

  const fetchPipeline = useCallback(async () => {
    setPipelineLoading(true);
    try {
      const res = await lifecycleApi.getPipeline();
      setPipelineStages(Array.isArray(res.data) ? res.data : []);
    } catch { /* Pipeline endpoint may not return data yet */ }
    finally { setPipelineLoading(false); }
  }, []);

  const fetchEnvironments = useCallback(async () => {
    setEnvsLoading(true);
    try {
      const res = await lifecycleApi.listEnvironments();
      setEnvironments(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setEnvsLoading(false); }
  }, []);

  const fetchHistory = useCallback(async (env: string) => {
    setHistoryLoading(true);
    try {
      const res = await lifecycleApi.getDeploymentHistory(env);
      setHistoryEntries(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setHistoryLoading(false); }
  }, []);

  useEffect(() => {
    void fetchDeployments();
    void fetchAgents();
    void fetchPipeline();
    void fetchEnvironments();
  }, [fetchDeployments, fetchAgents, fetchPipeline, fetchEnvironments]);

  async function handleDeploy(payload: {
    agent_id: string;
    version_id: string;
    environment: string;
    strategy_type: string;
    replicas: number;
    canary_percentage: number;
    blue_green_preview: boolean;
    rollback_threshold: number;
    pre_deploy_checks: boolean;
  }) {
    try {
      await apiPost("/lifecycle/deployments", {
        agent_id: payload.agent_id,
        version_id: payload.version_id,
        environment: payload.environment,
        strategy: payload.strategy_type,
        replicas: payload.replicas,
        metadata: {
          canary_pct: payload.canary_percentage,
          blue_green_preview: payload.blue_green_preview,
          rollback_threshold: payload.rollback_threshold,
        },
      });
      setShowForm(false);
      await fetchDeployments();
      await fetchPipeline();
      await fetchEnvironments();
    } catch {
      setError("Failed to create deployment.");
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

  async function handlePromote(deploymentId: string) {
    try {
      await lifecycleApi.promoteToNextStage(deploymentId);
      await fetchPipeline();
      await fetchDeployments();
    } catch {
      setError("Promotion failed.");
    }
  }

  async function handleDemote(deploymentId: string) {
    try {
      await lifecycleApi.demoteToPreviousStage(deploymentId);
      await fetchPipeline();
      await fetchDeployments();
    } catch {
      setError("Demotion failed.");
    }
  }

  async function handleDiff() {
    setDiffLoading(true);
    try {
      const res = await lifecycleApi.getConfigDiff(diffSource, diffTarget);
      setConfigDiff(res.data);
    } catch {
      setError("Failed to load diff.");
    } finally {
      setDiffLoading(false);
    }
  }

  async function handleSaveGates(newGates: Partial<ApprovalGate>[]) {
    setGatesSaving(true);
    try {
      const res = await lifecycleApi.configureGates(newGates);
      setGates(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to save gates.");
    } finally {
      setGatesSaving(false);
    }
  }

  async function handleViewHealth(deploymentId: string) {
    try {
      const res = await lifecycleApi.getDeploymentHealth(deploymentId);
      setHealthMetrics((prev) => ({ ...prev, [deploymentId]: res.data }));
    } catch { /* ignore */ }
  }

  const TABS: { key: ActiveTab; label: string; icon: React.ReactNode }[] = [
    { key: "pipeline", label: "Pipeline", icon: <RefreshCw size={12} /> },
    { key: "environments", label: "Environments", icon: <Server size={12} /> },
    { key: "history", label: "History", icon: <Clock size={12} /> },
    { key: "gates", label: "Gates", icon: <Settings size={12} /> },
  ];

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><p className="text-gray-400">Loading...</p></div>;
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-300 hover:text-red-200">×</button>
        </div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <RefreshCw size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Lifecycle & Deployment</h1>
        </div>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          <Rocket size={14} className="mr-1.5" />{showForm ? "Cancel" : "Deploy"}
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Manage deployments, promotions, and health monitoring across environments.</p>

      {/* ─── Deploy Form ────────────────────────────────────────────── */}
      {showForm && (
        <DeployForm
          agents={agents}
          onDeploy={handleDeploy}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* ─── Tab Navigation ─────────────────────────────────────────── */}
      <div className="mb-4 flex gap-1 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveTab(tab.key);
              if (tab.key === "history") void fetchHistory(historyEnv);
            }}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              activeTab === tab.key
                ? "bg-purple-500/20 text-purple-400"
                : "text-gray-400 hover:text-white"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* ─── Pipeline Tab ───────────────────────────────────────────── */}
      {activeTab === "pipeline" && (
        <PipelineView
          stages={pipelineStages}
          onPromote={handlePromote}
          onDemote={handleDemote}
        />
      )}

      {/* ─── Environments Tab ───────────────────────────────────────── */}
      {activeTab === "environments" && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {environments.map((env) => (
              <EnvironmentCard
                key={env.name}
                env={env}
                onSelect={(name) => {
                  setHistoryEnv(name);
                  setActiveTab("history");
                  void fetchHistory(name);
                }}
              />
            ))}
          </div>

          {/* Diff section */}
          <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
            <div className="mb-3 flex items-center gap-2">
              <ArrowLeftRight size={14} className="text-purple-400" />
              <span className="text-sm font-medium text-white">Environment Diff</span>
            </div>
            <div className="mb-3 flex items-center gap-2">
              <select
                value={diffSource}
                onChange={(e) => setDiffSource(e.target.value)}
                className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
              >
                <option value="dev">Draft</option>
                <option value="staging">Review</option>
                <option value="canary">Staging</option>
                <option value="production">Production</option>
              </select>
              <span className="text-xs text-gray-500">vs</span>
              <select
                value={diffTarget}
                onChange={(e) => setDiffTarget(e.target.value)}
                className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
              >
                <option value="dev">Draft</option>
                <option value="staging">Review</option>
                <option value="canary">Staging</option>
                <option value="production">Production</option>
              </select>
              <Button size="sm" variant="ghost" onClick={handleDiff}>
                Compare
              </Button>
            </div>
            <DiffView diff={configDiff} loading={diffLoading} />
          </div>
        </div>
      )}

      {/* ─── History Tab ────────────────────────────────────────────── */}
      {activeTab === "history" && (
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock size={14} className="text-purple-400" />
              <span className="text-sm font-medium text-white">Deployment History</span>
            </div>
            <select
              value={historyEnv}
              onChange={(e) => { setHistoryEnv(e.target.value); void fetchHistory(e.target.value); }}
              className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
            >
              <option value="dev">Draft</option>
              <option value="staging">Review</option>
              <option value="canary">Staging</option>
              <option value="production">Production</option>
            </select>
          </div>
          <DeploymentHistory entries={historyEntries} loading={historyLoading} />
        </div>
      )}

      {/* ─── Gates Tab ──────────────────────────────────────────────── */}
      {activeTab === "gates" && (
        <ApprovalGateConfig gates={gates} onSave={handleSaveGates} saving={gatesSaving} />
      )}

      {/* ─── Deployment Table ───────────────────────────────────────── */}
      <div className="mt-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">All Deployments ({deployments.length})</h2>
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
                <th className="px-4 py-2 font-medium">Version</th>
                <th className="px-4 py-2 font-medium">Environment</th>
                <th className="px-4 py-2 font-medium">Strategy</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Timestamp</th>
                <th className="px-4 py-2 font-medium">Health</th>
                <th className="px-4 py-2 font-medium" />
              </tr></thead>
              <tbody>{deployments.map((d) => {
                const agentName = agents.find((a) => a.id === d.agent_id)?.name;
                const metrics = healthMetrics[d.id];
                return (
                  <tr key={d.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2">
                      <span className="font-medium text-white">{agentName ?? d.agent_id.slice(0, 8) + "…"}</span>
                    </td>
                    <td className="px-4 py-2 text-gray-400">v{d.version_id}</td>
                    <td className="px-4 py-2">{stageBadge(d.environment)}</td>
                    <td className="px-4 py-2 text-gray-400">{d.strategy}</td>
                    <td className="px-4 py-2">{statusBadge(d.status)}</td>
                    <td className="px-4 py-2 text-xs text-gray-400">{new Date(d.created_at).toLocaleString()}</td>
                    <td className="px-4 py-2">
                      {healthChecks[d.id] ? (
                        <div className="flex items-center gap-2">
                          {healthDot(healthChecks[d.id]!.status)}
                          <span className="capitalize text-xs">{healthChecks[d.id]!.status}</span>
                          <span className="text-xs text-gray-500">{healthChecks[d.id]!.latency_ms}ms</span>
                        </div>
                      ) : metrics ? (
                        <div className="flex items-center gap-1 text-[10px]">
                          <span className="text-green-400">p50:{metrics.response_time_p50}ms</span>
                          <span className="text-yellow-400">p95:{metrics.response_time_p95}ms</span>
                          <span className="text-red-400">err:{(metrics.error_rate * 100).toFixed(1)}%</span>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex gap-1">
                        <Button variant="ghost" size="sm" onClick={() => handleHealthCheck(d.id)} disabled={checkingHealth === d.id}>
                          {checkingHealth === d.id ? <Loader2 size={12} className="animate-spin" /> : <HeartPulse size={12} className="mr-1" />}
                          Check
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleViewHealth(d.id)}>
                          Metrics
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
