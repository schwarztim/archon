interface UsageStatsProps {
  stats: {
    agents: { current: number; max: number };
    executions: { current: number; max: number };
    storage_mb: { current: number; max: number };
  };
}

function UsageBar({ label, current, max }: { label: string; current: number; max: number }) {
  const pct = max > 0 ? Math.min((current / max) * 100, 100) : 0;
  const color = pct > 90 ? "bg-red-400" : pct > 70 ? "bg-yellow-400" : "bg-purple-400";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-gray-300">{label}</span>
        <span className="text-xs text-gray-500">
          {current.toLocaleString()} / {max.toLocaleString()}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-white/10 dark:bg-white/10">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-right text-xs text-gray-600">{pct.toFixed(1)}% used</p>
    </div>
  );
}

export function UsageStats({ stats }: UsageStatsProps) {
  return (
    <div className="space-y-5 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-5 dark:bg-[#1a1d27]">
      <h3 className="text-sm font-semibold text-white">Usage & Quotas</h3>
      <UsageBar label="Agents" current={stats.agents.current} max={stats.agents.max} />
      <UsageBar label="Executions / Month" current={stats.executions.current} max={stats.executions.max} />
      <UsageBar label="Storage (MB)" current={stats.storage_mb.current} max={stats.storage_mb.max} />
    </div>
  );
}
