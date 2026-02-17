import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { StructuredOutputNodeData } from "@/types";

const BracesIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1" />
    <path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1" />
  </svg>
);

export const StructuredOutputNode = memo(function StructuredOutputNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as StructuredOutputNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<BracesIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.model} · t={nodeData.config.temperature}
      </p>
    </BaseNodeShell>
  );
});
