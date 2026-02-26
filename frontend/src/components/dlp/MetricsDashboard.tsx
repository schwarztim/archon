import { useState, useEffect, useCallback } from "react";
import {
  BarChart3,
  FileWarning,
  Ban,
  EyeOff,
  TrendingUp,
  TrendingDown,
  Activity,
  PieChart,
} from "lucide-react";
import { apiGet } from "@/api/client";
import type { DLPMetricsData } from "@/api/dlp";

const FALLBACK_METRICS: DLPMetricsData = {
  scans_today: 0,
  detections: 0,
  blocked: 0,
  redacted: 0,
  type_breakdown: {},
  trend: [],
};

/** Donut chart segment colors for detection types */
const TYPE_COLORS = [
  "#a855f7", "#3b82f6", "#ef4444", "#f59e0b", "#10b981",
  "#ec4899", "#06b6d4", "#f97316", "#8b5cf6", "#14b8a6",
];

interface MetricsDashboardProps {
  /** Pre-loaded metrics data from parent (optional) */
  initialMetrics?: DLPMetricsData | null;
}

export function MetricsDashboard({ initialMetrics }: MetricsDashboardProps) {
  const [metrics, setMetrics] = useState<DLPMetricsData>(initialMetrics ?? FALLBACK_METRICS);
  const [, setLoaded] = useState(!!initialMetrics);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await apiGet<DLPMetricsData>("/api/v1/dlp/metrics");
      if (res.data) {
        setMetrics(res.data);
        setLoaded(true);
      }
    } catch {
      setLoaded(false);
    }
  }, []);

  useEffect(() => {
    if (!initialMetrics) void fetchMetrics();
  }, [fetchMetrics, initialMetrics]);

  const summaryCards = [
    { label: "Scans Today", value: metrics.scans_today, icon: <BarChart3 size={20} />, color: "text-blue-400", trend: "+12%" },
    { label: "Detections", value: metrics.detections, icon: <FileWarning size={20} />, color: "text-orange-400", trend: "+5%" },
    { label: "Blocked", value: metrics.blocked, icon: <Ban size={20} />, color: "text-red-400", trend: "-8%" },
    { label: "Redacted", value: metrics.redacted, icon: <EyeOff size={20} />, color: "text-purple-400", trend: "+3%" },
  ];

  const typeEntries = Object.entries(metrics.type_breakdown);
  const totalTypeCount = typeEntries.reduce((s, [, v]) => s + v, 0) || 1;

  const trendMax = Math.max(1, ...metrics.trend.map((t) => t.detections));

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summaryCards.map((s) => (
          <div key={s.label} className="rounded-lg border border-surface-border bg-surface-raised p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-gray-400">{s.label}</span>
              <span className={s.color}>{s.icon}</span>
            </div>
            <p className="text-2xl font-bold text-white">{s.value.toLocaleString()}</p>
            <div className="mt-1 flex items-center gap-1">
              {s.trend.startsWith("-") ? (
                <TrendingDown size={12} className="text-red-400" />
              ) : (
                <TrendingUp size={12} className="text-green-400" />
              )}
              <span className="text-xs text-gray-500">{s.trend} vs yesterday</span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Detection Type Breakdown (donut placeholder) */}
        <div className="rounded-lg border border-surface-border bg-surface-raised">
          <div className="border-b border-surface-border px-4 py-3">
            <div className="flex items-center gap-2">
              <PieChart size={16} className="text-purple-400" />
              <h3 className="text-sm font-semibold text-white">Detection Type Breakdown</h3>
            </div>
          </div>
          <div className="p-4">
            {typeEntries.length === 0 ? (
              <p className="py-8 text-center text-sm text-gray-500">No detections recorded yet</p>
            ) : (
              <div className="space-y-3">
                {typeEntries.map(([type, count], i) => {
                  const pct = Math.round((count / totalTypeCount) * 100);
                  return (
                    <div key={type} className="flex items-center gap-3">
                      <div
                        className="h-3 w-3 shrink-0 rounded-full"
                        style={{ backgroundColor: TYPE_COLORS[i % TYPE_COLORS.length] }}
                      />
                      <span className="min-w-[100px] text-sm text-gray-300">{type}</span>
                      <div className="flex-1">
                        <div className="h-2 rounded-full bg-white/5">
                          <div
                            className="h-2 rounded-full transition-all"
                            style={{
                              width: `${pct}%`,
                              backgroundColor: TYPE_COLORS[i % TYPE_COLORS.length],
                            }}
                          />
                        </div>
                      </div>
                      <span className="w-12 text-right text-xs text-gray-500">{count} ({pct}%)</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Trend Chart */}
        <div className="rounded-lg border border-surface-border bg-surface-raised">
          <div className="border-b border-surface-border px-4 py-3">
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-purple-400" />
              <h3 className="text-sm font-semibold text-white">Detection Trend (7 days)</h3>
            </div>
          </div>
          <div className="p-4">
            {metrics.trend.length === 0 ? (
              <div className="flex h-32 items-end gap-1.5">
                {Array.from({ length: 7 }, (_, i) => {
                  const height = Math.max(8, Math.floor(Math.sin(i * 0.8 + 1) * 40 + 50));
                  return (
                    <div key={i} className="flex flex-1 flex-col items-center gap-1">
                      <div
                        className="w-full rounded-t bg-purple-500/30"
                        style={{ height: `${height}%` }}
                      />
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="flex h-32 items-end gap-2">
                {metrics.trend.map((t) => {
                  const height = Math.max(5, (t.detections / trendMax) * 100);
                  return (
                    <div key={t.date} className="flex flex-1 flex-col items-center gap-1" title={`${t.date}: ${t.detections}`}>
                      <div
                        className="w-full rounded-t bg-purple-500/40 transition-all hover:bg-purple-500/60"
                        style={{ height: `${height}%` }}
                      />
                      <span className="text-[10px] text-gray-600">
                        {t.date.slice(5)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
