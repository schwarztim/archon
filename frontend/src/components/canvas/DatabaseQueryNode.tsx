import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { DatabaseQueryNodeData } from "@/types";

const DatabaseIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M3 5V19A9 3 0 0 0 21 19V5" />
    <path d="M3 12A9 3 0 0 0 21 12" />
  </svg>
);

export const DatabaseQueryNode = memo(function DatabaseQueryNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as DatabaseQueryNodeData;
  const query = String(nodeData.config.query ?? "");
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<DatabaseIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.dbType}
      </p>
      {query && (
        <p className="font-mono text-[10px] opacity-50 truncate max-w-[160px]">
          {query}
        </p>
      )}
    </BaseNodeShell>
  );
});
