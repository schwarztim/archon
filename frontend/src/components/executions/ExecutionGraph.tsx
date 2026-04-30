/**
 * ExecutionGraph
 *
 * Visual DAG of a run's steps. Built on ``@xyflow/react`` (already a
 * dependency). Nodes are colour-coded by step status; edges follow the
 * static ``graph_definition`` (when supplied) or fall back to the
 * sequential order of the supplied step list.
 *
 * Click a node → ``onStepSelect(stepId)`` (used by ExecutionDetailPage to
 * cross-highlight in the EventTimeline + open the StepDetail panel).
 */
import { useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { WorkflowRunStep, StepStatus } from "@/types/workflow_run";

export interface GraphDefinition {
  nodes: { id: string; data?: { label?: string }; position?: { x: number; y: number } }[];
  edges: { id: string; source: string; target: string; label?: string }[];
}

interface ExecutionGraphProps {
  steps: WorkflowRunStep[];
  /** Optional static graph_definition from ``WorkflowRun.definition_snapshot``. */
  graphDefinition?: GraphDefinition | null;
  selectedStepId?: string | null;
  onStepSelect?: (stepId: string) => void;
  className?: string;
}

const STATUS_COLORS: Record<
  StepStatus,
  { bg: string; border: string; text: string }
> = {
  completed: { bg: "#065f46", border: "#10b981", text: "#6ee7b7" },
  running: { bg: "#1e3a5f", border: "#3b82f6", text: "#93c5fd" },
  failed: { bg: "#7f1d1d", border: "#ef4444", text: "#fca5a5" },
  skipped: { bg: "#1f2937", border: "#4b5563", text: "#9ca3af" },
  pending: { bg: "#1f2937", border: "#6b7280", text: "#d1d5db" },
  paused: { bg: "#3b1f5f", border: "#8b5cf6", text: "#c4b5fd" },
};

interface StepNodeData extends Record<string, unknown> {
  label: string;
  status: StepStatus;
  selected: boolean;
  durationMs: number | null;
  cost: number | null;
}

function StepNode({ data }: NodeProps) {
  const d = data as StepNodeData;
  const colors = STATUS_COLORS[d.status] ?? STATUS_COLORS.pending;
  return (
    <div
      className="rounded-lg px-4 py-3 shadow-lg transition-all"
      style={{
        backgroundColor: colors?.bg,
        border: `2px solid ${d.selected ? "#a78bfa" : colors?.border}`,
        minWidth: 160,
        boxShadow: d.selected ? "0 0 0 3px rgba(167, 139, 250, 0.25)" : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-500" />
      <div
        className="text-sm font-medium"
        style={{ color: colors?.text }}
      >
        {d.label}
      </div>
      <div
        className="mt-1 flex gap-2 text-[10px]"
        style={{ color: colors?.text, opacity: 0.7 }}
      >
        <span className="capitalize">{d.status}</span>
        {d.durationMs != null && <span>{d.durationMs}ms</span>}
        {d.cost != null && d.cost > 0 && <span>${d.cost.toFixed(4)}</span>}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-500" />
    </div>
  );
}

const nodeTypes = { stepNode: StepNode };

export function ExecutionGraph({
  steps,
  graphDefinition,
  selectedStepId,
  onStepSelect,
  className = "",
}: ExecutionGraphProps) {
  const { nodes, edges } = useMemo(() => {
    if (!steps || steps.length === 0) {
      return { nodes: [] as Node[], edges: [] as Edge[] };
    }

    const stepByStepId = new Map<string, WorkflowRunStep>();
    for (const s of steps) stepByStepId.set(s.step_id, s);

    // Prefer the static graph definition when supplied so nodes/edges
    // mirror the workflow author's intended layout.
    if (graphDefinition && graphDefinition.nodes.length > 0) {
      const ns: Node[] = graphDefinition.nodes.map((gn, i) => {
        const matched = stepByStepId.get(gn.id);
        const status: StepStatus = matched?.status ?? "pending";
        return {
          id: gn.id,
          type: "stepNode",
          position: gn.position ?? { x: (i % 4) * 240, y: Math.floor(i / 4) * 140 },
          data: {
            label: gn.data?.label ?? matched?.name ?? gn.id,
            status,
            selected: matched?.step_id === selectedStepId,
            durationMs: matched?.duration_ms ?? null,
            cost: matched?.cost_usd ?? null,
          } satisfies StepNodeData,
        };
      });

      const es: Edge[] = graphDefinition.edges.map((ge) => {
        const sourceStep = stepByStepId.get(ge.source);
        const status = sourceStep?.status ?? "pending";
        return {
          id: ge.id,
          source: ge.source,
          target: ge.target,
          animated: status === "running",
          label: ge.label,
          style: {
            stroke:
              status === "completed"
                ? "#10b981"
                : status === "failed"
                  ? "#ef4444"
                  : "#4b5563",
            strokeWidth: 2,
          },
        };
      });

      return { nodes: ns, edges: es };
    }

    // Fallback: sequential layout from the step list (chronological by ``started_at``).
    const ordered = [...steps].sort((a, b) => {
      const sa = a.started_at ? new Date(a.started_at).getTime() : 0;
      const sb = b.started_at ? new Date(b.started_at).getTime() : 0;
      return sa - sb;
    });

    const ns: Node[] = ordered.map((s, i) => ({
      id: s.step_id,
      type: "stepNode",
      position: { x: 250, y: i * 120 },
      data: {
        label: s.name || s.step_id,
        status: s.status,
        selected: s.step_id === selectedStepId,
        durationMs: s.duration_ms ?? null,
        cost: s.cost_usd ?? null,
      } satisfies StepNodeData,
    }));

    const es: Edge[] = [];
    for (let i = 0; i < ordered.length - 1; i++) {
      const src = ordered[i];
      const tgt = ordered[i + 1];
      if (!src || !tgt) continue;
      es.push({
        id: `${src.step_id}->${tgt.step_id}`,
        source: src.step_id,
        target: tgt.step_id,
        animated: src.status === "running",
        style: {
          stroke:
            src.status === "completed"
              ? "#10b981"
              : src.status === "failed"
                ? "#ef4444"
                : "#4b5563",
          strokeWidth: 2,
        },
      });
    }

    return { nodes: ns, edges: es };
  }, [steps, graphDefinition, selectedStepId]);

  if (!steps || steps.length === 0) {
    return (
      <div
        className={`flex items-center justify-center text-sm text-gray-500 ${className}`}
        style={{ height: 320 }}
      >
        No steps recorded for this run.
      </div>
    );
  }

  return (
    <div
      className={className}
      style={{ height: Math.max(320, steps.length * 110 + 80) }}
      data-testid="execution-graph"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, node) => onStepSelect?.(node.id)}
        className="bg-surface-base"
      >
        <Background color="#1a1d27" gap={20} />
        <Controls className="!bg-surface-raised !border-surface-border" />
        <MiniMap
          nodeColor={(node) => {
            const status = (node.data as StepNodeData)?.status;
            return STATUS_COLORS[status]?.border ?? "#4b5563";
          }}
          className="!bg-surface-base !border-surface-border"
        />
      </ReactFlow>
    </div>
  );
}
