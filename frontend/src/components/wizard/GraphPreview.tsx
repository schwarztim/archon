import { useMemo } from "react";
import {
  ArrowRight,
  Brain,
  Wrench,
  GitBranch,
  Shield,
} from "lucide-react";
import type { PlanStep } from "./PlanCard";
import type { PlannedEdge } from "@/api/wizard";

const TYPE_BADGE: Record<string, { color: string; icon: typeof Brain }> = {
  llm: { color: "bg-blue-500/20 text-blue-400", icon: Brain },
  tool: { color: "bg-green-500/20 text-green-400", icon: Wrench },
  condition: { color: "bg-yellow-500/20 text-yellow-400", icon: GitBranch },
  auth: { color: "bg-red-500/20 text-red-400", icon: Shield },
  default: { color: "bg-gray-500/20 text-gray-400", icon: Brain },
};

interface GraphPreviewProps {
  steps: PlanStep[];
  edges?: PlannedEdge[];
}

/** Read-only graph preview for the wizard Step 4. */
export function GraphPreview({ steps, edges }: GraphPreviewProps) {
  const resolvedEdges = useMemo(() => {
    if (edges && edges.length > 0) return edges;
    // Default: linear chain
    return steps.slice(0, -1).map((s, i) => ({
      source: s.id,
      target: steps[i + 1]?.id,
      condition: "",
    }));
  }, [edges, steps]);

  if (steps.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-[#2a2d37] bg-[#0f1117] p-8">
        <p className="text-sm text-gray-500">No steps defined</p>
      </div>
    );
  }

  // For a compact preview, render as a flow diagram
  const cols = Math.min(steps.length, 4);
  const rows = Math.ceil(steps.length / cols);

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] p-4">
      <div className="space-y-3">
        {Array.from({ length: rows }, (_, row) => (
          <div key={row} className="flex items-center gap-2 justify-center flex-wrap">
            {steps
              .slice(row * cols, (row + 1) * cols)
              .map((step, colIdx) => {
                const globalIdx = row * cols + colIdx;
                const badge = TYPE_BADGE[step.type] ?? TYPE_BADGE.default;
                const BadgeIcon = badge?.icon;
                const isLast = globalIdx === steps.length - 1;
                const isRowLast = colIdx === cols - 1;

                return (
                  <div key={step.id} className="flex items-center gap-2">
                    <div className="flex flex-col items-center gap-1 rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 min-w-[110px] max-w-[140px]">
                      {BadgeIcon && <BadgeIcon
                        size={16}
                        className={badge?.color.split(" ")[1]}
                      />}
                      <span className="text-xs font-medium text-white text-center leading-tight">
                        {step.name}
                      </span>
                      <span
                        className={`rounded-full px-1.5 py-0.5 text-[9px] font-medium ${badge?.color}`}
                      >
                        {step.type.toUpperCase()}
                      </span>
                    </div>
                    {!isLast && !isRowLast && (
                      <ArrowRight
                        size={16}
                        className="flex-shrink-0 text-gray-600"
                      />
                    )}
                  </div>
                );
              })}
          </div>
        ))}
      </div>

      {/* Edge legend when conditions exist */}
      {resolvedEdges.some((e) => e.condition) && (
        <div className="mt-3 border-t border-[#2a2d37] pt-3">
          <p className="text-[10px] font-medium text-gray-500 mb-1">
            Conditions
          </p>
          <div className="space-y-1">
            {resolvedEdges
              .filter((e) => e.condition)
              .map((e, i) => (
                <p key={i} className="text-[10px] text-gray-400">
                  {e.source} → {e.target}:{" "}
                  <span className="text-yellow-400">{e.condition}</span>
                </p>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
