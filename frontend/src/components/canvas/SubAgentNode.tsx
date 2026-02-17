import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { SubAgentNodeData } from "@/types";

const BotIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 8V4H8" />
    <rect width="16" height="12" x="4" y="8" rx="2" />
    <path d="M2 14h2" />
    <path d="M20 14h2" />
    <path d="M15 13v2" />
    <path d="M9 13v2" />
  </svg>
);

export const SubAgentNode = memo(function SubAgentNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as SubAgentNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<BotIcon />}>
      {nodeData.config.agentName && (
        <p className="font-mono text-[10px] opacity-70">
          {nodeData.config.agentName}
        </p>
      )}
    </BaseNodeShell>
  );
});
