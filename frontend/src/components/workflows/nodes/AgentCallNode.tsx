import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Bot } from "lucide-react";

export interface AgentCallNodeData extends Record<string, unknown> {
  nodeType: "agentCall";
  label: string;
  agent_id: string;
  inputMapping: { source: string; target: string }[];
  timeout: number;
  retryPolicy: "none" | "1" | "3";
  onFailure: "stop" | "skip" | "continue";
}

export function AgentCallNode({ data }: NodeProps) {
  const d = data as unknown as AgentCallNodeData;
  return (
    <div className="min-w-[180px] rounded-lg border-2 border-[#2a2d37] bg-[#1a1d27] shadow-md">
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-white" />
      <div className="flex items-center gap-2 rounded-t-md bg-blue-500 px-3 py-1.5 text-white text-xs font-medium">
        <Bot size={14} />
        <span>{d.label}</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-gray-400 space-y-0.5">
        {d.agent_id && <p>Agent: {d.agent_id.slice(0, 8)}…</p>}
        {d.timeout > 0 && <p>Timeout: {d.timeout}s</p>}
        {d.retryPolicy !== "none" && <p>Retry: {d.retryPolicy}x</p>}
        {d.onFailure !== "stop" && <p>On fail: {d.onFailure}</p>}
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !border-2 !border-[#12141e] !bg-white" />
    </div>
  );
}
