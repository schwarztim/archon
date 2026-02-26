import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Combine } from "lucide-react";

export interface MergeNodeData extends Record<string, unknown> {
  nodeType: "merge";
  label: string;
  strategy: "all" | "any" | "n";
  requiredCount: number;
  timeout: number;
}

export function MergeNode({ data }: NodeProps) {
  const d = data as unknown as MergeNodeData;
  const strategyLabel = d.strategy === "all" ? "Wait All" : d.strategy === "any" ? "Wait Any" : `Wait ${d.requiredCount}`;
  return (
    <div className="min-w-[160px] rounded-lg border-2 border-surface-border bg-surface-raised shadow-md">
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-surface-overlay !bg-white" />
      <div className="flex items-center gap-2 rounded-t-md bg-indigo-500 px-3 py-1.5 text-white text-xs font-medium">
        <Combine size={14} />
        <span>{d.label}</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-gray-400 space-y-0.5">
        <p>{strategyLabel}</p>
        {d.timeout > 0 && <p>Timeout: {d.timeout}s</p>}
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !border-2 !border-surface-overlay !bg-white" />
    </div>
  );
}
