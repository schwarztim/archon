import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { HTTPRequestNodeData } from "@/types";

const GlobeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" />
    <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
    <path d="M2 12h20" />
  </svg>
);

export const HTTPRequestNode = memo(function HTTPRequestNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as HTTPRequestNodeData;
  const authType = String(nodeData.config.authType ?? "none");
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<GlobeIcon />}>
      <p className="font-mono text-[10px] opacity-70 truncate max-w-[160px]">
        {nodeData.config.method} {nodeData.config.url}
      </p>
      {authType !== "none" && (
        <p className="font-mono text-[10px] opacity-50">auth: {authType}</p>
      )}
    </BaseNodeShell>
  );
});
