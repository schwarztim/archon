import type { RiskBreakdownResult } from "@/api/sentinelscan";

interface RiskBarsProps {
  risks: RiskBreakdownResult | null;
  onCategoryClick?: (category: string) => void;
}

const CATEGORY_COLORS: Record<string, string> = {
  "Data Exposure": "bg-orange-500",
  "Unauthorized Access": "bg-yellow-500",
  "Credential Risk": "bg-red-500",
  "Policy Violation": "bg-purple-500",
};

export function RiskBars({ risks, onCategoryClick }: RiskBarsProps) {
  if (!risks) {
    return (
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
        <h3 className="mb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Risk Breakdown</h3>
        <p className="text-sm text-gray-500">Run a scan to see risk breakdown.</p>
      </div>
    );
  }

  const categories = risks.categories;
  const maxCount = Math.max(1, ...Object.values(categories).map((c) => c.count));

  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
      <h3 className="mb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Risk Breakdown</h3>
      <div className="space-y-3">
        {Object.entries(categories).map(([name, cat]) => {
          const pct = (cat.count / maxCount) * 100;
          const barColor = CATEGORY_COLORS[name] ?? "bg-blue-500";
          return (
            <button
              key={name}
              className="w-full text-left hover:bg-white/5 rounded p-1 -m-1 transition-colors"
              onClick={() => onCategoryClick?.(name)}
              type="button"
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs text-gray-400">{name}</span>
                <span className="text-sm font-semibold text-white">{cat.count}</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-white/10">
                <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
              </div>
            </button>
          );
        })}
      </div>
      <div className="mt-3 text-xs text-gray-500">
        Total findings: {risks.total_findings}
      </div>
    </div>
  );
}
