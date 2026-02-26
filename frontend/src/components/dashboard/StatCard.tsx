import { type ReactNode } from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/utils/cn";

export interface StatCardProps {
  label: string;
  value: string | number;
  icon: ReactNode;
  trend?: number | null;
  trendLabel?: string;
  onClick?: () => void;
}

function TrendArrow({ trend }: { trend: number }) {
  if (trend > 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs font-medium text-green-400">
        <TrendingUp size={12} />
        +{trend}%
      </span>
    );
  }
  if (trend < 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs font-medium text-red-400">
        <TrendingDown size={12} />
        {trend}%
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium text-gray-400">
      <Minus size={12} />
      0%
    </span>
  );
}

export function StatCard({ label, value, icon, trend, trendLabel, onClick }: StatCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg border border-surface-border bg-surface-raised p-4 text-left transition-colors",
        onClick && "cursor-pointer hover:border-purple-500/40 hover:bg-surface-raised",
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm text-gray-400">{label}</span>
        <span className="text-purple-400">{icon}</span>
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
      {trend != null && (
        <div className="mt-1 flex items-center gap-2">
          <TrendArrow trend={trend} />
          {trendLabel && <span className="text-xs text-gray-500">{trendLabel}</span>}
        </div>
      )}
    </button>
  );
}
