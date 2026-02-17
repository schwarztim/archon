import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { ToolNodeData } from "@/types";

const WrenchIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
  </svg>
);

export const ToolNode = memo(function ToolNode({ data, selected }: NodeProps) {
  const toolData = data as unknown as ToolNodeData;
  return (
    <BaseNodeShell data={toolData} selected={selected} icon={<WrenchIcon />}>
      {toolData.config.toolName && (
        <p className="font-mono text-[10px] opacity-70">
          {toolData.config.toolName}
        </p>
      )}
    </BaseNodeShell>
  );
});
