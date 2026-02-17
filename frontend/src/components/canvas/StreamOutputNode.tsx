import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { StreamOutputNodeData } from "@/types";

const RadioIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9" />
    <path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.4" />
    <circle cx="12" cy="12" r="2" />
    <path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.4" />
    <path d="M19.1 4.9C23 8.8 23 15.1 19.1 19" />
  </svg>
);

export const StreamOutputNode = memo(function StreamOutputNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as StreamOutputNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<RadioIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.format} · chunk={nodeData.config.chunkSize}
      </p>
    </BaseNodeShell>
  );
});
