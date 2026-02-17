/**
 * NodeTypeRegistry — declarative schema for every canvas node type.
 *
 * Each entry maps a React Flow node type key to its metadata:
 * icon, label, category, defaultConfig, and a validate function.
 */

import type { NodeCategory, CustomNodeData } from "@/types";

/** Single condition row for visual condition builder */
export interface ConditionRow {
  field: string;
  operator: "equals" | "not_equals" | "contains" | "gt" | "lt" | "gte" | "lte" | "starts_with" | "ends_with";
  value: string;
}

/** Condition group with AND/OR logic */
export interface ConditionGroup {
  logic: "AND" | "OR";
  conditions: ConditionRow[];
}

/** Key-value pair used in headers, parameters, etc. */
export interface KeyValuePair {
  key: string;
  value: string;
}

/** HTTP Auth type for HTTP request nodes */
export type HTTPAuthType = "none" | "bearer" | "basic" | "api_key";

/** Validation error for a node */
export interface NodeValidationError {
  nodeId: string;
  message: string;
}

/** Validation result for the entire graph */
export interface GraphValidationResult {
  valid: boolean;
  errors: NodeValidationError[];
}

/** Operator options for condition builder */
export const CONDITION_OPERATORS: Array<{ value: ConditionRow["operator"]; label: string }> = [
  { value: "equals", label: "Equals" },
  { value: "not_equals", label: "Not Equals" },
  { value: "contains", label: "Contains" },
  { value: "gt", label: "Greater Than" },
  { value: "lt", label: "Less Than" },
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
  { value: "starts_with", label: "Starts With" },
  { value: "ends_with", label: "Ends With" },
];

/** Registry entry for a single node type */
export interface NodeTypeDefinition {
  type: string;
  label: string;
  category: NodeCategory;
  description: string;
  icon: string;
  /** Validate node-specific config. Returns error messages or empty array. */
  validate: (data: CustomNodeData) => string[];
}

/** Validate an LLM node */
function validateLLM(data: CustomNodeData): string[] {
  const errors: string[] = [];
  if (!data.config.model) errors.push("Model is required.");
  const temp = Number(data.config.temperature ?? 0);
  if (temp < 0 || temp > 2) errors.push("Temperature must be 0–2.");
  return errors;
}

/** Validate a condition node */
function validateCondition(data: CustomNodeData): string[] {
  const errors: string[] = [];
  const conditions = data.config.conditions as ConditionGroup | undefined;
  const expression = data.config.expression as string | undefined;
  if (!conditions && !expression) {
    errors.push("At least one condition or expression is required.");
  }
  if (conditions?.conditions) {
    for (const row of conditions.conditions) {
      if (!row.field) errors.push("Condition field is required.");
    }
  }
  return errors;
}

/** Validate an HTTP request node */
function validateHTTPRequest(data: CustomNodeData): string[] {
  const errors: string[] = [];
  if (!data.config.url) errors.push("URL is required.");
  if (!data.config.method) errors.push("Method is required.");
  return errors;
}

/** Validate an MCP tool node */
function validateMCPTool(data: CustomNodeData): string[] {
  const errors: string[] = [];
  if (!data.config.serverName) errors.push("MCP server name is required.");
  if (!data.config.toolName) errors.push("Tool name is required.");
  return errors;
}

/** No-op validator for nodes that always pass */
function noValidation(): string[] {
  return [];
}

/** Full registry of all node types */
export const NODE_TYPE_REGISTRY: Record<string, NodeTypeDefinition> = {
  // Triggers
  inputNode: {
    type: "inputNode",
    label: "Input",
    category: "input",
    description: "Agent input / entry point",
    icon: "ArrowRightToLine",
    validate: noValidation,
  },
  webhookTriggerNode: {
    type: "webhookTriggerNode",
    label: "Webhook Trigger",
    category: "input",
    description: "Trigger via incoming webhook",
    icon: "Webhook",
    validate: (d) => (!d.config.path ? ["Webhook path is required."] : []),
  },
  scheduleTriggerNode: {
    type: "scheduleTriggerNode",
    label: "Schedule Trigger",
    category: "input",
    description: "Trigger on a cron schedule",
    icon: "Clock",
    validate: (d) => (!d.config.cron ? ["Cron expression is required."] : []),
  },

  // AI Models
  llmNode: {
    type: "llmNode",
    label: "LLM",
    category: "llm",
    description: "Large Language Model call",
    icon: "Brain",
    validate: validateLLM,
  },
  embeddingNode: {
    type: "embeddingNode",
    label: "Embedding",
    category: "llm",
    description: "Generate vector embeddings",
    icon: "Hash",
    validate: (d) => (!d.config.model ? ["Model is required."] : []),
  },
  visionNode: {
    type: "visionNode",
    label: "Vision",
    category: "llm",
    description: "Vision / multimodal model",
    icon: "Eye",
    validate: (d) => (!d.config.model ? ["Model is required."] : []),
  },
  structuredOutputNode: {
    type: "structuredOutputNode",
    label: "Structured Output",
    category: "llm",
    description: "JSON mode / structured output",
    icon: "Braces",
    validate: (d) => (!d.config.model ? ["Model is required."] : []),
  },

  // Tools
  toolNode: {
    type: "toolNode",
    label: "Tool",
    category: "tool",
    description: "External tool or API call",
    icon: "Wrench",
    validate: (d) => (!d.config.toolName ? ["Tool name is required."] : []),
  },
  mcpToolNode: {
    type: "mcpToolNode",
    label: "MCP Tool",
    category: "tool",
    description: "Model Context Protocol tool call",
    icon: "Plug",
    validate: validateMCPTool,
  },
  httpRequestNode: {
    type: "httpRequestNode",
    label: "HTTP Request",
    category: "tool",
    description: "HTTP / REST API call",
    icon: "Globe",
    validate: validateHTTPRequest,
  },
  databaseQueryNode: {
    type: "databaseQueryNode",
    label: "Database Query",
    category: "tool",
    description: "Execute a database query",
    icon: "Database",
    validate: (d) => (!d.config.query ? ["Query is required."] : []),
  },
  functionCallNode: {
    type: "functionCallNode",
    label: "Function",
    category: "tool",
    description: "Custom function / code execution",
    icon: "Code",
    validate: (d) => (!d.config.functionName ? ["Function name is required."] : []),
  },

  // Logic
  conditionNode: {
    type: "conditionNode",
    label: "Condition",
    category: "condition",
    description: "Branch based on a condition",
    icon: "GitBranch",
    validate: validateCondition,
  },
  switchNode: {
    type: "switchNode",
    label: "Switch",
    category: "condition",
    description: "Multi-branch switch statement",
    icon: "ListTree",
    validate: (d) => (!d.config.expression ? ["Switch expression is required."] : []),
  },
  loopNode: {
    type: "loopNode",
    label: "Loop",
    category: "condition",
    description: "Iterate over items or repeat",
    icon: "Repeat",
    validate: noValidation,
  },
  parallelNode: {
    type: "parallelNode",
    label: "Parallel",
    category: "condition",
    description: "Execute branches in parallel",
    icon: "GitFork",
    validate: noValidation,
  },
  mergeNode: {
    type: "mergeNode",
    label: "Merge",
    category: "condition",
    description: "Merge parallel branches",
    icon: "Merge",
    validate: noValidation,
  },
  delayNode: {
    type: "delayNode",
    label: "Delay",
    category: "condition",
    description: "Wait / delay execution",
    icon: "Timer",
    validate: (d) => (Number(d.config.delayMs) < 0 ? ["Delay must be ≥ 0."] : []),
  },

  // RAG
  vectorSearchNode: {
    type: "vectorSearchNode",
    label: "Vector Search",
    category: "rag",
    description: "Vector similarity search",
    icon: "Search",
    validate: (d) => (!d.config.collection ? ["Collection is required."] : []),
  },
  documentLoaderNode: {
    type: "documentLoaderNode",
    label: "Document Loader",
    category: "rag",
    description: "Load and chunk documents",
    icon: "FileText",
    validate: (d) => (!d.config.source ? ["Source is required."] : []),
  },

  // Human
  humanApprovalNode: {
    type: "humanApprovalNode",
    label: "Human Approval",
    category: "human",
    description: "Require human approval to proceed",
    icon: "UserCheck",
    validate: noValidation,
  },
  humanInputNode: {
    type: "humanInputNode",
    label: "Human Input",
    category: "human",
    description: "Request input from a human",
    icon: "MessageSquare",
    validate: noValidation,
  },

  // Security
  dlpScanNode: {
    type: "dlpScanNode",
    label: "DLP Scan",
    category: "security",
    description: "Scan for sensitive data (PII, secrets)",
    icon: "ShieldCheck",
    validate: noValidation,
  },
  costGateNode: {
    type: "costGateNode",
    label: "Cost Gate",
    category: "security",
    description: "Block if cost exceeds threshold",
    icon: "DollarSign",
    validate: (d) => (Number(d.config.maxCost) < 0 ? ["Max cost must be ≥ 0."] : []),
  },

  // Sub-agents
  subAgentNode: {
    type: "subAgentNode",
    label: "Sub-Agent",
    category: "subagent",
    description: "Invoke another agent",
    icon: "Bot",
    validate: (d) => (!d.config.agentId ? ["Agent ID is required."] : []),
  },
};

/** Validate the entire graph */
export function validateGraph(
  nodes: Array<{ id: string; type?: string; data: CustomNodeData }>,
  edges: Array<{ source: string; target: string }>,
): GraphValidationResult {
  const errors: NodeValidationError[] = [];

  // Check for at least 1 input/trigger and 1 output node
  const hasInput = nodes.some((n) => n.data.category === "input");
  const hasOutput = nodes.some((n) => n.data.category === "output");

  if (!hasInput) {
    errors.push({ nodeId: "", message: "Graph must have at least 1 Input/Trigger node." });
  }
  if (!hasOutput) {
    errors.push({ nodeId: "", message: "Graph must have at least 1 Output node." });
  }

  // Validate edges connect to existing nodes
  const nodeIds = new Set(nodes.map((n) => n.id));
  for (const edge of edges) {
    if (!nodeIds.has(edge.source)) {
      errors.push({ nodeId: edge.source, message: `Edge source "${edge.source}" not found.` });
    }
    if (!nodeIds.has(edge.target)) {
      errors.push({ nodeId: edge.target, message: `Edge target "${edge.target}" not found.` });
    }
  }

  // Per-node validation
  for (const node of nodes) {
    const def = NODE_TYPE_REGISTRY[node.type ?? ""];
    if (def) {
      const nodeErrors = def.validate(node.data);
      for (const msg of nodeErrors) {
        errors.push({ nodeId: node.id, message: msg });
      }
    }
  }

  return { valid: errors.length === 0, errors };
}
