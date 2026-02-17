import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Split } from "lucide-react";

export interface ConditionNodeData extends Record<string, unknown> {
  nodeType: "condition";
  label: string;
  condField: string;
  condOperator: string;
  condValue: string;
  condLogic: "AND" | "OR";
}

export function ConditionNode({ data }: NodeProps) {
  const d = data as unknown as ConditionNodeData;
  return (
    <div className="min-w-[160px] rounded-lg border-2 border-[#2a2d37] bg-[#1a1d27] shadow-md"
         style={{ transform: "rotate(0deg)" }}>
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-white" />
      <div className="flex items-center gap-2 rounded-t-md bg-amber-500 px-3 py-1.5 text-white text-xs font-medium">
        <Split size={14} />
        <span>{d.label}</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-gray-400">
        {d.condField && <p>{d.condField} {d.condOperator} {d.condValue}</p>}
        {d.condLogic && d.condLogic !== "AND" && <p>Logic: {d.condLogic}</p>}
      </div>
      <Handle type="source" position={Position.Right} id="true" className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-green-400" style={{ top: "35%" }} />
      <Handle type="source" position={Position.Right} id="false" className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-red-400" style={{ top: "65%" }} />
    </div>
  );
}
