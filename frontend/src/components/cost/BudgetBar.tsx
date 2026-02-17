interface BudgetBarProps {
  name: string;
  spent: number;
  limit: number;
  enforcement: string;
  scope: string;
  period: string;
  thresholds?: number[];
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

export function BudgetBar({ name, spent, limit, enforcement, scope, period, thresholds = [50, 75, 90, 100] }: BudgetBarProps) {
  const pct = limit > 0 ? Math.round((spent / limit) * 100) : 0;
  const color = pct < 75 ? "bg-green-500" : pct < 90 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div className="px-4 py-3">
      <div className="mb-1 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium text-white">{name}</span>
          <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">{scope}</span>
          <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">{period}</span>
          <span className={`rounded px-1.5 py-0.5 text-[10px] ${enforcement === "hard" ? "bg-red-500/20 text-red-400" : "bg-yellow-500/20 text-yellow-400"}`}>
            {enforcement}
          </span>
        </div>
        <span className="text-sm font-medium text-gray-400">
          {formatCurrency(spent)} / {formatCurrency(limit)} ({pct}%)
        </span>
      </div>
      {/* Utilization bar: green <75%, yellow 75-90%, red >90% */}
      <div className="relative h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
        {thresholds.map((t) => (
          <div
            key={t}
            className="absolute top-0 h-full w-px"
            style={{
              left: `${t}%`,
              backgroundColor: t <= pct ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.15)",
            }}
            title={`${t}% threshold`}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[9px] text-gray-600">
        <span>0%</span>
        {thresholds.map((t) => (
          <span key={t}>{t}%</span>
        ))}
      </div>
    </div>
  );
}
