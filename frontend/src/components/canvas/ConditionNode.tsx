import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { ConditionNodeData } from "@/types";
import type { ConditionGroup } from "@/types/nodeTypes";

const GitBranchIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <line x1="6" x2="6" y1="3" y2="15" />
    <circle cx="18" cy="6" r="3" />
    <circle cx="6" cy="18" r="3" />
    <path d="M18 9a9 9 0 0 1-9 9" />
  </svg>
);

export const ConditionNode = memo(function ConditionNode({
  data,
  selected,
}: NodeProps) {
  const condData = data as unknown as ConditionNodeData;
  const conditions = condData.config.conditions as ConditionGroup | undefined;
  const condCount = conditions?.conditions?.length ?? 0;

  return (
    <BaseNodeShell
      data={condData}
      selected={selected}
      icon={<GitBranchIcon />}
    >
      {condCount > 0 ? (
        <p className="font-mono text-[10px] opacity-70 truncate max-w-[160px]">
          {condCount} condition{condCount !== 1 ? "s" : ""} ({conditions?.logic})
        </p>
      ) : condData.config.expression ? (
        <p className="font-mono text-[10px] opacity-70 truncate max-w-[160px]">
          {String(condData.config.expression)}
        </p>
      ) : null}
    </BaseNodeShell>
  );
});
