import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { EmbeddingNodeData } from "@/types";

const HashIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <line x1="4" x2="20" y1="9" y2="9" />
    <line x1="4" x2="20" y1="15" y2="15" />
    <line x1="10" x2="8" y1="3" y2="21" />
    <line x1="16" x2="14" y1="3" y2="21" />
  </svg>
);

export const EmbeddingNode = memo(function EmbeddingNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as EmbeddingNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<HashIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.model} · d={nodeData.config.dimensions}
      </p>
    </BaseNodeShell>
  );
});
