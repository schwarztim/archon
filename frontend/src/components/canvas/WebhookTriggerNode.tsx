import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { WebhookTriggerNodeData } from "@/types";

const WebhookIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M18 16.98h-5.99c-1.1 0-1.95.94-2.48 1.9A4 4 0 0 1 2 17c.01-.7.2-1.4.57-2" />
    <path d="m6 17 3.13-5.78c.53-.97.1-2.18-.5-3.1a4 4 0 1 1 6.89-4.06" />
    <path d="m12 6 3.13 5.73C15.66 12.7 16.9 13 18 13a4 4 0 0 1 0 8H12" />
  </svg>
);

export const WebhookTriggerNode = memo(function WebhookTriggerNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as WebhookTriggerNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<WebhookIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.method} {nodeData.config.path}
      </p>
    </BaseNodeShell>
  );
});
