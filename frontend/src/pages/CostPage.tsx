import { useState, useEffect } from "react";
import {
  DollarSign,
  AlertTriangle,
} from "lucide-react";
import { apiGet, apiPost } from "@/api/client";
import { SummaryCards } from "@/components/cost/SummaryCards";
import { UsageChart } from "@/components/cost/UsageChart";
import { BreakdownTable } from "@/components/cost/BreakdownTable";
import { TopConsumers } from "@/components/cost/TopConsumers";
import { BudgetWizard, type BudgetFormData } from "@/components/cost/BudgetWizard";
import { BudgetList } from "@/components/cost/BudgetList";
import { ExportButton } from "@/components/cost/ExportButton";

interface UsageEntry {
  id: string;
  model_id: string;
  agent_id: string;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  currency: string;
  recorded_at: string;
}

interface BudgetItem {
  id: string;
  name: string;
  scope: string;
  limit_amount: number;
  spent_amount: number;
  currency: string;
  period: string;
  enforcement: string;
  is_active: boolean;
  created_at: string;
  alert_thresholds?: number[];
  utilization_pct?: number;
  utilization_color?: string;
}

interface CostAlertItem {
  id: string;
  message: string;
  severity: string;
  created_at: string;
}

interface PricingEntry {
  id: string;
  model_id: string;
  cost_per_input_token: number;
  cost_per_output_token: number;
}

interface BreakdownEntry {
  name: string;
  tokens_used: number;
  cost: number;
  pct_of_total: number;
}

interface CostSummaryData {
  total_spend: number;
  budget_limit: number;
  budget_used_pct: number;
  projected_spend: number;
  top_model: string;
  daily_spend: { date: string; amount: number }[];
  breakdown_by_agent: BreakdownEntry[];
  breakdown_by_model: BreakdownEntry[];
  breakdown_by_user: BreakdownEntry[];
}

interface ChartPoint {
  date: string;
  [provider: string]: string | number;
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function formatTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function CostPage() {
  const [usage, setUsage] = useState<UsageEntry[]>([]);
  const [budgets, setBudgets] = useState<BudgetItem[]>([]);
  const [alerts, setAlerts] = useState<CostAlertItem[]>([]);
  const [pricing, setPricing] = useState<PricingEntry[]>([]);
  const [summary, setSummary] = useState<CostSummaryData | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [chartProviders, setChartProviders] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showBudgetWizard, setShowBudgetWizard] = useState(false);

  async function fetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [usageRes, budgetsRes, alertsRes, pricingRes, summaryRes, chartRes] = await Promise.allSettled([
        apiGet<UsageEntry[]>("/cost/usage"),
        apiGet<BudgetItem[]>("/cost/api/v1/cost/budgets"),
        apiGet<CostAlertItem[]>("/cost/alerts"),
        apiGet<PricingEntry[]>("/cost/pricing"),
        apiGet<CostSummaryData>("/cost/summary"),
        apiGet<{ providers: string[]; series: ChartPoint[] }>("/cost/api/v1/cost/chart"),
      ]);
      if (usageRes.status === "fulfilled") setUsage(Array.isArray(usageRes.value.data) ? usageRes.value.data : []);
      if (budgetsRes.status === "fulfilled") setBudgets(Array.isArray(budgetsRes.value.data) ? budgetsRes.value.data : []);
      if (alertsRes.status === "fulfilled") setAlerts(Array.isArray(alertsRes.value.data) ? alertsRes.value.data : []);
      if (pricingRes.status === "fulfilled") setPricing(Array.isArray(pricingRes.value.data) ? pricingRes.value.data : []);
      if (summaryRes.status === "fulfilled" && summaryRes.value.data) setSummary(summaryRes.value.data as CostSummaryData);
      if (chartRes.status === "fulfilled" && chartRes.value.data) {
        const cd = chartRes.value.data as { providers: string[]; series: ChartPoint[] };
        setChartProviders(cd.providers || []);
        setChartData(cd.series || []);
      }
    } catch {
      setError("Failed to load cost data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchAll(); }, []);

  async function handleCreateBudget(data: BudgetFormData) {
    try {
      await apiPost("/cost/api/v1/cost/budgets", data);
      setShowBudgetWizard(false);
      await fetchAll();
    } catch {
      setError("Failed to create budget.");
    }
  }

  async function handleExport(format: "csv" | "pdf") {
    try {
      if (format === "csv") {
        const res = await fetch("/api/v1/cost/api/v1/cost/export?format=csv", { credentials: "include" });
        if (!res.ok) throw new Error("Export failed");
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "cost_report.csv";
        a.click();
        URL.revokeObjectURL(url);
      } else {
        await apiGet("/cost/api/v1/cost/export", { format: "pdf" });
      }
    } catch {
      setError("Failed to export report.");
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading...</p>
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

  // Build breakdown data for the BreakdownTable
  const breakdownByModel = summary?.breakdown_by_model ?? [];
  const breakdownByAgent = summary?.breakdown_by_agent ?? [];
  const breakdownByUser = summary?.breakdown_by_user ?? [];

  // Top consumers from model breakdown
  const topConsumers = [...breakdownByModel].sort((a, b) => b.cost - a.cost).slice(0, 10);

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <DollarSign size={24} className="text-purple-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Cost &amp; Budget</h1>
            <p className="text-sm text-gray-400">Track token usage, set spending limits, and manage cost alerts.</p>
          </div>
        </div>
        <ExportButton onExport={handleExport} />
      </div>

      {/* Summary Cards */}
      {summary && (
        <SummaryCards
          totalSpend={summary.total_spend}
          budgetUsedPct={summary.budget_used_pct}
          projectedSpend={summary.projected_spend}
          topModel={summary.top_model}
        />
      )}

      {/* Usage Chart — stacked area by provider */}
      <UsageChart series={chartData} providers={chartProviders} />

      {/* Usage Table */}
      <div className="mb-6 rounded-lg border border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Usage</h2>
        </div>
        <div className="overflow-x-auto">
          {usage.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <DollarSign size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No usage data yet.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Model</th>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium text-right">Input Tokens</th>
                  <th className="px-4 py-2 font-medium text-right">Output Tokens</th>
                  <th className="px-4 py-2 font-medium text-right">Cost</th>
                  <th className="px-4 py-2 font-medium text-right">Recorded</th>
                </tr>
              </thead>
              <tbody>
                {usage.map((u) => (
                  <tr key={u.id} className="border-b border-surface-border hover:bg-white/5">
                    <td className="px-4 py-2 font-medium text-white">{u.model_id}</td>
                    <td className="px-4 py-2 text-gray-400">{u.agent_id}</td>
                    <td className="px-4 py-2 text-right text-gray-400">{formatTokens(u.input_tokens)}</td>
                    <td className="px-4 py-2 text-right text-gray-400">{formatTokens(u.output_tokens)}</td>
                    <td className="px-4 py-2 text-right font-medium text-green-400">{formatCurrency(u.total_cost)}</td>
                    <td className="px-4 py-2 text-right text-gray-400">{new Date(u.recorded_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Budgets with Wizard */}
      <BudgetList
        budgets={budgets}
        showWizard={showBudgetWizard}
        onToggleWizard={() => setShowBudgetWizard(!showBudgetWizard)}
      >
        <BudgetWizard
          onSubmit={handleCreateBudget}
          onCancel={() => setShowBudgetWizard(false)}
        />
      </BudgetList>

      {/* Cost Breakdown Table with switchable tabs */}
      {summary && (
        <BreakdownTable
          breakdownByModel={breakdownByModel}
          breakdownByAgent={breakdownByAgent}
          breakdownByUser={breakdownByUser}
          breakdownByTeam={[]}
        />
      )}

      {/* Top Consumers — horizontal bar chart */}
      {topConsumers.length > 0 && <TopConsumers data={topConsumers} />}

      {/* Alerts */}
      <div className="mb-6 rounded-lg border border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Alerts</h2>
        </div>
        {alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <AlertTriangle size={32} className="mb-2 text-gray-600" />
            <p className="text-sm text-gray-500">No cost alerts.</p>
          </div>
        ) : (
          <div className="divide-y divide-[#2a2d37]">
            {alerts.map((a) => (
              <div key={a.id} className="flex items-center gap-3 px-4 py-3">
                <AlertTriangle size={16} className={a.severity === "critical" ? "text-red-400" : "text-yellow-400"} />
                <div className="flex-1">
                  <p className="text-sm text-white">{a.message}</p>
                  <p className="text-xs text-gray-500">{new Date(a.created_at).toLocaleString()}</p>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${a.severity === "critical" ? "bg-red-500/20 text-red-400" : "bg-yellow-500/20 text-yellow-400"}`}>
                  {a.severity}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Pricing */}
      {pricing.length > 0 && (
        <div className="rounded-lg border border-surface-border bg-surface-raised">
          <div className="border-b border-surface-border px-4 py-3">
            <h2 className="text-sm font-semibold text-white">Pricing</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Model</th>
                  <th className="px-4 py-2 font-medium text-right">Input $/1K</th>
                  <th className="px-4 py-2 font-medium text-right">Output $/1K</th>
                </tr>
              </thead>
              <tbody>
                {pricing.map((p) => (
                  <tr key={p.id} className="border-b border-surface-border hover:bg-white/5">
                    <td className="px-4 py-2 font-medium text-white">{p.model_id}</td>
                    <td className="px-4 py-2 text-right text-gray-400">${(p.cost_per_input_token * 1000).toFixed(4)}</td>
                    <td className="px-4 py-2 text-right text-gray-400">${(p.cost_per_output_token * 1000).toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
