import { useState } from "react";
import { BarChart3 } from "lucide-react";

interface ChartPoint {
  date: string;
  [provider: string]: string | number;
}

interface UsageChartProps {
  series: ChartPoint[];
  providers: string[];
}

const PROVIDER_COLORS: Record<string, string> = {
  openai: "#10b981",
  anthropic: "#8b5cf6",
  google: "#3b82f6",
  azure: "#f59e0b",
};

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

type Granularity = "daily" | "weekly" | "monthly";

export function UsageChart({ series, providers }: UsageChartProps) {
  const [granularity, setGranularity] = useState<Granularity>("daily");

  const maxValue = Math.max(
    ...series.map((p) =>
      providers.reduce((sum, prov) => sum + (Number(p[prov]) || 0), 0)
    ),
    1
  );

  return (
    <div className="mb-6 rounded-lg border border-surface-border bg-surface-raised">
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <BarChart3 size={14} /> Usage by Provider
        </h2>
        <div className="flex gap-1">
          {(["daily", "weekly", "monthly"] as const).map((g) => (
            <button
              key={g}
              onClick={() => setGranularity(g)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                granularity === g
                  ? "bg-purple-600 text-white"
                  : "text-gray-400 hover:bg-white/5 hover:text-white"
              }`}
            >
              {g.charAt(0).toUpperCase() + g.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <div className="px-4 py-4">
        {series.length === 0 ? (
          <p className="text-center text-sm text-gray-500">No chart data available.</p>
        ) : (
          <>
            {/* Stacked bar chart */}
            <div className="flex items-end gap-1" style={{ height: 160 }}>
              {series.map((point) => {
                const total = providers.reduce((sum, p) => sum + (Number(point[p]) || 0), 0);
                return (
                  <div key={String(point.date)} className="flex flex-1 flex-col items-center gap-1" title={formatCurrency(total)}>
                    <span className="text-[9px] text-gray-400">{formatCurrency(total)}</span>
                    <div className="flex w-full flex-col-reverse" style={{ height: `${Math.max((total / maxValue) * 100, 2)}%`, minHeight: 4 }}>
                      {providers.map((prov) => {
                        const val = Number(point[prov]) || 0;
                        const pct = total > 0 ? (val / total) * 100 : 0;
                        return (
                          <div
                            key={prov}
                            className="w-full first:rounded-b last:rounded-t"
                            style={{
                              height: `${pct}%`,
                              backgroundColor: PROVIDER_COLORS[prov] || "#6b7280",
                              minHeight: val > 0 ? 2 : 0,
                            }}
                            title={`${prov}: ${formatCurrency(val)}`}
                          />
                        );
                      })}
                    </div>
                    <span className="text-[9px] text-gray-500">{String(point.date).slice(-5)}</span>
                  </div>
                );
              })}
            </div>
            {/* Legend */}
            <div className="mt-3 flex flex-wrap gap-3">
              {providers.map((p) => (
                <div key={p} className="flex items-center gap-1.5 text-xs text-gray-400">
                  <div className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: PROVIDER_COLORS[p] || "#6b7280" }} />
                  {p}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
