import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { VisionNodeData } from "@/types";

const EyeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

export const VisionNode = memo(function VisionNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as VisionNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<EyeIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.model} · {nodeData.config.detail}
      </p>
    </BaseNodeShell>
  );
});
