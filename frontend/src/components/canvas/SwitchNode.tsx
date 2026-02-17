import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { SwitchNodeData } from "@/types";

const ListTreeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12h-8" />
    <path d="M21 6H8" />
    <path d="M21 18h-8" />
    <path d="M3 6v4c0 1.1.9 2 2 2h3" />
    <path d="M3 10v6c0 1.1.9 2 2 2h3" />
  </svg>
);

export const SwitchNode = memo(function SwitchNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as SwitchNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<ListTreeIcon />}>
      {nodeData.config.expression && (
        <p className="font-mono text-[10px] opacity-70 truncate max-w-[160px]">
          switch: {nodeData.config.expression}
        </p>
      )}
    </BaseNodeShell>
  );
});
