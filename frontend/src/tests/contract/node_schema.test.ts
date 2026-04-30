/**
 * Contract test: frontend NodeKind discriminated union parity.
 *
 * Phase 3, WS15. Verifies that:
 *   1. Every NodeKind value is accepted by the discriminated union.
 *   2. Specific config interfaces narrow correctly via the ``type`` field.
 *   3. NodeConfig instances round-trip through JSON without losing data.
 *
 * Pairs with ``scripts/check-frontend-backend-parity.py``, which enforces
 * that ``ALL_NODE_KINDS`` matches the backend's @register decorators.
 */

import { describe, it, expect } from "vitest";
import {
  ALL_NODE_KINDS,
  type ConditionNodeConfig,
  type HTTPRequestNodeConfig,
  type LLMNodeConfig,
  type NodeConfig,
  type NodeKind,
  type SwitchNodeConfig,
  _NODE_KIND_EXHAUSTIVE_GUARD,
} from "@/types/nodes";

describe("NodeKind union", () => {
  it("contains exactly 28 node types (matches backend registry)", () => {
    // The backend has 28 @register decorators; ALL_NODE_KINDS must mirror that.
    expect(ALL_NODE_KINDS).toHaveLength(28);
  });

  it("ALL_NODE_KINDS members are unique", () => {
    const set = new Set(ALL_NODE_KINDS);
    expect(set.size).toBe(ALL_NODE_KINDS.length);
  });

  it("ALL_NODE_KINDS includes every expected backend node_type", () => {
    const expected: NodeKind[] = [
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
    ];
    for (const kind of expected) {
      expect(ALL_NODE_KINDS).toContain(kind);
    }
  });

  it("compile-time exhaustiveness guard is true", () => {
    // If a NodeKind exists in the union but not in ALL_NODE_KINDS, the
    // ``_NODE_KIND_EXHAUSTIVE_GUARD`` constant fails to type-check at
    // build time. Asserting it's truthy at runtime is the runtime witness.
    expect(_NODE_KIND_EXHAUSTIVE_GUARD).toBe(true);
  });
});

describe("NodeConfig discriminated union narrowing", () => {
  it("narrows LLMNodeConfig via type='llmNode'", () => {
    const node: NodeConfig = {
      id: "n1",
      name: "GPT-4",
      type: "llmNode",
      config: {
        model: "gpt-4o-mini",
        prompt: "Summarise the input.",
        temperature: 0.7,
        maxTokens: 512,
      },
    };
    if (node.type === "llmNode") {
      // Inside this block, ``node`` is narrowed to LLMNodeConfig — accessing
      // the model-specific fields must compile.
      expect(node.config.model).toBe("gpt-4o-mini");
      expect(node.config.temperature).toBe(0.7);
    } else {
      throw new Error("type guard failed");
    }
  });

  it("narrows ConditionNodeConfig via type='conditionNode'", () => {
    const node: NodeConfig = {
      id: "c1",
      name: "Check",
      type: "conditionNode",
      config: {
        expression: "x > 5",
        trueBranch: "approve",
        falseBranch: "reject",
      },
    };
    if (node.type === "conditionNode") {
      expect(node.config.expression).toBe("x > 5");
      expect(node.config.trueBranch).toBe("approve");
    }
  });

  it("narrows SwitchNodeConfig via type='switchNode'", () => {
    const node: NodeConfig = {
      id: "sw1",
      name: "Route",
      type: "switchNode",
      config: {
        expression: "input.category",
        cases: [
          { value: "a", branch: "branch-a" },
          { value: "b", branch: "branch-b" },
        ],
      },
    };
    if (node.type === "switchNode") {
      expect(node.config.cases).toHaveLength(2);
    }
  });

  it("narrows HTTPRequestNodeConfig via type='httpRequestNode'", () => {
    const node: NodeConfig = {
      id: "h1",
      name: "Fetch",
      type: "httpRequestNode",
      config: {
        method: "POST",
        url: "https://api.example.com/v1/search",
        authType: "bearer",
        authToken: "tok-abc",
        body: { query: "hello" },
        timeoutSeconds: 30,
      },
    };
    if (node.type === "httpRequestNode") {
      expect(node.config.method).toBe("POST");
      expect(node.config.authType).toBe("bearer");
    }
  });

  it("narrows StructuredOutputNodeConfig via type='structuredOutputNode'", () => {
    const node: NodeConfig = {
      id: "so1",
      name: "JSON",
      type: "structuredOutputNode",
      config: {
        model: "gpt-4o",
        schema: { type: "object", properties: { name: { type: "string" } } },
        temperature: 0,
      },
    };
    if (node.type === "structuredOutputNode") {
      expect(node.config.model).toBe("gpt-4o");
      expect(node.config.schema).toEqual({
        type: "object",
        properties: { name: { type: "string" } },
      });
    }
  });
});

describe("NodeConfig serialization round-trip", () => {
  it("LLM node serializes and re-parses without data loss", () => {
    const original: LLMNodeConfig = {
      id: "n1",
      name: "GPT",
      type: "llmNode",
      config: {
        model: "gpt-4o-mini",
        prompt: "Say hi",
        temperature: 0.5,
        maxTokens: 100,
      },
    };
    const json = JSON.stringify(original);
    const parsed = JSON.parse(json) as LLMNodeConfig;
    expect(parsed).toEqual(original);
    expect(parsed.type).toBe("llmNode");
    expect(parsed.config.model).toBe("gpt-4o-mini");
  });

  it("Condition node round-trips with nested ConditionGroup", () => {
    const original: ConditionNodeConfig = {
      id: "c1",
      name: "Check",
      type: "conditionNode",
      config: {
        conditions: {
          logic: "AND",
          conditions: [
            { field: "status", operator: "equals", value: "ok" },
            { field: "count", operator: "gt", value: "10" },
          ],
        },
      },
    };
    const parsed = JSON.parse(JSON.stringify(original)) as ConditionNodeConfig;
    expect(parsed.config.conditions?.logic).toBe("AND");
    expect(parsed.config.conditions?.conditions).toHaveLength(2);
    expect(parsed.config.conditions?.conditions[0]?.operator).toBe("equals");
  });

  it("HTTP node round-trips with mixed body type", () => {
    const original: HTTPRequestNodeConfig = {
      id: "h1",
      name: "Post",
      type: "httpRequestNode",
      config: {
        method: "POST",
        url: "https://api.example.com",
        headers: { "X-Custom": "value" },
        body: { foo: 1, bar: [1, 2, 3] },
      },
    };
    const parsed = JSON.parse(
      JSON.stringify(original),
    ) as HTTPRequestNodeConfig;
    expect(parsed.config.body).toEqual({ foo: 1, bar: [1, 2, 3] });
  });

  it("Switch node round-trips with case array", () => {
    const original: SwitchNodeConfig = {
      id: "sw1",
      name: "Route",
      type: "switchNode",
      config: {
        expression: "x.kind",
        cases: [
          { value: 1, branch: "one" },
          { value: 2, branch: "two" },
          { value: "default", branch: "fallback" },
        ],
      },
    };
    const parsed = JSON.parse(JSON.stringify(original)) as SwitchNodeConfig;
    expect(parsed.config.cases).toHaveLength(3);
    expect(parsed.config.cases[0]?.value).toBe(1);
  });

  it("Round-trip of every NodeKind preserves the discriminator", () => {
    // Construct a minimal valid instance for every kind. We only need
    // the type field to round-trip — config can be empty for this check.
    for (const kind of ALL_NODE_KINDS) {
      const minimal = {
        id: `id-${kind}`,
        name: `name-${kind}`,
        type: kind,
        config: {} as Record<string, unknown>,
      };
      const parsed = JSON.parse(JSON.stringify(minimal)) as {
        type: NodeKind;
        id: string;
      };
      expect(parsed.type).toBe(kind);
      expect(parsed.id).toBe(`id-${kind}`);
    }
  });
});
