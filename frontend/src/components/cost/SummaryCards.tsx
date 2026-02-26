import { DollarSign, Wallet, TrendingUp, Cpu } from "lucide-react";

interface SummaryCardsProps {
  totalSpend: number;
  budgetUsedPct: number;
  projectedSpend: number;
  topModel: string;
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

export function SummaryCards({ totalSpend, budgetUsedPct, projectedSpend, topModel }: SummaryCardsProps) {
  return (
    <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4 dark:bg-surface-raised">
        <div className="mb-1 flex items-center gap-2 text-xs text-gray-400">
          <DollarSign size={14} />Total Spend
        </div>
        <div className="text-2xl font-bold text-white">{formatCurrency(totalSpend)}</div>
      </div>
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4 dark:bg-surface-raised">
        <div className="mb-1 flex items-center gap-2 text-xs text-gray-400">
          <Wallet size={14} />Spend vs Budget
        </div>
        <div className="text-2xl font-bold text-white">{budgetUsedPct}%</div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10">
          <div
            className={`h-full rounded-full ${budgetUsedPct >= 90 ? "bg-red-500" : budgetUsedPct >= 75 ? "bg-yellow-500" : "bg-green-500"}`}
            style={{ width: `${Math.min(budgetUsedPct, 100)}%` }}
          />
        </div>
      </div>
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4 dark:bg-surface-raised">
        <div className="mb-1 flex items-center gap-2 text-xs text-gray-400">
          <TrendingUp size={14} />Projected
        </div>
        <div className="text-2xl font-bold text-white">{formatCurrency(projectedSpend)}</div>
      </div>
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4 dark:bg-surface-raised">
        <div className="mb-1 flex items-center gap-2 text-xs text-gray-400">
          <Cpu size={14} />Top Model
        </div>
        <div className="text-2xl font-bold text-white">{topModel}</div>
      </div>
    </div>
  );
}
