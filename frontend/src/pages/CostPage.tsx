import { useState, useEffect } from "react";
import {
  DollarSign,
  Wallet,
  AlertTriangle,
  Plus,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost } from "@/api/client";

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

interface Budget {
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
}

interface CostAlert {
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
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [alerts, setAlerts] = useState<CostAlert[]>([]);
  const [pricing, setPricing] = useState<PricingEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateBudget, setShowCreateBudget] = useState(false);
  const [creating, setCreating] = useState(false);
  const [budgetForm, setBudgetForm] = useState({
    name: "",
    scope: "global",
    limit_amount: "",
    currency: "USD",
    period: "monthly",
    enforcement: "soft",
  });

  async function fetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [usageRes, budgetsRes, alertsRes, pricingRes] = await Promise.allSettled([
        apiGet<UsageEntry[]>("/cost/usage"),
        apiGet<Budget[]>("/cost/budgets"),
        apiGet<CostAlert[]>("/cost/alerts"),
        apiGet<PricingEntry[]>("/cost/pricing"),
      ]);
      if (usageRes.status === "fulfilled") setUsage(Array.isArray(usageRes.value.data) ? usageRes.value.data : []);
      if (budgetsRes.status === "fulfilled") setBudgets(Array.isArray(budgetsRes.value.data) ? budgetsRes.value.data : []);
      if (alertsRes.status === "fulfilled") setAlerts(Array.isArray(alertsRes.value.data) ? alertsRes.value.data : []);
      if (pricingRes.status === "fulfilled") setPricing(Array.isArray(pricingRes.value.data) ? pricingRes.value.data : []);
    } catch {
      setError("Failed to load cost data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchAll(); }, []);

  async function handleCreateBudget(e: React.FormEvent) {
    e.preventDefault();
    const limit = parseFloat(budgetForm.limit_amount);
    if (!budgetForm.name || isNaN(limit) || limit <= 0) return;
    setCreating(true);
    try {
      await apiPost("/cost/budgets", {
        name: budgetForm.name,
        scope: budgetForm.scope,
        limit_amount: limit,
        currency: budgetForm.currency,
        period: budgetForm.period,
        enforcement: budgetForm.enforcement,
        is_active: true,
      });
      setBudgetForm({ name: "", scope: "global", limit_amount: "", currency: "USD", period: "monthly", enforcement: "soft" });
      setShowCreateBudget(false);
      await fetchAll();
    } catch {
      setError("Failed to create budget.");
    } finally {
      setCreating(false);
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

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center gap-3">
        <DollarSign size={24} className="text-purple-400" />
        <div>
          <h1 className="text-2xl font-bold text-white">Cost &amp; Budget</h1>
          <p className="text-sm text-gray-400">Track token usage, set spending limits, and manage cost alerts.</p>
        </div>
      </div>

      {/* Usage Table */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
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
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
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
                  <tr key={u.id} className="border-b border-[#2a2d37] hover:bg-white/5">
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

      {/* Budgets */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Budgets</h2>
          <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowCreateBudget(!showCreateBudget)}>
            {showCreateBudget ? <><X size={14} className="mr-1.5" /> Cancel</> : <><Plus size={14} className="mr-1.5" /> Create Budget</>}
          </Button>
        </div>

        {showCreateBudget && (
          <form onSubmit={handleCreateBudget} className="border-b border-[#2a2d37] bg-[#0f1117] px-4 py-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Budget Name *</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="Production LLM" value={budgetForm.name} onChange={(e) => setBudgetForm({ ...budgetForm, name: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Scope</label>
                <select value={budgetForm.scope} onChange={(e) => setBudgetForm({ ...budgetForm, scope: e.target.value })} className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
                  <option value="global">Global</option>
                  <option value="team">Team</option>
                  <option value="project">Project</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Limit Amount *</label>
                <input type="number" min="1" className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="5000" value={budgetForm.limit_amount} onChange={(e) => setBudgetForm({ ...budgetForm, limit_amount: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Period</label>
                <select value={budgetForm.period} onChange={(e) => setBudgetForm({ ...budgetForm, period: e.target.value })} className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                  <option value="annual">Annual</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Enforcement</label>
                <select value={budgetForm.enforcement} onChange={(e) => setBudgetForm({ ...budgetForm, enforcement: e.target.value })} className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
                  <option value="soft">Soft</option>
                  <option value="hard">Hard</option>
                </select>
              </div>
              <div className="flex items-end">
                <Button type="submit" size="sm" className="w-full bg-purple-600 hover:bg-purple-700" disabled={creating}>
                  {creating ? "Creating…" : "Create Budget"}
                </Button>
              </div>
            </div>
          </form>
        )}

        <div className="divide-y divide-[#2a2d37]">
          {budgets.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Wallet size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No budgets configured yet.</p>
            </div>
          ) : (
            budgets.map((b) => {
              const pct = b.limit_amount > 0 ? Math.round(((b.spent_amount ?? 0) / b.limit_amount) * 100) : 0;
              return (
                <div key={b.id} className="px-4 py-3">
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-white">{b.name}</span>
                      <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">{b.period}</span>
                    </div>
                    <span className="text-sm font-medium text-gray-400">
                      {formatCurrency(b.spent_amount ?? 0)} / {formatCurrency(b.limit_amount)} ({pct}%)
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-white/10">
                    <div className={`h-full rounded-full transition-all ${pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-yellow-500" : "bg-green-500"}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Alerts */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
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
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="border-b border-[#2a2d37] px-4 py-3">
            <h2 className="text-sm font-semibold text-white">Pricing</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Model</th>
                  <th className="px-4 py-2 font-medium text-right">Input $/1K</th>
                  <th className="px-4 py-2 font-medium text-right">Output $/1K</th>
                </tr>
              </thead>
              <tbody>
                {pricing.map((p) => (
                  <tr key={p.id} className="border-b border-[#2a2d37] hover:bg-white/5">
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
