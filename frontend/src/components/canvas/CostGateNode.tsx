import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { CostGateNodeData } from "@/types";

const DollarSignIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <line x1="12" x2="12" y1="2" y2="22" />
    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
  </svg>
);

export const CostGateNode = memo(function CostGateNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as CostGateNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<DollarSignIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        max: {nodeData.config.currency}{nodeData.config.maxCost}
      </p>
    </BaseNodeShell>
  );
});
