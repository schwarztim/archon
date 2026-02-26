import { Handle, Position, type NodeProps } from "@xyflow/react";
import { GitFork } from "lucide-react";

export interface ParallelNodeData extends Record<string, unknown> {
  nodeType: "parallel";
  label: string;
  branches: number;
  executionMode: "all" | "any" | "n_of_m";
  requiredCount: number;
}

export function ParallelNode({ data }: NodeProps) {
  const d = data as unknown as ParallelNodeData;
  const modeLabel = d.executionMode === "all" ? "Wait All" : d.executionMode === "any" ? "Wait Any" : `${d.requiredCount} of ${d.branches}`;
  return (
    <div className="min-w-[160px] rounded-lg border-2 border-surface-border bg-surface-raised shadow-md">
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-surface-overlay !bg-white" />
      <div className="flex items-center gap-2 rounded-t-md bg-cyan-500 px-3 py-1.5 text-white text-xs font-medium">
        <GitFork size={14} />
        <span>{d.label}</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-gray-400 space-y-0.5">
        <p>{d.branches} branches</p>
        <p>Mode: {modeLabel}</p>
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !border-2 !border-surface-overlay !bg-white" />
    </div>
  );
}
