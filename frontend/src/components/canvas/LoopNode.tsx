import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { LoopNodeData } from "@/types";

const RepeatIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m17 2 4 4-4 4" />
    <path d="M3 11v-1a4 4 0 0 1 4-4h14" />
    <path d="m7 22-4-4 4-4" />
    <path d="M21 13v1a4 4 0 0 1-4 4H3" />
  </svg>
);

export const LoopNode = memo(function LoopNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as LoopNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<RepeatIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.loopType} · max={nodeData.config.maxIterations}
      </p>
    </BaseNodeShell>
  );
});
