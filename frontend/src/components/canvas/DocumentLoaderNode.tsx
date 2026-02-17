import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { BaseNodeShell } from "./BaseNode";
import type { DocumentLoaderNodeData } from "@/types";

const FileTextIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
    <path d="M14 2v4a2 2 0 0 0 2 2h4" />
    <path d="M10 13H8" />
    <path d="M16 17H8" />
    <path d="M16 13h-2" />
  </svg>
);

export const DocumentLoaderNode = memo(function DocumentLoaderNode({
  data,
  selected,
}: NodeProps) {
  const nodeData = data as unknown as DocumentLoaderNodeData;
  return (
    <BaseNodeShell data={nodeData} selected={selected} icon={<FileTextIcon />}>
      <p className="font-mono text-[10px] opacity-70">
        chunk={nodeData.config.chunkSize}
      </p>
    </BaseNodeShell>
  );
});
