import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { ScheduleTriggerNodeData } from "@/types";

const ClockIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

export const ScheduleTriggerNode = memo(function ScheduleTriggerNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as ScheduleTriggerNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<ClockIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        {nodeData.config.cron}
      </p>
    </BaseNodeShell>
  );
});
