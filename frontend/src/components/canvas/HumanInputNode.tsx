import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { HumanInputNodeData } from "@/types";

const MessageSquareIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

export const HumanInputNode = memo(function HumanInputNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as HumanInputNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<MessageSquareIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        type: {nodeData.config.inputType}
      </p>
    </BaseNodeShell>
  );
});
