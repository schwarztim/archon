import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { FunctionCallNodeData } from "@/types";

const CodeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
);

export const FunctionCallNode = memo(function FunctionCallNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as FunctionCallNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<CodeIcon />}>
      {nodeData.config.functionName && (
        <p className="font-mono text-[10px] opacity-70">
          {nodeData.config.functionName}()
        </p>
      )}
    </BaseNodeShell>
  );
});
