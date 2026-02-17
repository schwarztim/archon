import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { MCPToolNodeData } from "@/types";

const PlugIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 22v-5" />
    <path d="M9 8V2" />
    <path d="M15 8V2" />
    <path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z" />
  </svg>
);

export const MCPToolNode = memo(function MCPToolNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as MCPToolNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<PlugIcon />}>
      {nodeData.config.serverName && (
        <p className="font-mono text-[10px] opacity-70">
          {nodeData.config.serverName}/{nodeData.config.toolName}
        </p>
      )}
    </BaseNodeShell>
  );
});
