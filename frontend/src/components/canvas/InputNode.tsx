import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { InputNodeData } from "@/types";

const ArrowRightIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14" />
    <path d="m12 5 7 7-7 7" />
  </svg>
);

export const InputNode = memo(function InputNode({
  data,
  selected,
}: NodeProps) {
  const inputData = data as unknown as InputNodeData;
  return (
    <BaseNodeShell
      data={inputData}
      selected={selected}
      icon={<ArrowRightIcon />}
    >
      <p className="font-mono text-[10px] opacity-70">
        type: {inputData.config.inputType}
      </p>
    </BaseNodeShell>
  );
});
