import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { VectorSearchNodeData } from "@/types";

const SearchIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="8" />
    <path d="m21 21-4.3-4.3" />
  </svg>
);

export const VectorSearchNode = memo(function VectorSearchNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as VectorSearchNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<SearchIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.collection || "—"} · top={nodeData.config.topK}
      </p>
      <p className="font-mono text-[10px] opacity-50">
        threshold: {nodeData.config.threshold}
      </p>
    </BaseNodeShell>
  );
});
