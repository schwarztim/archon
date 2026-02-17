import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { DelayNodeData } from "@/types";

const TimerIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <line x1="10" x2="14" y1="2" y2="2" />
    <line x1="12" x2="15" y1="14" y2="11" />
    <circle cx="12" cy="14" r="8" />
  </svg>
);

export const DelayNode = memo(function DelayNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as DelayNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<TimerIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.delayMs}ms
      </p>
    </BaseNodeShell>
  );
});
