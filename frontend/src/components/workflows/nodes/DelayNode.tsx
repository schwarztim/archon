import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Clock } from "lucide-react";

export interface DelayNodeData extends Record<string, unknown> {
  nodeType: "delay";
  label: string;
  delayType: "duration" | "datetime";
  durationMs: number;
  targetDatetime: string;
}

export function DelayNode({ data }: NodeProps) {
  const d = data as unknown as DelayNodeData;
  const displayDelay =
    d.delayType === "duration"
      ? d.durationMs >= 60000
        ? `${Math.round(d.durationMs / 60000)}m`
        : `${Math.round(d.durationMs / 1000)}s`
      : d.targetDatetime || "Not set";

  return (
    <div className="min-w-[160px] rounded-lg border-2 border-[#2a2d37] bg-[#1a1d27] shadow-md">
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-white" />
      <div className="flex items-center gap-2 rounded-t-md bg-orange-500 px-3 py-1.5 text-white text-xs font-medium">
        <Clock size={14} />
        <span>{d.label}</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-gray-400">
        <p>{d.delayType === "duration" ? `Wait ${displayDelay}` : `At ${displayDelay}`}</p>
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-white" />
    </div>
  );
}
