import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { OutputNodeData } from "@/types";

const ArrowLeftIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M19 12H5" />
    <path d="m12 19-7-7 7-7" />
  </svg>
);

export const OutputNode = memo(function OutputNode({
  data,
  selected,
}: NodeProps) {
  const outputData = data as unknown as OutputNodeData;
  return (
    <BaseNodeShell
      data={outputData}
      selected={selected}
      icon={<ArrowLeftIcon />}
    >
      <p className="font-mono text-[10px] opacity-70">
        format: {outputData.config.outputFormat}
      </p>
    </BaseNodeShell>
  );
});
