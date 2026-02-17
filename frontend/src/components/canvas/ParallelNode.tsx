import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { ParallelNodeData } from "@/types";

const GitForkIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="18" r="3" />
    <circle cx="6" cy="6" r="3" />
    <circle cx="18" cy="6" r="3" />
    <path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9" />
    <path d="M12 12v3" />
  </svg>
);

export const ParallelNode = memo(function ParallelNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as ParallelNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<GitForkIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.branches} branches
      </p>
    </BaseNodeShell>
  );
});
