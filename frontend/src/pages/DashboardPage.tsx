import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Bot,
  Play,
  Cpu,
  DollarSign,
  Loader2,
  Sparkles,
} from "lucide-react";
import { apiGet } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { NLAgentWizard } from "@/components/wizard/NLAgentWizard";
import { StatCard } from "@/components/dashboard/StatCard";
import { QuickActions } from "@/components/dashboard/QuickActions";
import { ActivityFeed } from "@/components/dashboard/ActivityFeed";
import { HealthIndicators, type ServiceHealth } from "@/components/dashboard/HealthIndicators";
import { AgentLeaderboard, type LeaderboardAgent } from "@/components/dashboard/AgentLeaderboard";
import { CostWidget, type DailyCost } from "@/components/dashboard/CostWidget";
import { RunAgentDialog } from "@/components/dashboard/RunAgentDialog";
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
  agent_name?: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

interface ModelEntry {
  id: string;
}

interface CostSummaryResponse {
  total_cost?: number;
  total_cost_usd?: number;
  currency?: string;
}

interface ChartPoint {
  date: string;
  total?: number;
  [key: string]: string | number | undefined;
}

interface HealthResponse {
  api?: boolean;
  database?: boolean;
  db?: boolean;
  redis?: boolean;
  vault?: boolean;
  keycloak?: boolean;
  sso?: boolean;
}

export function DashboardPage() {
  const navigate = useNavigate();
  const [showWizard, setShowWizard] = useState(false);
  const [showRunDialog, setShowRunDialog] = useState(false);

  const [agentCount, setAgentCount] = useState<number>(0);
  const [execTodayCount, setExecTodayCount] = useState<number>(0);
  const [modelCount, setModelCount] = useState<number>(0);
  const [totalCost, setTotalCost] = useState<number>(0);
  const [auditEvents, setAuditEvents] = useState<AuditEntry[]>([]);
  const [healthServices, setHealthServices] = useState<ServiceHealth[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardAgent[]>([]);
  const [dailyCosts, setDailyCosts] = useState<DailyCost[]>([]);
  const [costThisWeek, setCostThisWeek] = useState<number>(0);
  const [costLastWeek, setCostLastWeek] = useState<number>(0);

  // Trend data
  const [agentTrend, setAgentTrend] = useState<number | null>(null);
  const [execTrend, setExecTrend] = useState<number | null>(null);
  const [modelTrend, setModelTrend] = useState<number | null>(null);
  const [costTrend, setCostTrend] = useState<number | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const today = new Date();
    const todayStr = today.toISOString().split("T")[0];
    const weekAgo = new Date(today);
    weekAgo.setDate(weekAgo.getDate() - 7);
    const twoWeeksAgo = new Date(today);
    twoWeeksAgo.setDate(twoWeeksAgo.getDate() - 14);

    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const [agentsRes, execsRes, modelsRes, auditRes, costSummaryRes, costChartRes] =
          await Promise.allSettled([
            apiGet<Agent[]>("/agents/", { limit: 100 }),
            apiGet<Execution[]>("/executions", { limit: 100 }),
            apiGet<ModelEntry[]>("/router/models", { limit: 100 }),
            apiGet<AuditEntry[]>("/governance/audit", { limit: 10 }),
            apiGet<CostSummaryResponse>("/cost/api/v1/cost/summary", {
              since: weekAgo.toISOString(),
              until: today.toISOString(),
            }),
            apiGet<{ series: ChartPoint[] }>("/cost/api/v1/cost/chart", {
              granularity: "day",
              since: weekAgo.toISOString(),
              until: today.toISOString(),
            }),
          ]);

        // Agents
        if (agentsRes.status === "fulfilled") {
          const data = agentsRes.value.data;
          const agents = Array.isArray(data) ? data : [];
          const activeAgents = agents.filter((a) => a.status === "active");
          setAgentCount(activeAgents.length);
          setAgentTrend(agents.length > 0 ? Math.round((activeAgents.length / agents.length) * 100 - 50) : null);

          // Build leaderboard from executions
          if (execsRes.status === "fulfilled") {
            const execData = execsRes.value.data;
            const execs = Array.isArray(execData) ? execData : [];

            // Count today's executions
            const todayExecs = execs.filter((e) => e.started_at?.startsWith(todayStr));
            setExecTodayCount(
              execsRes.value.meta?.pagination?.total != null
                ? todayExecs.length
                : todayExecs.length,
            );
            setExecTrend(todayExecs.length > 0 ? Math.min(todayExecs.length * 10, 100) : 0);

            // Build agent leaderboard
            const agentExecCounts = new Map<string, number>();
            for (const exec of execs) {
              agentExecCounts.set(exec.agent_id, (agentExecCounts.get(exec.agent_id) ?? 0) + 1);
            }
            const lb: LeaderboardAgent[] = [];
            for (const [agentId, count] of agentExecCounts.entries()) {
              const agent = agents.find((a) => a.id === agentId);
              lb.push({
                id: agentId,
                name: agent?.name ?? agentId.slice(0, 8),
                execution_count: count,
              });
            }
            lb.sort((a, b) => b.execution_count - a.execution_count);
            setLeaderboard(lb.slice(0, 5));
          }
        }

        // Models
        if (modelsRes.status === "fulfilled") {
          const count =
            modelsRes.value.meta?.pagination?.total ??
            (Array.isArray(modelsRes.value.data) ? modelsRes.value.data.length : 0);
          setModelCount(count);
          setModelTrend(count > 0 ? 0 : null);
        }

        // Audit
        if (auditRes.status === "fulfilled") {
          const data = auditRes.value.data;
          setAuditEvents(Array.isArray(data) ? data : []);
        }

        // Cost summary
        if (costSummaryRes.status === "fulfilled") {
          const summary = costSummaryRes.value.data;
          const cost = (summary as CostSummaryResponse)?.total_cost ?? (summary as CostSummaryResponse)?.total_cost_usd ?? 0;
          setTotalCost(cost);
          setCostThisWeek(cost);
          setCostTrend(cost > 0 ? 0 : null);
        }

        // Cost chart (daily)
        if (costChartRes.status === "fulfilled") {
          const chartData = costChartRes.value.data;
          if (chartData && Array.isArray(chartData.series)) {
            const costs: DailyCost[] = chartData.series.map((pt) => ({
              date: pt.date,
              cost: pt.total ?? Object.values(pt).reduce((sum, v) => sum + (typeof v === "number" ? v : 0), 0),
            }));
            setDailyCosts(costs);
          }
        }

        // Fetch last week cost for comparison
        try {
          const lastWeekRes = await apiGet<CostSummaryResponse>("/cost/api/v1/cost/summary", {
            since: twoWeeksAgo.toISOString(),
            until: weekAgo.toISOString(),
          });
          const lw = lastWeekRes.data;
          const lwCost = (lw as CostSummaryResponse)?.total_cost ?? (lw as CostSummaryResponse)?.total_cost_usd ?? 0;
          setCostLastWeek(lwCost);
          if (lwCost > 0) {
            const thisWeekCost = costSummaryRes.status === "fulfilled"
              ? ((costSummaryRes.value.data as CostSummaryResponse)?.total_cost ?? 0)
              : 0;
            setCostTrend(Math.round(((thisWeekCost - lwCost) / lwCost) * 100));
          }
        } catch {
          // Last week cost unavailable
        }
      } catch {
        setError("Failed to load dashboard data.");
      } finally {
        setLoading(false);
      }
    }

    async function fetchHealth() {
      try {
        const res = await fetch("/api/v1/health");
        const fallback = !res.ok ? await fetch("/ready") : res;
        const data: HealthResponse = fallback.ok ? await fallback.json() : {};

        const services: ServiceHealth[] = [
          {
            name: "api",
            displayName: "API",
            status: fallback.ok ? "healthy" : "unhealthy",
          },
          {
            name: "database",
            displayName: "Database",
            status: (data?.database ?? data?.db) === true ? "healthy" : (data?.database ?? data?.db) === false ? "unhealthy" : "unknown",
          },
          {
            name: "redis",
            displayName: "Redis",
            status: data?.redis === true ? "healthy" : data?.redis === false ? "unhealthy" : "unknown",
          },
          {
            name: "vault",
            displayName: "Vault",
            status: data?.vault === true ? "healthy" : data?.vault === false ? "unhealthy" : "unknown",
          },
          {
            name: "keycloak",
            displayName: "Keycloak",
            status: (data?.keycloak ?? data?.sso) === true ? "healthy" : (data?.keycloak ?? data?.sso) === false ? "unhealthy" : "unknown",
          },
        ];
        setHealthServices(services);
      } catch {
        setHealthServices([
          { name: "api", displayName: "API", status: "unhealthy" },
          { name: "database", displayName: "Database", status: "unknown" },
          { name: "redis", displayName: "Redis", status: "unknown" },
          { name: "vault", displayName: "Vault", status: "unknown" },
          { name: "keycloak", displayName: "Keycloak", status: "unknown" },
        ]);
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

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center gap-3">
        <LayoutDashboard size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
      </div>

      {/* Stat Cards — real data with trend arrows and click navigation */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Active Agents"
          value={agentCount}
          icon={<Bot size={20} />}
          trend={agentTrend}
          trendLabel="active rate"
          onClick={() => navigate("/agents")}
        />
        <StatCard
          label="Executions Today"
          value={execTodayCount}
          icon={<Play size={20} />}
          trend={execTrend}
          trendLabel="today"
          onClick={() => navigate("/executions")}
        />
        <StatCard
          label="Models Configured"
          value={modelCount}
          icon={<Cpu size={20} />}
          trend={modelTrend}
          trendLabel="configured"
          onClick={() => navigate("/router")}
        />
        <StatCard
          label="Total Cost This Month"
          value={`$${totalCost.toFixed(2)}`}
          icon={<DollarSign size={20} />}
          trend={costTrend}
          trendLabel="vs last week"
          onClick={() => navigate("/cost")}
        />
      </div>

      {/* Quick Actions Bar */}
      <div className="mb-6">
        <QuickActions
          onCreateAgent={() => setShowWizard(true)}
          onRunAgent={() => setShowRunDialog(true)}
        />
      </div>

      {/* Quick Start — AI Wizard */}
      <div className="mb-6 rounded-lg border border-purple-500/30 bg-gradient-to-r from-purple-500/5 to-purple-600/10 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/20">
              <Sparkles size={20} className="text-purple-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">Quick Start</h2>
              <p className="text-xs text-gray-400">Describe your agent in plain language and let AI build it for you</p>
            </div>
          </div>
          <Button
            size="sm"
            onClick={() => setShowWizard(true)}
            className="bg-purple-600 hover:bg-purple-700 gap-2"
          >
            <Sparkles size={14} />
            Create with AI ✨
          </Button>
        </div>
      </div>

      {/* System Health Indicators */}
      <div className="mb-6">
        <HealthIndicators services={healthServices} />
      </div>

      {/* Agent Leaderboard + Cost Widget */}
      <div className="mb-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
        <AgentLeaderboard agents={leaderboard} />
        <CostWidget
          dailyCosts={dailyCosts}
          totalThisWeek={costThisWeek}
          totalLastWeek={costLastWeek}
        />
      </div>

      {/* Recent Activity Feed */}
      <ActivityFeed events={auditEvents} />

      {/* NL Agent Wizard Modal */}
      {showWizard && (
        <NLAgentWizard onClose={() => setShowWizard(false)} />
      )}

      {/* Run Agent Dialog */}
      {showRunDialog && (
        <RunAgentDialog onClose={() => setShowRunDialog(false)} />
      )}
    </div>
  );
}
