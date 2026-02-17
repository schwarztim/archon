import type { Node, Edge } from "@xyflow/react";

/** Supported custom node categories */
export type NodeCategory =
  | "llm"
  | "tool"
  | "condition"
  | "input"
  | "output"
  | "transform"
  | "custom"
  | "rag"
  | "human"
  | "security"
  | "subagent";

/** Port direction */
export type PortDirection = "input" | "output";

/** Data types that can flow between nodes */
export type PortDataType = "string" | "number" | "boolean" | "object" | "any";

/** A port (handle) on a node */
export interface NodePort {
  id: string;
  label: string;
  direction: PortDirection;
  dataType: PortDataType;
  required?: boolean;
}

/** Base data common to all custom nodes */
export interface BaseNodeData extends Record<string, unknown> {
  label: string;
  category: NodeCategory;
  description?: string;
  ports: NodePort[];
  config: Record<string, unknown>;
}

/** LLM-specific node data */
export interface LLMNodeData extends BaseNodeData {
  category: "llm";
  config: {
    model: string;
    temperature: number;
    maxTokens: number;
    systemPrompt: string;
    [key: string]: unknown;
  };
}

/** Tool-specific node data */
export interface ToolNodeData extends BaseNodeData {
  category: "tool";
  config: {
    toolName: string;
    parameters: Record<string, unknown>;
    [key: string]: unknown;
  };
}

/** Condition-specific node data */
export interface ConditionNodeData extends BaseNodeData {
  category: "condition";
  config: {
    expression: string;
    [key: string]: unknown;
  };
}

/** Input-specific node data */
export interface InputNodeData extends BaseNodeData {
  category: "input";
  config: {
    inputType: string;
    defaultValue?: string;
    [key: string]: unknown;
  };
}

/** Output-specific node data */
export interface OutputNodeData extends BaseNodeData {
  category: "output";
  config: {
    outputFormat: string;
    [key: string]: unknown;
  };
}

/** Webhook trigger node data */
export interface WebhookTriggerNodeData extends BaseNodeData {
  category: "input";
  config: {
    method: string;
    path: string;
    [key: string]: unknown;
  };
}

/** Schedule trigger node data */
export interface ScheduleTriggerNodeData extends BaseNodeData {
  category: "input";
  config: {
    cron: string;
    timezone: string;
    [key: string]: unknown;
  };
}

/** Stream output node data */
export interface StreamOutputNodeData extends BaseNodeData {
  category: "output";
  config: {
    format: string;
    chunkSize: number;
    [key: string]: unknown;
  };
}

/** Embedding node data */
export interface EmbeddingNodeData extends BaseNodeData {
  category: "llm";
  config: {
    model: string;
    dimensions: number;
    [key: string]: unknown;
  };
}

/** Vision node data */
export interface VisionNodeData extends BaseNodeData {
  category: "llm";
  config: {
    model: string;
    maxTokens: number;
    detail: string;
    [key: string]: unknown;
  };
}

/** Structured output node data */
export interface StructuredOutputNodeData extends BaseNodeData {
  category: "llm";
  config: {
    model: string;
    schema: string;
    temperature: number;
    [key: string]: unknown;
  };
}

/** MCP tool node data */
export interface MCPToolNodeData extends BaseNodeData {
  category: "tool";
  config: {
    serverName: string;
    toolName: string;
    [key: string]: unknown;
  };
}

/** HTTP request node data */
export interface HTTPRequestNodeData extends BaseNodeData {
  category: "tool";
  config: {
    method: string;
    url: string;
    headers: string;
    body: string;
    [key: string]: unknown;
  };
}

/** Database query node data */
export interface DatabaseQueryNodeData extends BaseNodeData {
  category: "tool";
  config: {
    connectionString: string;
    query: string;
    dbType: string;
    [key: string]: unknown;
  };
}

/** Function call node data */
export interface FunctionCallNodeData extends BaseNodeData {
  category: "tool";
  config: {
    functionName: string;
    code: string;
    [key: string]: unknown;
  };
}

/** Switch node data */
export interface SwitchNodeData extends BaseNodeData {
  category: "condition";
  config: {
    expression: string;
    cases: string;
    [key: string]: unknown;
  };
}

/** Loop node data */
export interface LoopNodeData extends BaseNodeData {
  category: "condition";
  config: {
    loopType: string;
    maxIterations: number;
    [key: string]: unknown;
  };
}

/** Parallel node data */
export interface ParallelNodeData extends BaseNodeData {
  category: "condition";
  config: {
    branches: number;
    [key: string]: unknown;
  };
}

/** Merge node data */
export interface MergeNodeData extends BaseNodeData {
  category: "condition";
  config: {
    strategy: string;
    [key: string]: unknown;
  };
}

/** Delay node data */
export interface DelayNodeData extends BaseNodeData {
  category: "condition";
  config: {
    delayMs: number;
    [key: string]: unknown;
  };
}

/** Vector search node data */
export interface VectorSearchNodeData extends BaseNodeData {
  category: "rag";
  config: {
    collection: string;
    topK: number;
    threshold: number;
    [key: string]: unknown;
  };
}

/** Document loader node data */
export interface DocumentLoaderNodeData extends BaseNodeData {
  category: "rag";
  config: {
    source: string;
    chunkSize: number;
    overlap: number;
    [key: string]: unknown;
  };
}

/** Human approval node data */
export interface HumanApprovalNodeData extends BaseNodeData {
  category: "human";
  config: {
    approver: string;
    timeoutMinutes: number;
    message: string;
    [key: string]: unknown;
  };
}

/** Human input node data */
export interface HumanInputNodeData extends BaseNodeData {
  category: "human";
  config: {
    prompt: string;
    inputType: string;
    [key: string]: unknown;
  };
}

/** DLP scan node data */
export interface DLPScanNodeData extends BaseNodeData {
  category: "security";
  config: {
    policyId: string;
    action: string;
    [key: string]: unknown;
  };
}

/** Cost gate node data */
export interface CostGateNodeData extends BaseNodeData {
  category: "security";
  config: {
    maxCost: number;
    currency: string;
    [key: string]: unknown;
  };
}

/** Sub-agent node data */
export interface SubAgentNodeData extends BaseNodeData {
  category: "subagent";
  config: {
    agentId: string;
    agentName: string;
    [key: string]: unknown;
  };
}

/** Union of all node data types */
export type CustomNodeData =
  | LLMNodeData
  | ToolNodeData
  | ConditionNodeData
  | InputNodeData
  | OutputNodeData
  | WebhookTriggerNodeData
  | ScheduleTriggerNodeData
  | StreamOutputNodeData
  | EmbeddingNodeData
  | VisionNodeData
  | StructuredOutputNodeData
  | MCPToolNodeData
  | HTTPRequestNodeData
  | DatabaseQueryNodeData
  | FunctionCallNodeData
  | SwitchNodeData
  | LoopNodeData
  | ParallelNodeData
  | MergeNodeData
  | DelayNodeData
  | VectorSearchNodeData
  | DocumentLoaderNodeData
  | HumanApprovalNodeData
  | HumanInputNodeData
  | DLPScanNodeData
  | CostGateNodeData
  | SubAgentNodeData;

/** Typed React Flow node */
export type AppNode = Node<CustomNodeData>;

/** Typed React Flow edge */
export type AppEdge = Edge;

/** Agent definition for save/load */
export interface AgentDefinition {
  id: string;
  name: string;
  description?: string;
  nodes: AppNode[];
  edges: AppEdge[];
  version: number;
  createdAt: string;
  updatedAt: string;
}

/** API envelope response */
export interface ApiResponse<T> {
  data: T;
  meta: {
    request_id: string;
    timestamp: string;
    pagination?: {
      total: number;
      limit: number;
      offset: number;
    };
  };
}

/** API error response */
export interface ApiError {
  errors: Array<{
    code: string;
    message: string;
    field?: string;
    details?: Record<string, unknown>;
  }>;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

/** Node palette item (template for creating nodes) */
export interface PaletteItem {
  type: string;
  category: NodeCategory;
  label: string;
  description: string;
  icon: string;
  defaultData: CustomNodeData;
}
