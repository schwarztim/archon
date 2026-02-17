import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/utils/cn";
import type { BaseNodeData, NodeCategory } from "@/types";

const categoryColors: Record<NodeCategory, string> = {
  llm: "border-purple-500 bg-purple-500/10",
  tool: "border-blue-500 bg-blue-500/10",
  condition: "border-amber-500 bg-amber-500/10",
  input: "border-green-500 bg-green-500/10",
  output: "border-red-500 bg-red-500/10",
  transform: "border-cyan-500 bg-cyan-500/10",
  custom: "border-gray-500 bg-gray-500/10",
  rag: "border-teal-500 bg-teal-500/10",
  human: "border-orange-500 bg-orange-500/10",
  security: "border-rose-500 bg-rose-500/10",
  subagent: "border-indigo-500 bg-indigo-500/10",
};

const categoryHeaderColors: Record<NodeCategory, string> = {
  llm: "bg-purple-500",
  tool: "bg-blue-500",
  condition: "bg-amber-500",
  input: "bg-green-500",
  output: "bg-red-500",
  transform: "bg-cyan-500",
  custom: "bg-gray-500",
  rag: "bg-teal-500",
  human: "bg-orange-500",
  security: "bg-rose-500",
  subagent: "bg-indigo-500",
};

interface BaseNodeShellProps {
  data: BaseNodeData;
  selected: boolean | undefined;
  icon: React.ReactNode;
  children?: React.ReactNode;
}

/** Shared visual shell for all custom node types */
export const BaseNodeShell = memo(function BaseNodeShell({
  data,
  selected,
  icon,
  children,
}: BaseNodeShellProps) {
  const inputPorts = data.ports.filter((p) => p.direction === "input");
  const outputPorts = data.ports.filter((p) => p.direction === "output");

  return (
    <div
      className={cn(
        "min-w-[180px] rounded-lg border-2 shadow-md transition-shadow",
        categoryColors[data.category],
        selected && "ring-2 ring-ring shadow-lg",
      )}
      role="group"
      aria-label={`${data.label} node`}
    >
      {/* Header */}
      <div
        className={cn(
          "flex items-center gap-2 rounded-t-md px-3 py-2 text-white text-sm font-medium",
          categoryHeaderColors[data.category],
        )}
      >
        {icon}
        <span>{data.label}</span>
      </div>

      {/* Body */}
      <div className="px-3 py-2 text-xs text-muted-foreground">
        {data.description && <p className="mb-1">{data.description}</p>}
        {children}
      </div>

      {/* Input handles */}
      {inputPorts.map((port, i) => (
        <Handle
          key={port.id}
          type="target"
          position={Position.Left}
          id={port.id}
          style={{ top: `${((i + 1) / (inputPorts.length + 1)) * 100}%` }}
          className="!w-3 !h-3 !border-2 !border-background !bg-foreground"
          aria-label={`${port.label} input`}
        />
      ))}

      {/* Output handles */}
      {outputPorts.map((port, i) => (
        <Handle
          key={port.id}
          type="source"
          position={Position.Right}
          id={port.id}
          style={{ top: `${((i + 1) / (outputPorts.length + 1)) * 100}%` }}
          className="!w-3 !h-3 !border-2 !border-background !bg-foreground"
          aria-label={`${port.label} output`}
        />
      ))}
    </div>
  );
});

/** Generic custom node renderer that dispatches to BaseNodeShell */
export function createCustomNode(icon: React.ReactNode) {
  return memo(function CustomNode({ data, selected }: NodeProps) {
    return (
      <BaseNodeShell
        data={data as unknown as BaseNodeData}
        selected={selected}
        icon={icon}
      />
    );
  });
}
