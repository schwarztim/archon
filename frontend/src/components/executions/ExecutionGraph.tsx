import { useMemo } from "react";
import {
  ReactFlow,
  type Node,
  type Edge,
  Background,
  Controls,
  MiniMap,
  Position,
  Handle,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { StepData } from "./StepTimeline";

interface ExecutionGraphProps {
  steps: StepData[];
  className?: string;
}

const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  completed: { bg: "#065f46", border: "#10b981", text: "#6ee7b7" },
  running: { bg: "#1e3a5f", border: "#3b82f6", text: "#93c5fd" },
  failed: { bg: "#7f1d1d", border: "#ef4444", text: "#fca5a5" },
  skipped: { bg: "#1f2937", border: "#4b5563", text: "#9ca3af" },
  pending: { bg: "#1f2937", border: "#6b7280", text: "#d1d5db" },
};

const STEP_TYPE_ICONS: Record<string, string> = {
  llm_call: "🤖",
  tool_call: "🔧",
  condition: "⚡",
  transform: "🔄",
  retrieval: "📚",
};

function StepNode({ data }: NodeProps) {
  const nodeData = data as Record<string, unknown>;
  const status = (nodeData.status as string) ?? "pending";
  const colors = STATUS_COLORS[status] ?? STATUS_COLORS.pending;
  const stepType = (nodeData.stepType as string) ?? "";
  const icon = STEP_TYPE_ICONS[stepType] ?? "●";
  const tokens = nodeData.tokens as number | undefined;
  const durationMs = nodeData.durationMs as number | undefined;
  const cost = nodeData.cost as number | undefined;

  return (
    <div
      className="rounded-lg px-4 py-3 shadow-lg"
      style={{
        backgroundColor: colors?.bg,
        border: `2px solid ${colors?.border}`,
        minWidth: 180,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-500" />
      <div className="flex items-center gap-2">
        <span className="text-base">{icon}</span>
        <span className="text-sm font-medium capitalize" style={{ color: colors?.text }}>
          {nodeData.label as string}
        </span>
      </div>
      {stepType && (
        <div className="mt-1 text-[10px] uppercase tracking-wide" style={{ color: colors?.text, opacity: 0.7 }}>
          {stepType.replace("_", " ")}
        </div>
      )}
      <div className="mt-1 flex gap-2 text-[10px]" style={{ color: colors?.text, opacity: 0.6 }}>
        {tokens != null && tokens > 0 && <span>{tokens} tok</span>}
        {durationMs != null && <span>{durationMs}ms</span>}
        {cost != null && cost > 0 && <span>${cost.toFixed(4)}</span>}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-500" />
    </div>
  );
}

const nodeTypes = { stepNode: StepNode };

export function ExecutionGraph({ steps, className = "" }: ExecutionGraphProps) {
  const { nodes, edges } = useMemo(() => {
    if (!steps || steps.length === 0) return { nodes: [], edges: [] };

    const ns: Node[] = steps.map((step, i) => ({
      id: `step-${i}`,
      type: "stepNode",
      position: { x: 250, y: i * 120 },
      data: {
        label: step.step_name ?? step.name ?? `Step ${i + 1}`,
        status: step.status,
        stepType: step.step_type ?? "",
        tokens: step.token_usage ?? step.tokens,
        durationMs: step.duration_ms,
        cost: step.cost,
      },
    }));

    const es: Edge[] = [];
    for (let i = 0; i < steps.length - 1; i++) {
      es.push({
        id: `edge-${i}-${i + 1}`,
        source: `step-${i}`,
        target: `step-${i + 1}`,
        animated: steps[i]?.status === "running",
        style: {
          stroke: steps[i]?.status === "completed" ? "#10b981" : steps[i]?.status === "failed" ? "#ef4444" : "#4b5563",
          strokeWidth: 2,
        },
      });
    }

    return { nodes: ns, edges: es };
  }, [steps]);

  if (!steps || steps.length === 0) {
    return (
      <div className={`flex items-center justify-center text-sm text-gray-500 ${className}`} style={{ height: 400 }}>
        No steps to visualize.
      </div>
    );
  }

  return (
    <div className={className} style={{ height: Math.max(400, steps.length * 120 + 80) }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        className="bg-[#0f1117]"
      >
        <Background color="#1a1d27" gap={20} />
        <Controls className="!bg-[#1a1d27] !border-[#2a2d37]" />
        <MiniMap
          nodeColor={(node) => {
            const status = (node.data as Record<string, unknown>)?.status as string;
            return STATUS_COLORS[status]?.border ?? "#4b5563";
          }}
          className="!bg-[#0f1117] !border-[#2a2d37]"
        />
      </ReactFlow>
    </div>
  );
}
