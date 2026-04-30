/**
 * CostDashboard — at-a-glance spend dashboard.
 *
 * Surfaces:
 *   - Per-tenant total spend for the current period (header card)
 *   - Top 10 most expensive runs (sourced from /cost/usage rolled up)
 *   - Token breakdown (prompt vs completion) per provider
 *   - Cost-gate blocked count (sourced from /cost/alerts; falls back to 0)
 *   - 24h sparkline (sourced from /cost/chart granularity=daily)
 *   - Per-tenant filter (admin only)
 *
 * The dashboard is read-only — it does NOT mutate any backend state.
 * For budget management see the existing ``CostPage``.
 */

import { useMemo, useState } from "react";
import {
  DollarSign,
  ShieldAlert,
  TrendingUp,
  Users,
  Loader2,
} from "lucide-react";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useCostSummary } from "@/hooks/useArtifacts";
import { useApiQuery } from "@/hooks/useApi";
import { apiGet } from "@/api/client";
import type { CostSummary } from "@/types/artifacts";

interface CostDashboardProps {
  /** When set, the dashboard locks to this tenant. The admin filter
   *  override only applies when this is undefined. */
  tenantId?: string;
  /** Show the per-tenant filter input. Default: false (admin-only). */
  showTenantFilter?: boolean;
}

interface UsageEntry {
  id: string;
  execution_id?: string | null;
  model_id: string;
  agent_id?: string | null;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  provider?: string;
  recorded_at?: string;
  created_at?: string;
}

interface AlertEntry {
  id: string;
  message: string;
  severity: string;
  created_at: string;
  /** Some backends use ``alert_type=cost_gate_blocked``. */
  alert_type?: string;
}

interface ChartPoint {
  date: string;
  [provider: string]: string | number;
}

interface ChartData {
  granularity: string;
  providers: string[];
  series: ChartPoint[];
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value);
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function buildPeriodParams(period: string): {
  since?: string;
  until?: string;
} {
  // ``period`` accepts the ISO month form ``YYYY-MM``. Fall back to the
  // last 30 days when the format is unrecognised.
  const m = period.match(/^(\d{4})-(\d{2})$/);
  if (m && m[1] && m[2]) {
    const start = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1));
    const end = new Date(Date.UTC(Number(m[1]), Number(m[2]), 1));
    return { since: start.toISOString(), until: end.toISOString() };
  }
  return {};
}

export function CostDashboard({
  tenantId,
  showTenantFilter = false,
}: CostDashboardProps) {
  const [tenantFilter, setTenantFilter] = useState<string>(tenantId ?? "");
  const [period, setPeriod] = useState<string>(() => {
    const now = new Date();
    return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
  });

  const periodWindow = useMemo(() => buildPeriodParams(period), [period]);
  const effectiveTenant = tenantId ?? tenantFilter;

  // Cost summary (typed)
  const summaryQuery = useCostSummary({
    tenant_id: effectiveTenant || undefined,
    since: periodWindow.since,
    until: periodWindow.until,
    group_by: "provider",
  });

  // Top runs (rolled up from the ledger surface)
  const usageQuery = useApiQuery<UsageEntry[]>(
    ["cost-dashboard-usage", periodWindow.since, periodWindow.until, effectiveTenant],
    () =>
      apiGet<UsageEntry[]>("/cost/usage", {
        limit: 100,
        ...(periodWindow.since ? { since: periodWindow.since } : {}),
        ...(periodWindow.until ? { until: periodWindow.until } : {}),
      }),
  );

  // Cost-gate alerts (treat all critical alerts as blocked-execution events
  // when no specific ``alert_type`` is set).
  const alertsQuery = useApiQuery<AlertEntry[]>(
    ["cost-dashboard-alerts", effectiveTenant],
    () => apiGet<AlertEntry[]>("/cost/alerts", { limit: 100 }),
  );

  // 24h sparkline — use the chart endpoint, granularity=daily.
  const chartQuery = useApiQuery<ChartData>(
    ["cost-dashboard-chart", effectiveTenant],
    () => apiGet<ChartData>("/cost/chart", { granularity: "daily" }),
  );

  const summary: CostSummary | undefined = summaryQuery.data;
  const usageEntries = usageQuery.data?.data ?? [];
  const alerts = alertsQuery.data?.data ?? [];
  const chart = chartQuery.data?.data;

  // Top 10 most expensive runs by total_cost. Ledger entries are per-call;
  // group by execution_id and sum.
  const topRuns = useMemo(() => {
    const byRun = new Map<
      string,
      { run_id: string; total_cost: number; calls: number; model: string }
    >();
    for (const e of usageEntries) {
      const id = e.execution_id ?? null;
      if (!id) continue;
      const existing = byRun.get(id);
      if (existing) {
        existing.total_cost += Number(e.total_cost ?? 0);
        existing.calls += 1;
      } else {
        byRun.set(id, {
          run_id: id,
          total_cost: Number(e.total_cost ?? 0),
          calls: 1,
          model: e.model_id,
        });
      }
    }
    return Array.from(byRun.values())
      .sort((a, b) => b.total_cost - a.total_cost)
      .slice(0, 10);
  }, [usageEntries]);

  // Token breakdown per provider.
  const tokenByProvider = useMemo(() => {
    const map = new Map<
      string,
      { provider: string; input: number; output: number }
    >();
    for (const e of usageEntries) {
      const p = e.provider ?? "unknown";
      const existing = map.get(p);
      if (existing) {
        existing.input += Number(e.input_tokens ?? 0);
        existing.output += Number(e.output_tokens ?? 0);
      } else {
        map.set(p, {
          provider: p,
          input: Number(e.input_tokens ?? 0),
          output: Number(e.output_tokens ?? 0),
        });
      }
    }
    return Array.from(map.values()).sort(
      (a, b) => b.input + b.output - (a.input + a.output),
    );
  }, [usageEntries]);

  const blockedCount = useMemo(() => {
    return alerts.filter((a) => {
      if (a.alert_type) return a.alert_type === "cost_gate_blocked";
      return a.severity === "critical";
    }).length;
  }, [alerts]);

  // Sparkline: last 24 buckets from the chart endpoint, summed across providers.
  const sparkline = useMemo(() => {
    if (!chart || !Array.isArray(chart.series)) return [];
    return chart.series.slice(-24).map((p) => {
      let total = 0;
      for (const prov of chart.providers) {
        total += Number(p[prov] ?? 0);
      }
      return { date: String(p.date), total };
    });
  }, [chart]);

  const sparkMax = sparkline.reduce((m, p) => Math.max(m, p.total), 0) || 1;

  const isLoading =
    summaryQuery.isLoading ||
    usageQuery.isLoading ||
    alertsQuery.isLoading ||
    chartQuery.isLoading;

  const isEmpty =
    !isLoading &&
    (!summary || summary.total_cost === 0) &&
    usageEntries.length === 0;

  return (
    <div className="space-y-4" data-testid="cost-dashboard">
      {/* Header / filters */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-surface-border bg-surface-raised p-4">
        <div>
          <Label htmlFor="period" className="mb-1 block text-xs">
            Period (YYYY-MM)
          </Label>
          <Input
            id="period"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            placeholder="2025-04"
            className="w-32"
          />
        </div>
        {showTenantFilter && !tenantId && (
          <div>
            <Label htmlFor="tenant" className="mb-1 block text-xs">
              Tenant ID
            </Label>
            <Input
              id="tenant"
              value={tenantFilter}
              onChange={(e) => setTenantFilter(e.target.value)}
              placeholder="all tenants"
              className="w-64"
            />
          </div>
        )}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={<DollarSign size={14} />}
          label="Total spend"
          value={summary ? formatCurrency(summary.total_cost) : "—"}
          loading={summaryQuery.isLoading}
        />
        <SummaryCard
          icon={<Users size={14} />}
          label="Calls"
          value={summary ? String(summary.call_count) : "—"}
          loading={summaryQuery.isLoading}
        />
        <SummaryCard
          icon={<TrendingUp size={14} />}
          label="Tokens"
          value={
            summary
              ? formatTokens(
                  summary.total_input_tokens + summary.total_output_tokens,
                )
              : "—"
          }
          loading={summaryQuery.isLoading}
        />
        <SummaryCard
          icon={<ShieldAlert size={14} />}
          label="Cost-gate blocked"
          value={String(blockedCount)}
          loading={alertsQuery.isLoading}
          tone={blockedCount > 0 ? "warn" : "ok"}
        />
      </div>

      {/* Sparkline */}
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
        <h3 className="mb-3 text-sm font-semibold text-white">
          Spend (last 24 buckets)
        </h3>
        {chartQuery.isLoading ? (
          <div className="flex items-center justify-center py-8 text-gray-400">
            <Loader2 size={16} className="mr-2 animate-spin" /> Loading…
          </div>
        ) : sparkline.length === 0 ? (
          <p className="py-4 text-center text-xs text-gray-500">
            No spend recorded.
          </p>
        ) : (
          <div
            data-testid="cost-sparkline"
            className="flex h-24 items-end gap-1"
          >
            {sparkline.map((p) => {
              const pct = (p.total / sparkMax) * 100;
              return (
                <div
                  key={p.date}
                  className="flex-1 rounded-t bg-green-500/60 hover:bg-green-400"
                  style={{ height: `${Math.max(pct, 2)}%` }}
                  title={`${p.date}: ${formatCurrency(p.total)}`}
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Top runs */}
      <div className="rounded-lg border border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-3">
          <h3 className="text-sm font-semibold text-white">
            Top 10 most expensive runs
          </h3>
        </div>
        {usageQuery.isLoading ? (
          <div className="flex items-center justify-center py-8 text-gray-400">
            <Loader2 size={16} className="mr-2 animate-spin" /> Loading…
          </div>
        ) : topRuns.length === 0 ? (
          <p
            data-testid="top-runs-empty"
            className="py-8 text-center text-sm text-gray-500"
          >
            No runs with recorded cost.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Run</th>
                <th className="px-4 py-2 font-medium">Model</th>
                <th className="px-4 py-2 font-medium text-right">Calls</th>
                <th className="px-4 py-2 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {topRuns.map((r) => (
                <tr
                  key={r.run_id}
                  className="border-b border-surface-border hover:bg-white/5"
                >
                  <td className="px-4 py-2 font-mono text-xs text-gray-300">
                    {r.run_id.slice(0, 8)}…
                  </td>
                  <td className="px-4 py-2 text-gray-200">{r.model}</td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {r.calls}
                  </td>
                  <td className="px-4 py-2 text-right font-medium text-green-300">
                    {formatCurrency(r.total_cost)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Token breakdown by provider */}
      <div className="rounded-lg border border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-3">
          <h3 className="text-sm font-semibold text-white">
            Tokens by provider
          </h3>
        </div>
        {tokenByProvider.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-500">
            No token usage recorded.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Provider</th>
                <th className="px-4 py-2 font-medium text-right">Input</th>
                <th className="px-4 py-2 font-medium text-right">Output</th>
                <th className="px-4 py-2 font-medium text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {tokenByProvider.map((p) => (
                <tr
                  key={p.provider}
                  className="border-b border-surface-border"
                >
                  <td className="px-4 py-2 capitalize text-gray-200">
                    {p.provider}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {formatTokens(p.input)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {formatTokens(p.output)}
                  </td>
                  <td className="px-4 py-2 text-right font-medium text-white">
                    {formatTokens(p.input + p.output)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {isEmpty && (
        <p
          data-testid="cost-empty-state"
          className="rounded-lg border border-dashed border-surface-border bg-surface-raised/50 p-6 text-center text-sm text-gray-500"
        >
          No costs recorded for the selected period.
        </p>
      )}
    </div>
  );
}

interface SummaryCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  loading?: boolean;
  tone?: "ok" | "warn";
}

function SummaryCard({
  icon,
  label,
  value,
  loading,
  tone = "ok",
}: SummaryCardProps) {
  const valueClass =
    tone === "warn"
      ? "text-2xl font-bold text-red-300"
      : "text-2xl font-bold text-white";
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
      <div className="mb-1 flex items-center gap-2 text-xs text-gray-400">
        {icon}
        {label}
      </div>
      <div className={valueClass}>
        {loading ? (
          <Loader2 size={16} className="animate-spin text-gray-400" />
        ) : (
          value
        )}
      </div>
    </div>
  );
}
