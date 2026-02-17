import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Repeat } from "lucide-react";

export interface LoopNodeData extends Record<string, unknown> {
  nodeType: "loop";
  label: string;
  loopType: "forEach" | "while" | "fixedCount";
  maxIterations: number;
  loopCondition: string;
}

export function LoopNode({ data }: NodeProps) {
  const d = data as unknown as LoopNodeData;
  const typeLabel = d.loopType === "forEach" ? "For Each" : d.loopType === "while" ? "While" : "Fixed Count";
  return (
    <div className="min-w-[160px] rounded-lg border-2 border-[#2a2d37] bg-[#1a1d27] shadow-md">
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-white" />
      <div className="flex items-center gap-2 rounded-t-md bg-green-500 px-3 py-1.5 text-white text-xs font-medium">
        <Repeat size={14} />
        <span>{d.label}</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-gray-400 space-y-0.5">
        <p>{typeLabel}</p>
        <p>Max: {d.maxIterations} iterations</p>
        {d.loopCondition && <p>Cond: {d.loopCondition}</p>}
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-white" />
    </div>
  );
}
