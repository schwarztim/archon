interface ConsumerEntry {
  name: string;
  cost: number;
  pct_of_total: number;
}

interface TopConsumersProps {
  data: ConsumerEntry[];
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

export function TopConsumers({ data }: TopConsumersProps) {
  const maxCost = Math.max(...data.map((d) => d.cost), 1);

  return (
    <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="border-b border-[#2a2d37] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Top Consumers</h2>
      </div>
      <div className="px-4 py-4">
        {data.length === 0 ? (
          <p className="text-center text-sm text-gray-500">No consumer data available.</p>
        ) : (
          <div className="space-y-3">
            {data.slice(0, 10).map((item) => (
              <div key={item.name}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="font-medium text-white">{item.name}</span>
                  <span className="text-gray-400">
                    {formatCurrency(item.cost)} ({item.pct_of_total}%)
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-purple-500 transition-all"
                    style={{ width: `${Math.max((item.cost / maxCost) * 100, 1)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
