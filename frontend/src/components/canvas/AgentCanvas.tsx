import { useCallback, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type NodeTypes,
  type OnSelectionChangeFunc,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useCanvasStore } from "@/stores/canvasStore";
import { LLMNode } from "./LLMNode";
import { ToolNode } from "./ToolNode";
import { ConditionNode } from "./ConditionNode";
import { InputNode } from "./InputNode";
import { OutputNode } from "./OutputNode";
import { WebhookTriggerNode } from "./WebhookTriggerNode";
import { ScheduleTriggerNode } from "./ScheduleTriggerNode";
import { StreamOutputNode } from "./StreamOutputNode";
import { EmbeddingNode } from "./EmbeddingNode";
import { VisionNode } from "./VisionNode";
import { StructuredOutputNode } from "./StructuredOutputNode";
import { MCPToolNode } from "./MCPToolNode";
import { HTTPRequestNode } from "./HTTPRequestNode";
import { DatabaseQueryNode } from "./DatabaseQueryNode";
import { FunctionCallNode } from "./FunctionCallNode";
import { SwitchNode } from "./SwitchNode";
import { LoopNode } from "./LoopNode";
import { ParallelNode } from "./ParallelNode";
import { MergeNode } from "./MergeNode";
import { DelayNode } from "./DelayNode";
import { VectorSearchNode } from "./VectorSearchNode";
import { DocumentLoaderNode } from "./DocumentLoaderNode";
import { HumanApprovalNode } from "./HumanApprovalNode";
import { HumanInputNode } from "./HumanInputNode";
import { DLPScanNode } from "./DLPScanNode";
import { CostGateNode } from "./CostGateNode";
import { SubAgentNode } from "./SubAgentNode";
import type { CustomNodeData, PaletteItem } from "@/types";
import { generateNodeId } from "@/utils/cn";

const nodeTypes: NodeTypes = {
  llmNode: LLMNode,
  toolNode: ToolNode,
  conditionNode: ConditionNode,
  inputNode: InputNode,
  outputNode: OutputNode,
  webhookTriggerNode: WebhookTriggerNode,
  scheduleTriggerNode: ScheduleTriggerNode,
  streamOutputNode: StreamOutputNode,
  embeddingNode: EmbeddingNode,
  visionNode: VisionNode,
  structuredOutputNode: StructuredOutputNode,
  mcpToolNode: MCPToolNode,
  httpRequestNode: HTTPRequestNode,
  databaseQueryNode: DatabaseQueryNode,
  functionCallNode: FunctionCallNode,
  switchNode: SwitchNode,
  loopNode: LoopNode,
  parallelNode: ParallelNode,
  mergeNode: MergeNode,
  delayNode: DelayNode,
  vectorSearchNode: VectorSearchNode,
  documentLoaderNode: DocumentLoaderNode,
  humanApprovalNode: HumanApprovalNode,
  humanInputNode: HumanInputNode,
  dlpScanNode: DLPScanNode,
  costGateNode: CostGateNode,
  subAgentNode: SubAgentNode,
};

export function AgentCanvas() {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    selectNode,
  } = useCanvasStore();

  const onSelectionChange: OnSelectionChangeFunc = useCallback(
    ({ nodes: selectedNodes }) => {
      const selected = selectedNodes[0];
      selectNode(selected?.id ?? null);
    },
    [selectNode],
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData("application/archon-node");
      if (!raw) return;

      const item = JSON.parse(raw) as PaletteItem;
      const wrapper = reactFlowWrapper.current;
      if (!wrapper) return;

      const bounds = wrapper.getBoundingClientRect();
      const position = {
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      };

      addNode({
        id: generateNodeId(),
        type: item.type,
        position,
        data: { ...item.defaultData } as CustomNodeData,
      });
    },
    [addNode],
  );

  const memoNodeTypes = useMemo(() => nodeTypes, []);

  return (
    <div ref={reactFlowWrapper} className="h-full w-full" role="application" aria-label="Agent workflow canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={onSelectionChange}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={memoNodeTypes}
        fitView
        snapToGrid
        snapGrid={[16, 16]}
        deleteKeyCode={["Backspace", "Delete"]}
        className="bg-background"
      >
        <Background gap={16} size={1} />
        <Controls className="!bg-card !border-border !shadow-md" aria-label="Canvas zoom controls" />
        <MiniMap
          className="!bg-card !border-border"
          maskColor="rgba(0,0,0,0.2)"
          aria-label="Canvas minimap"
        />
      </ReactFlow>
    </div>
  );
}
