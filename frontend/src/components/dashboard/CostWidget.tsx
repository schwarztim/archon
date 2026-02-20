import { DollarSign, TrendingUp, TrendingDown, Minus } from "lucide-react";

export interface DailyCost {
  date: string;
  cost: number;
}

interface CostWidgetProps {
  dailyCosts: DailyCost[];
  totalThisWeek: number;
  totalLastWeek: number;
  currency?: string;
}

function formatCurrency(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function MiniAreaChart({ data, height = 60 }: { data: DailyCost[]; height?: number }) {
  if (data.length === 0) return null;

  const maxCost = Math.max(...data.map((d) => d.cost), 0.01);
  const width = 280;
  const padding = 4;

  const points = data.map((d, i) => ({
    x: padding + (i / Math.max(data.length - 1, 1)) * (width - padding * 2),
    y: height - padding - (d.cost / maxCost) * (height - padding * 2),
  }));

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const areaPath = `${linePath} L ${points[points.length - 1]?.x} ${height - padding} L ${points[0]?.x} ${height - padding} Z`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgb(168, 85, 247)" stopOpacity={0.3} />
          <stop offset="100%" stopColor="rgb(168, 85, 247)" stopOpacity={0.05} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#costGradient)" />
      <path d={linePath} fill="none" stroke="rgb(168, 85, 247)" strokeWidth={2} />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={2.5} fill="rgb(168, 85, 247)" />
      ))}
    </svg>
  );
}

export function CostWidget({ dailyCosts, totalThisWeek, totalLastWeek, currency = "USD" }: CostWidgetProps) {
  const weekChange = totalLastWeek > 0
    ? Math.round(((totalThisWeek - totalLastWeek) / totalLastWeek) * 100)
    : 0;

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center gap-2 border-b border-[#2a2d37] px-4 py-3">
        <DollarSign size={14} className="text-green-400" />
        <h2 className="text-sm font-semibold text-white">Cost Summary</h2>
      </div>
      <div className="p-4">
        <div className="mb-3 flex items-end justify-between">
          <div>
            <p className="text-xs text-gray-400">This Week</p>
            <p className="text-xl font-bold text-white">{formatCurrency(totalThisWeek, currency)}</p>
          </div>
          <div className="text-right">
            <div className="flex items-center gap-1">
              {weekChange > 0 ? (
                <TrendingUp size={12} className="text-red-400" />
              ) : weekChange < 0 ? (
                <TrendingDown size={12} className="text-green-400" />
              ) : (
                <Minus size={12} className="text-gray-400" />
              )}
              <span
                className={`text-xs font-medium ${
                  weekChange > 0 ? "text-red-400" : weekChange < 0 ? "text-green-400" : "text-gray-400"
                }`}
              >
                {weekChange > 0 ? "+" : ""}{weekChange}% vs last week
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Last: {formatCurrency(totalLastWeek, currency)}
            </p>
          </div>
        </div>
        <div className="rounded-md bg-[#141620] p-2">
          {dailyCosts.length > 0 ? (
            <>
              <MiniAreaChart data={dailyCosts} />
              <div className="mt-1 flex justify-between text-[10px] text-gray-500">
                {dailyCosts.length > 0 && (
                  <>
                    <span>{new Date(dailyCosts[0]?.date ?? '').toLocaleDateString("en-US", { weekday: "short" })}</span>
                    <span>{new Date(dailyCosts[dailyCosts.length - 1]?.date ?? '').toLocaleDateString("en-US", { weekday: "short" })}</span>
                  </>
                )}
              </div>
            </>
          ) : (
            <p className="py-4 text-center text-xs text-gray-500">No cost data available</p>
          )}
        </div>
      </div>
    </div>
  );
}
