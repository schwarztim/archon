import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Workflow } from "lucide-react";

export interface SubWorkflowNodeData extends Record<string, unknown> {
  nodeType: "subWorkflow";
  label: string;
  workflowId: string;
  inputMapping: { source: string; target: string }[];
  async: boolean;
}

export function SubWorkflowNode({ data }: NodeProps) {
  const d = data as unknown as SubWorkflowNodeData;
  return (
    <div className="min-w-[160px] rounded-lg border-2 border-surface-border bg-surface-raised shadow-md">
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-surface-overlay !bg-white" />
      <div className="flex items-center gap-2 rounded-t-md bg-purple-500 px-3 py-1.5 text-white text-xs font-medium">
        <Workflow size={14} />
        <span>{d.label}</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-gray-400 space-y-0.5">
        {d.workflowId && <p>Workflow: {d.workflowId.slice(0, 8)}…</p>}
        {d.async && <p>Async execution</p>}
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !border-2 !border-surface-overlay !bg-white" />
    </div>
  );
}
