import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { HumanApprovalNodeData } from "@/types";

const UserCheckIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <polyline points="16 11 18 13 22 9" />
  </svg>
);

export const HumanApprovalNode = memo(function HumanApprovalNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as HumanApprovalNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<UserCheckIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        timeout: {nodeData.config.timeoutMinutes}m
      </p>
    </BaseNodeShell>
  );
});
