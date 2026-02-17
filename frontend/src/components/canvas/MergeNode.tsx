import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { MergeNodeData } from "@/types";

const MergeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m8 6 4-4 4 4" />
    <path d="M12 2v10.3a4 4 0 0 1-1.172 2.872L4 22" />
    <path d="m20 22-5-5" />
  </svg>
);

export const MergeNode = memo(function MergeNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as MergeNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<MergeIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        strategy: {nodeData.config.strategy}
      </p>
    </BaseNodeShell>
  );
});
