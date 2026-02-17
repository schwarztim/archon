import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { DLPScanNodeData } from "@/types";

const ShieldCheckIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

export const DLPScanNode = memo(function DLPScanNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as DLPScanNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<ShieldCheckIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        action: {nodeData.config.action}
      </p>
    </BaseNodeShell>
  );
});
