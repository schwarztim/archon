import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// ── Types ────────────────────────────────────────────────────────────

type ChartType = "bar" | "line" | "pie";

interface ChartComponentProps {
  chartType: ChartType;
  data: Record<string, unknown>[];
  xKey: string;
  yKey: string;
  title?: string;
  height?: number;
  colors?: string[];
}

const DEFAULT_COLORS = [
  "#a78bfa",
  "#60a5fa",
  "#34d399",
  "#fbbf24",
  "#f87171",
  "#c084fc",
  "#38bdf8",
  "#4ade80",
];

// ── Component ────────────────────────────────────────────────────────

export function ChartComponent({
  chartType,
  data,
  xKey,
  yKey,
  title,
  height = 300,
  colors = DEFAULT_COLORS,
}: ChartComponentProps) {
  const tooltipStyle = {
    backgroundColor: "#1a1d27",
    border: "1px solid #2a2d37",
    borderRadius: "8px",
    color: "#d1d5db",
  };

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] p-4">
      {title && (
        <h4 className="mb-3 text-sm font-semibold text-white">{title}</h4>
      )}
      <ResponsiveContainer width="100%" height={height}>
        {chartType === "bar" ? (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2d37" />
            <XAxis dataKey={xKey} stroke="#6b7280" fontSize={12} />
            <YAxis stroke="#6b7280" fontSize={12} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
            <Bar dataKey={yKey} fill={colors[0]} radius={[4, 4, 0, 0]} />
          </BarChart>
        ) : chartType === "line" ? (
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2d37" />
            <XAxis dataKey={xKey} stroke="#6b7280" fontSize={12} />
            <YAxis stroke="#6b7280" fontSize={12} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
            <Line
              type="monotone"
              dataKey={yKey}
              stroke={colors[0]}
              strokeWidth={2}
              dot={{ fill: colors[0], r: 4 }}
            />
          </LineChart>
        ) : (
          <PieChart>
            <Pie
              data={data}
              dataKey={yKey}
              nameKey={xKey}
              cx="50%"
              cy="50%"
              outerRadius={height / 3}
              label
            >
              {data.map((_, i) => (
                <Cell key={i} fill={colors[i % colors.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
          </PieChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
