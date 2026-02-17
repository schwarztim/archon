import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Bot,
  Play,
  ShieldCheck,
  Plus,
  Layers,
  Cpu,
  Activity,
  Clock,
  ArrowRight,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react";
import { apiGet } from "@/api/client";
import { Button } from "@/components/ui/Button";
import type { AuditEntry } from "@/types/models";

interface Agent {
  id: string;
  name: string;
  status: string;
  updated_at: string;
}

interface Execution {
  id: string;
  agent_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

interface DlpPolicy {
  id: string;
}

interface ModelEntry {
  id: string;
}

interface HealthStatus {
  api: boolean;
  database: boolean;
  redis: boolean;
  vault: boolean;
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    active: "bg-green-500/20 text-green-400",
    draft: "bg-gray-500/20 text-gray-400",
    paused: "bg-yellow-500/20 text-yellow-400",
    completed: "bg-green-500/20 text-green-400",
    running: "bg-blue-500/20 text-blue-400",
    failed: "bg-red-500/20 text-red-400",
    pending: "bg-gray-500/20 text-gray-400",
    cancelled: "bg-yellow-500/20 text-yellow-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${colors[status] ?? "bg-gray-500/20 text-gray-400"}`}>
      {status}
    </span>
  );
}

function formatDuration(ms: number | null) {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function HealthDot({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-500" />;
  return ok
    ? <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" />
    : <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500" />;
}

export function DashboardPage() {
  const navigate = useNavigate();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [policiesCount, setPoliciesCount] = useState<number>(0);
  const [agentCount, setAgentCount] = useState<number>(0);
  const [execCount, setExecCount] = useState<number>(0);
  const [modelCount, setModelCount] = useState<number>(0);
  const [auditEvents, setAuditEvents] = useState<AuditEntry[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const [agentsRes, execsRes, dlpRes, modelsRes, auditRes] = await Promise.allSettled([
          apiGet<Agent[]>("/agents/", { limit: 5 }),
          apiGet<Execution[]>("/executions", { limit: 5 }),
          apiGet<DlpPolicy[]>("/api/v1/dlp/policies"),
          apiGet<ModelEntry[]>("/router/models", { limit: 1 }),
          apiGet<AuditEntry[]>("/governance/audit", { limit: 10 }),
        ]);

        if (agentsRes.status === "fulfilled") {
          const data = agentsRes.value.data;
          setAgents(Array.isArray(data) ? data : []);
          setAgentCount(agentsRes.value.meta?.pagination?.total ?? (Array.isArray(data) ? data.length : 0));
        }
        if (execsRes.status === "fulfilled") {
          const data = execsRes.value.data;
          setExecutions(Array.isArray(data) ? data : []);
          setExecCount(execsRes.value.meta?.pagination?.total ?? (Array.isArray(data) ? data.length : 0));
        }
        if (dlpRes.status === "fulfilled") {
          const data = dlpRes.value.data;
          setPoliciesCount(dlpRes.value.meta?.pagination?.total ?? (Array.isArray(data) ? data.length : 0));
        }
        if (modelsRes.status === "fulfilled") {
          setModelCount(modelsRes.value.meta?.pagination?.total ?? (Array.isArray(modelsRes.value.data) ? modelsRes.value.data.length : 0));
        }
        if (auditRes.status === "fulfilled") {
          const data = auditRes.value.data;
          setAuditEvents(Array.isArray(data) ? data : []);
        }
      } catch {
        setError("Failed to load dashboard data.");
      } finally {
        setLoading(false);
      }
    }

    async function fetchHealth() {
      try {
        const res = await fetch("/ready");
        if (res.ok) {
          const data = await res.json();
          setHealth({
            api: true,
            database: data?.database ?? data?.db ?? true,
            redis: data?.redis ?? true,
            vault: data?.vault ?? true,
          });
        } else {
          setHealth({ api: false, database: false, redis: false, vault: false });
        }
      } catch {
        setHealth({ api: false, database: false, redis: false, vault: false });
      }
    }

    void fetchData();
    void fetchHealth();
  }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 size={24} className="animate-spin text-purple-400" />
        <p className="ml-2 text-gray-400">Loading dashboard…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">{error}</div>
      </div>
    );
  }

  const statsCards = [
    { label: "Active Agents", value: String(agentCount), icon: <Bot size={20} /> },
    { label: "Executions", value: String(execCount), icon: <Play size={20} /> },
    { label: "Models", value: String(modelCount), icon: <Cpu size={20} /> },
    { label: "DLP Policies", value: String(policiesCount), icon: <ShieldCheck size={20} /> },
  ];

  const quickActions = [
    { label: "Create Agent", icon: <Plus size={16} />, path: "/agents" },
    { label: "Run Agent", icon: <Play size={16} />, path: "/executions" },
    { label: "Browse Templates", icon: <Layers size={16} />, path: "/templates" },
    { label: "View Models", icon: <Cpu size={16} />, path: "/router" },
  ];

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center gap-3">
        <LayoutDashboard size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
      </div>

      {/* Stats Cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statsCards.map((s) => (
          <div key={s.label} className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-gray-400">{s.label}</span>
              <span className="text-purple-400">{s.icon}</span>
            </div>
            <p className="text-2xl font-bold text-white">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
        <h2 className="mb-3 text-sm font-semibold text-white">Quick Actions</h2>
        <div className="flex flex-wrap gap-3">
          {quickActions.map((action) => (
            <Button
              key={action.label}
              variant="outline"
              size="sm"
              onClick={() => navigate(action.path)}
              className="gap-2"
            >
              {action.icon}
              {action.label}
              <ArrowRight size={14} className="ml-1 opacity-50" />
            </Button>
          ))}
        </div>
      </div>

      {/* System Health */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
        <h2 className="mb-3 text-sm font-semibold text-white">System Health</h2>
        <div className="flex flex-wrap gap-6">
          {(["api", "database", "redis", "vault"] as const).map((service) => (
            <div key={service} className="flex items-center gap-2">
              <HealthDot ok={health ? health[service] : null} />
              <span className="text-sm capitalize text-gray-300">{service === "api" ? "API" : service}</span>
              {health && (
                health[service]
                  ? <CheckCircle2 size={14} className="text-green-500" />
                  : <XCircle size={14} className="text-red-500" />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {/* Recent Agents */}
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="border-b border-[#2a2d37] px-4 py-3">
            <h2 className="text-sm font-semibold text-white">Recent Agents</h2>
          </div>
          <div className="overflow-x-auto">
            {agents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12">
                <Bot size={32} className="mb-3 text-gray-600" />
                <p className="mb-1 text-sm font-medium text-gray-400">No agents yet</p>
                <p className="mb-4 text-xs text-gray-500">Get started by creating your first agent</p>
                <Button size="sm" onClick={() => navigate("/agents")} className="gap-2">
                  <Plus size={14} />
                  Create Agent
                </Button>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium text-right">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((a) => (
                    <tr key={a.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                      <td className="px-4 py-2 font-medium text-white">{a.name}</td>
                      <td className="px-4 py-2">{statusBadge(a.status)}</td>
                      <td className="px-4 py-2 text-right text-gray-400">{new Date(a.updated_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Recent Executions */}
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="border-b border-[#2a2d37] px-4 py-3">
            <h2 className="text-sm font-semibold text-white">Recent Executions</h2>
          </div>
          <div className="overflow-x-auto">
            {executions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12">
                <Play size={32} className="mb-3 text-gray-600" />
                <p className="mb-1 text-sm font-medium text-gray-400">No executions yet</p>
                <p className="mb-4 text-xs text-gray-500">Run an agent to see execution results here</p>
                <Button size="sm" onClick={() => navigate("/executions")} className="gap-2">
                  <Play size={14} />
                  Run Agent
                </Button>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                    <th className="px-4 py-2 font-medium">Agent</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Duration</th>
                    <th className="px-4 py-2 font-medium text-right">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {executions.map((e) => (
                    <tr key={e.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                      <td className="px-4 py-2 font-medium text-white">{e.agent_id}</td>
                      <td className="px-4 py-2">{statusBadge(e.status)}</td>
                      <td className="px-4 py-2 text-gray-400">{formatDuration(e.duration_ms)}</td>
                      <td className="px-4 py-2 text-right text-gray-400">{new Date(e.started_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Recent Activity Feed */}
      <div className="mt-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Recent Activity</h2>
        </div>
        <div className="p-4">
          {auditEvents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8">
              <Activity size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No recent activity</p>
            </div>
          ) : (
            <ul className="space-y-3">
              {auditEvents.map((event) => (
                <li key={event.id} className="flex items-start gap-3">
                  <Activity size={16} className="mt-0.5 shrink-0 text-purple-400" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-white">
                      <span className="font-medium">{event.action}</span>
                      <span className="text-gray-400"> on </span>
                      <span className="text-gray-300">{event.resource_type}</span>
                    </p>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <Clock size={12} />
                      <span>{relativeTime(event.created_at)}</span>
                      {event.actor && <span>· {event.actor}</span>}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
