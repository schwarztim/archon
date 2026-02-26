interface StrategySelectorProps {
  strategy: string;
  onStrategyChange: (strategy: string) => void;
  replicas: string;
  onReplicasChange: (replicas: string) => void;
  canaryPct: string;
  onCanaryPctChange: (pct: string) => void;
  blueGreenPreview: boolean;
  onBlueGreenPreviewChange: (preview: boolean) => void;
}

const STRATEGIES = [
  { value: "rolling", label: "Rolling", description: "Gradually replace instances" },
  { value: "blue-green", label: "Blue-Green", description: "Switch traffic between two identical environments" },
  { value: "canary", label: "Canary", description: "Route a percentage of traffic to new version" },
] as const;

export function StrategySelector({
  strategy,
  onStrategyChange,
  replicas,
  onReplicasChange,
  canaryPct,
  onCanaryPctChange,
  blueGreenPreview,
  onBlueGreenPreviewChange,
}: StrategySelectorProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className="mb-1 block text-xs text-gray-400">Strategy</label>
        <div className="grid grid-cols-3 gap-2">
          {STRATEGIES.map((s) => (
            <button
              key={s.value}
              type="button"
              onClick={() => onStrategyChange(s.value)}
              className={`rounded-lg border p-2 text-left transition-colors ${
                strategy === s.value
                  ? "border-purple-500/50 bg-purple-500/10"
                  : "border-surface-border bg-surface-base hover:border-gray-500"
              }`}
            >
              <span className="block text-xs font-medium text-white">{s.label}</span>
              <span className="block text-[10px] text-gray-500">{s.description}</span>
            </button>
          ))}
        </div>
      </div>

      {strategy === "rolling" && (
        <div>
          <label className="mb-1 flex items-center justify-between text-xs text-gray-400">
            <span>Replica Count</span>
            <span className="font-mono text-purple-400">{replicas}</span>
          </label>
          <input
            type="range"
            min={1}
            max={10}
            value={replicas}
            onChange={(e) => onReplicasChange(e.target.value)}
            className="h-2 w-full cursor-pointer accent-purple-500"
          />
          <div className="flex justify-between text-[10px] text-gray-600">
            <span>1</span>
            <span>10</span>
          </div>
        </div>
      )}

      {strategy === "blue-green" && (
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={blueGreenPreview}
            onChange={(e) => onBlueGreenPreviewChange(e.target.checked)}
            className="h-4 w-4 rounded border-gray-600 accent-purple-500"
          />
          <label className="text-xs text-gray-400">Enable preview environment before switch</label>
        </div>
      )}

      {strategy === "canary" && (
        <div>
          <label className="mb-1 flex items-center justify-between text-xs text-gray-400">
            <span>Traffic %</span>
            <span className="font-mono text-purple-400">{canaryPct}%</span>
          </label>
          <input
            type="range"
            min={1}
            max={100}
            value={canaryPct}
            onChange={(e) => onCanaryPctChange(e.target.value)}
            className="h-2 w-full cursor-pointer accent-purple-500"
          />
          <div className="flex justify-between text-[10px] text-gray-600">
            <span>1%</span>
            <span>100%</span>
          </div>
        </div>
      )}
    </div>
  );
}
