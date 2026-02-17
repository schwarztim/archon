import { useState } from "react";

interface BreakdownItem {
  name: string;
  cost: number;
  pct_of_total: number;
  tokens_used?: number;
}

interface BreakdownTableProps {
  breakdownByModel: BreakdownItem[];
  breakdownByAgent: BreakdownItem[];
  breakdownByUser: BreakdownItem[];
  breakdownByTeam: BreakdownItem[];
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function formatTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

type Tab = "model" | "agent" | "user" | "team";

export function BreakdownTable({ breakdownByModel, breakdownByAgent, breakdownByUser, breakdownByTeam }: BreakdownTableProps) {
  const [tab, setTab] = useState<Tab>("model");
  const [sortField, setSortField] = useState<"name" | "cost" | "pct_of_total">("cost");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const tabData: Record<Tab, BreakdownItem[]> = {
    model: breakdownByModel,
    agent: breakdownByAgent,
    user: breakdownByUser,
    team: breakdownByTeam,
  };

  const data = [...tabData[tab]].sort((a, b) => {
    const av = a[sortField] ?? 0;
    const bv = b[sortField] ?? 0;
    if (typeof av === "string" && typeof bv === "string") {
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    return sortDir === "asc" ? Number(av) - Number(bv) : Number(bv) - Number(av);
  });

  function handleSort(field: typeof sortField) {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  const sortIcon = (field: typeof sortField) =>
    sortField === field ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  return (
    <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center gap-1 border-b border-[#2a2d37] px-4 py-2">
        {(["model", "agent", "user", "team"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === t ? "bg-purple-600 text-white" : "text-gray-400 hover:bg-white/5 hover:text-white"
            }`}
          >
            By {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto">
        {data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <p className="text-sm text-gray-500">No breakdown data available.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="cursor-pointer px-4 py-2 font-medium" onClick={() => handleSort("name")}>
                  Name{sortIcon("name")}
                </th>
                <th className="cursor-pointer px-4 py-2 font-medium text-right" onClick={() => handleSort("cost")}>
                  Cost{sortIcon("cost")}
                </th>
                <th className="cursor-pointer px-4 py-2 font-medium text-right" onClick={() => handleSort("pct_of_total")}>
                  % of Total{sortIcon("pct_of_total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.name} className="border-b border-[#2a2d37] hover:bg-white/5">
                  <td className="px-4 py-2 font-medium text-white">{row.name}</td>
                  <td className="px-4 py-2 text-right font-medium text-green-400">{formatCurrency(row.cost)}</td>
                  <td className="px-4 py-2 text-right text-gray-400">{row.pct_of_total}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
