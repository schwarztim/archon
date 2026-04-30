/**
 * Backend↔frontend schema parity for node serialization.
 *
 * Phase 3, WS15. Single source of truth for the canonical (wire-format)
 * shape of every node configuration the canvas serializes. The discriminated
 * union below MUST stay in lockstep with the backend's
 * ``backend/app/services/node_executors/`` registry — the parity gate at
 * ``scripts/check-frontend-backend-parity.py`` enforces this.
 *
 * Source-of-truth references:
 *   - backend/app/services/node_executors/__init__.py — @register decorators
 *   - backend/app/services/node_executors/status_registry.py — NODE_STATUS
 *   - backend/app/services/node_executors/<file>.py — config.get(...) accessors
 *   - docs/feature-matrix.yaml — categories.node_executors
 *
 * NodeKind values mirror the backend node_type strings exactly. Each
 * specific config interface is derived from the executor's ``ctx.config``
 * accessor pattern (camelCase keys are canonical; some executors accept
 * snake_case fallbacks but the frontend always emits camelCase).
 */

/** Production-readiness classification. Mirrors backend NodeStatus enum. */
export type NodeStatus = "production" | "beta" | "stub" | "blocked" | "designed";

/**
 * Canonical node_type discriminator. MUST match the keys registered via
 * ``@register("...")`` in backend/app/services/node_executors/.
 *
 * 28 entries — kept sorted alphabetically within category groups.
 */
export type NodeKind =
  // ── Triggers / IO ──────────────────────────────────────────────────
  | "inputNode"
  | "outputNode"
  | "webhookTriggerNode"
  | "scheduleTriggerNode"
  // ── Models ────────────────────────────────────────────────────────
  | "llmNode"
  | "embeddingNode"
  | "visionNode"
  | "structuredOutputNode"
  | "streamOutputNode"
  // ── Tools ─────────────────────────────────────────────────────────
  | "toolNode"
  | "mcpToolNode"
  | "httpRequestNode"
  | "databaseQueryNode"
  | "functionCallNode"
  // ── Logic / control flow ──────────────────────────────────────────
  | "conditionNode"
  | "switchNode"
  | "loopNode"
  | "parallelNode"
  | "mergeNode"
  | "delayNode"
  // ── RAG ───────────────────────────────────────────────────────────
  | "vectorSearchNode"
  | "documentLoaderNode"
  // ── Human in the loop ─────────────────────────────────────────────
  | "humanApprovalNode"
  | "humanInputNode"
  // ── Security / governance ─────────────────────────────────────────
  | "dlpScanNode"
  | "costGateNode"
  // ── Composition ───────────────────────────────────────────────────
  | "subAgentNode"
  | "subWorkflowNode";

/**
 * Frozen array of every NodeKind. Use this when you need to iterate at
 * runtime — for instance, in the parity test below or in the palette.
 *
 * The compile-time exhaustiveness check at the bottom of this file
 * guarantees this array stays in sync with the union.
 */
export const ALL_NODE_KINDS: readonly NodeKind[] = [
  "inputNode",
  "outputNode",
  "webhookTriggerNode",
  "scheduleTriggerNode",
  "llmNode",
  "embeddingNode",
  "visionNode",
  "structuredOutputNode",
  "streamOutputNode",
  "toolNode",
  "mcpToolNode",
  "httpRequestNode",
  "databaseQueryNode",
  "functionCallNode",
  "conditionNode",
  "switchNode",
  "loopNode",
  "parallelNode",
  "mergeNode",
  "delayNode",
  "vectorSearchNode",
  "documentLoaderNode",
  "humanApprovalNode",
  "humanInputNode",
  "dlpScanNode",
  "costGateNode",
  "subAgentNode",
  "subWorkflowNode",
] as const;

/**
 * Common fields every serialized node carries. ``id`` and ``name`` are
 * canvas concerns; ``type`` is the discriminator the backend dispatches on.
 */
export interface BaseNodeConfig<K extends NodeKind = NodeKind> {
  id: string;
  name: string;
  type: K;
}

// ─── Triggers / IO ────────────────────────────────────────────────────

export interface InputNodeConfig extends BaseNodeConfig<"inputNode"> {
  config: {
    initialInput?: Record<string, unknown> | unknown[] | string | number | boolean | null;
    inputType?: string;
    defaultValue?: string;
  };
}

export interface OutputNodeConfig extends BaseNodeConfig<"outputNode"> {
  config: {
    outputKey?: string;
    outputFormat?: string;
  };
}

export interface WebhookTriggerNodeConfig extends BaseNodeConfig<"webhookTriggerNode"> {
  config: {
    path?: string;
    method?: string;
  };
}

export interface ScheduleTriggerNodeConfig extends BaseNodeConfig<"scheduleTriggerNode"> {
  config: {
    cron: string;
    timezone?: string;
    cronExpression?: string;
  };
}

// ─── Models ──────────────────────────────────────────────────────────

export interface LLMNodeConfig extends BaseNodeConfig<"llmNode"> {
  config: {
    model: string;
    prompt?: string;
    userPrompt?: string;
    systemPrompt?: string;
    temperature?: number;
    maxTokens?: number;
  };
}

export interface EmbeddingNodeConfig extends BaseNodeConfig<"embeddingNode"> {
  config: {
    model: string;
    text?: string;
    dimensions?: number;
  };
}

export interface VisionNodeConfig extends BaseNodeConfig<"visionNode"> {
  config: {
    model: string;
    imageUrl?: string;
    maxTokens?: number;
    detail?: "low" | "high" | "auto";
  };
}

export interface StructuredOutputNodeConfig extends BaseNodeConfig<"structuredOutputNode"> {
  config: {
    model: string;
    schema: Record<string, unknown> | string;
    temperature?: number;
  };
}

export interface StreamOutputNodeConfig extends BaseNodeConfig<"streamOutputNode"> {
  config: {
    format?: string;
    chunkSize?: number;
  };
}

// ─── Tools ───────────────────────────────────────────────────────────

export interface ToolNodeConfig extends BaseNodeConfig<"toolNode"> {
  config: {
    toolName: string;
    parameters?: Record<string, unknown>;
  };
}

export interface MCPToolNodeConfig extends BaseNodeConfig<"mcpToolNode"> {
  config: {
    serverName: string;
    toolName: string;
    parameters?: Record<string, unknown>;
  };
}

/** HTTP authentication mode for httpRequestNode. */
export type HTTPAuthType = "none" | "bearer" | "basic" | "api_key";

export interface HTTPRequestNodeConfig extends BaseNodeConfig<"httpRequestNode"> {
  config: {
    method: string;
    url: string;
    headers?: Array<{ key: string; value: string }> | Record<string, string>;
    authType?: HTTPAuthType;
    authToken?: string;
    authHeader?: string;
    body?: unknown;
    timeoutSeconds?: number;
  };
}

export interface DatabaseQueryNodeConfig extends BaseNodeConfig<"databaseQueryNode"> {
  config: {
    query: string;
    connectorId?: string;
    dbType?: string;
  };
}

export interface FunctionCallNodeConfig extends BaseNodeConfig<"functionCallNode"> {
  config: {
    functionName: string;
    parameters?: Record<string, unknown>;
    code?: string;
  };
}

// ─── Logic / control flow ────────────────────────────────────────────

/** A single condition row for the visual condition builder. */
export interface ConditionRow {
  field: string;
  operator:
    | "equals"
    | "not_equals"
    | "contains"
    | "gt"
    | "lt"
    | "gte"
    | "lte"
    | "starts_with"
    | "ends_with";
  value: string;
}

/** Group of condition rows joined by AND/OR. */
export interface ConditionGroup {
  logic: "AND" | "OR";
  conditions: ConditionRow[];
}

export interface ConditionNodeConfig extends BaseNodeConfig<"conditionNode"> {
  config: {
    expression?: string;
    conditions?: ConditionGroup;
    trueBranch?: string;
    falseBranch?: string;
  };
}

export interface SwitchNodeConfig extends BaseNodeConfig<"switchNode"> {
  config: {
    expression: string;
    cases: Array<{ value: string | number | boolean; branch: string }>;
  };
}

export interface LoopNodeConfig extends BaseNodeConfig<"loopNode"> {
  config: {
    maxIterations?: number;
    condition?: string;
    iterationVar?: string;
  };
}

export interface ParallelNodeConfig extends BaseNodeConfig<"parallelNode"> {
  config: {
    executionMode?: "all" | "any" | "n_of_m";
    n?: number;
    branches?: number;
  };
}

export interface MergeNodeConfig extends BaseNodeConfig<"mergeNode"> {
  config: {
    strategy?: "concat" | "merge" | "first" | "all";
  };
}

export interface DelayNodeConfig extends BaseNodeConfig<"delayNode"> {
  config: {
    seconds?: number;
    delayMs?: number;
  };
}

// ─── RAG ─────────────────────────────────────────────────────────────

export interface VectorSearchNodeConfig extends BaseNodeConfig<"vectorSearchNode"> {
  config: {
    collection: string;
    query?: string;
    topK?: number;
    threshold?: number;
  };
}

export interface DocumentLoaderNodeConfig extends BaseNodeConfig<"documentLoaderNode"> {
  config: {
    source: string;
    chunkSize?: number;
    overlap?: number;
  };
}

// ─── Human in the loop ───────────────────────────────────────────────

export interface HumanApprovalNodeConfig extends BaseNodeConfig<"humanApprovalNode"> {
  config: {
    approvers?: string[];
    prompt?: string;
    timeoutHours?: number;
    message?: string;
  };
}

export interface HumanInputNodeConfig extends BaseNodeConfig<"humanInputNode"> {
  config: {
    prompt?: string;
    inputType?: string;
    fields?: Array<{ name: string; type: string; required?: boolean }>;
  };
}

// ─── Security / governance ───────────────────────────────────────────

export interface DLPScanNodeConfig extends BaseNodeConfig<"dlpScanNode"> {
  config: {
    actionOnViolation?: "flag" | "block";
    inputKey?: string;
    policyId?: string;
  };
}

export interface CostGateNodeConfig extends BaseNodeConfig<"costGateNode"> {
  config: {
    maxUsd?: number;
    maxCost?: number;
    currency?: string;
  };
}

// ─── Composition ─────────────────────────────────────────────────────

export interface SubAgentNodeConfig extends BaseNodeConfig<"subAgentNode"> {
  config: {
    agentId?: string;
    agentDefinition?: Record<string, unknown>;
    input?: Record<string, unknown>;
  };
}

export interface SubWorkflowNodeConfig extends BaseNodeConfig<"subWorkflowNode"> {
  config: {
    workflowId?: string;
    workflowDefinition?: Record<string, unknown>;
  };
}

// ─── Discriminated union ──────────────────────────────────────────────

/**
 * Discriminated union over every supported node type. ``type`` is the
 * discriminator — TypeScript narrows ``config`` automatically once you
 * switch on it.
 */
export type NodeConfig =
  | InputNodeConfig
  | OutputNodeConfig
  | WebhookTriggerNodeConfig
  | ScheduleTriggerNodeConfig
  | LLMNodeConfig
  | EmbeddingNodeConfig
  | VisionNodeConfig
  | StructuredOutputNodeConfig
  | StreamOutputNodeConfig
  | ToolNodeConfig
  | MCPToolNodeConfig
  | HTTPRequestNodeConfig
  | DatabaseQueryNodeConfig
  | FunctionCallNodeConfig
  | ConditionNodeConfig
  | SwitchNodeConfig
  | LoopNodeConfig
  | ParallelNodeConfig
  | MergeNodeConfig
  | DelayNodeConfig
  | VectorSearchNodeConfig
  | DocumentLoaderNodeConfig
  | HumanApprovalNodeConfig
  | HumanInputNodeConfig
  | DLPScanNodeConfig
  | CostGateNodeConfig
  | SubAgentNodeConfig
  | SubWorkflowNodeConfig;

/**
 * Compile-time exhaustiveness check. If a NodeKind is added to the union
 * but not to ``ALL_NODE_KINDS``, this assignment produces a TS error —
 * narrowing ``never`` is the standard exhaustiveness pattern.
 */
type _NodeKindIsExhaustive = Exclude<NodeKind, (typeof ALL_NODE_KINDS)[number]> extends never
  ? true
  : never;
// Force the compiler to actually evaluate the conditional above. If the
// alias resolves to ``never`` (i.e. some NodeKind is missing from
// ALL_NODE_KINDS), the assignment fails to type-check.
export const _NODE_KIND_EXHAUSTIVE_GUARD: _NodeKindIsExhaustive = true;
