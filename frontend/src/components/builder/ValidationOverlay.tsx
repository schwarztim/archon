import { useMemo } from "react";
import { useCanvasStore } from "@/stores/canvasStore";
import type { CustomNodeData } from "@/types";
import {
  validateGraph,
  type GraphValidationResult,
  type NodeValidationError,
} from "@/types/nodeTypes";

interface ValidationOverlayProps {
  /** When true, show validation errors inline */
  showErrors: boolean;
}

/**
 * Renders validation error badges on the canvas.
 * Also provides a floating error summary panel.
 */
export function ValidationOverlay({ showErrors }: ValidationOverlayProps) {
  const { nodes, edges } = useCanvasStore();

  const validation: GraphValidationResult = useMemo(() => {
    const typedNodes = nodes.map((n) => ({
      id: n.id,
      type: n.type,
      data: n.data as CustomNodeData,
    }));
    return validateGraph(typedNodes, edges);
  }, [nodes, edges]);

  if (!showErrors || validation.valid) return null;

  // Group errors by node
  const globalErrors = validation.errors.filter((e) => !e.nodeId);
  const nodeErrors = validation.errors.filter((e) => e.nodeId);

  const grouped = nodeErrors.reduce<Record<string, NodeValidationError[]>>(
    (acc, err) => {
      if (!acc[err.nodeId]) acc[err.nodeId] = [];
      acc[err.nodeId].push(err);
      return acc;
    },
    {},
  );

  // Find node labels for display
  const nodeLabels = new Map(
    nodes.map((n) => [n.id, (n.data as CustomNodeData).label ?? n.id]),
  );

  return (
    <div
      className="absolute bottom-4 left-1/2 z-50 -translate-x-1/2 w-96 max-h-48 overflow-y-auto rounded-lg border border-destructive/50 bg-card shadow-lg"
      role="alert"
      aria-label="Validation errors"
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-2">
        <span className="inline-block h-2 w-2 rounded-full bg-destructive" />
        <span className="text-sm font-medium text-destructive">
          {validation.errors.length} Validation Error{validation.errors.length !== 1 ? "s" : ""}
        </span>
      </div>
      <ul className="divide-y divide-border">
        {globalErrors.map((err, i) => (
          <li key={`global-${i}`} className="px-4 py-2 text-xs text-destructive">
            {err.message}
          </li>
        ))}
        {Object.entries(grouped).map(([nodeId, errs]) => (
          <li key={nodeId} className="px-4 py-2">
            <span className="text-xs font-medium">
              {nodeLabels.get(nodeId) ?? nodeId}
            </span>
            <ul className="mt-1 space-y-0.5">
              {errs.map((err, i) => (
                <li key={i} className="text-xs text-destructive">
                  • {err.message}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Hook to get validation state for use in other components.
 * Returns nodeIds that have validation errors (for red badge display).
 */
export function useValidationErrors(): {
  validation: GraphValidationResult;
  errorNodeIds: Set<string>;
} {
  const { nodes, edges } = useCanvasStore();

  return useMemo(() => {
    const typedNodes = nodes.map((n) => ({
      id: n.id,
      type: n.type,
      data: n.data as CustomNodeData,
    }));
    const validation = validateGraph(typedNodes, edges);
    const errorNodeIds = new Set(
      validation.errors.filter((e) => e.nodeId).map((e) => e.nodeId),
    );
    return { validation, errorNodeIds };
  }, [nodes, edges]);
}
