/**
 * Contract test: api/runs.ts honors the canonical run API shape.
 *
 * Phase 3, WS15. Verifies request/response wiring for:
 *   - startRun       (POST /api/v1/executions)
 *   - getRun         (GET  /api/v1/workflow-runs/{id})
 *   - cancelRun      (POST /api/v1/executions/{id}/cancel)
 *   - listRuns       (GET  /api/v1/workflow-runs)
 *
 * Uses a mock fetch to capture the wire format. We're checking the
 * request body keys, the X-Idempotency-Key header (ADR-004), and the
 * canonical WorkflowRun shape returned to callers.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  cancelRun,
  getRun,
  listRuns,
  startRun,
} from "@/api/runs";
import type { WorkflowRun, WorkflowRunSummary } from "@/types/workflow_run";

// ── Test fixture builders ─────────────────────────────────────────────

function makeRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    workflow_id: null,
    agent_id: "22222222-2222-2222-2222-222222222222",
    kind: "agent",
    tenant_id: null,
    status: "pending",
    trigger_type: "manual",
    input_data: { x: 1 },
    triggered_by: "test@example.com",
    attempt: 0,
    idempotency_key: null,
    input_hash: null,
    definition_snapshot: { nodes: [], edges: [] },
    output_data: null,
    metrics: null,
    error: null,
    error_code: null,
    queued_at: null,
    claimed_at: null,
    started_at: null,
    completed_at: null,
    paused_at: null,
    resumed_at: null,
    cancel_requested_at: null,
    duration_ms: null,
    created_at: "2026-04-29T00:00:00Z",
    ...overrides,
  };
}

function makeSummary(
  overrides: Partial<WorkflowRunSummary> = {},
): WorkflowRunSummary {
  return {
    id: "33333333-3333-3333-3333-333333333333",
    kind: "workflow",
    workflow_id: "44444444-4444-4444-4444-444444444444",
    agent_id: null,
    tenant_id: null,
    status: "completed",
    trigger_type: "manual",
    triggered_by: "ci@example.com",
    queued_at: "2026-04-29T00:00:00Z",
    started_at: "2026-04-29T00:00:01Z",
    completed_at: "2026-04-29T00:00:05Z",
    duration_ms: 4000,
    error_code: null,
    created_at: "2026-04-29T00:00:00Z",
    ...overrides,
  };
}

interface MockResponse {
  status: number;
  body: unknown;
}

function buildResponse(mock: MockResponse): Response {
  const init: ResponseInit = { status: mock.status };
  return new Response(JSON.stringify(mock.body), init);
}

// ── Setup ─────────────────────────────────────────────────────────────

let fetchCalls: Array<{ url: string; init: RequestInit }>;

function setMockResponse(mock: MockResponse): void {
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    fetchCalls.push({
      url: typeof url === "string" ? url : url.toString(),
      init: init ?? {},
    });
    return buildResponse(mock);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  fetchCalls = [];
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── startRun ──────────────────────────────────────────────────────────

describe("startRun", () => {
  it("POSTs to /api/v1/executions with the expected body keys and types", async () => {
    setMockResponse({ status: 201, body: { data: makeRun() } });

    await startRun({
      agent_id: "22222222-2222-2222-2222-222222222222",
      input_data: { foo: "bar" },
    });

    expect(fetchCalls).toHaveLength(1);
    const call = fetchCalls[0]!;
    expect(call.url).toBe("/api/v1/executions");
    expect(call.init.method).toBe("POST");

    const body = JSON.parse(call.init.body as string);
    expect(body).toHaveProperty("agent_id");
    expect(body).toHaveProperty("input_data");
    expect(typeof body.agent_id).toBe("string");
    expect(typeof body.input_data).toBe("object");
  });

  it("includes X-Idempotency-Key header when idempotency_key is supplied", async () => {
    setMockResponse({ status: 201, body: { data: makeRun() } });

    await startRun({
      workflow_id: "55555555-5555-5555-5555-555555555555",
      input_data: {},
      idempotency_key: "key-abc-123",
    });

    const headers = fetchCalls[0]!.init.headers as Record<string, string>;
    expect(headers["X-Idempotency-Key"]).toBe("key-abc-123");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("omits X-Idempotency-Key header when idempotency_key is absent", async () => {
    setMockResponse({ status: 201, body: { data: makeRun() } });

    await startRun({
      workflow_id: "55555555-5555-5555-5555-555555555555",
      input_data: {},
    });

    const headers = fetchCalls[0]!.init.headers as Record<string, string>;
    expect(headers["X-Idempotency-Key"]).toBeUndefined();
  });

  it("rejects calls with both workflow_id and agent_id", async () => {
    await expect(
      startRun({
        workflow_id: "a",
        agent_id: "b",
        input_data: {},
      }),
    ).rejects.toThrow(/mutually exclusive/);
  });

  it("rejects calls with neither workflow_id nor agent_id", async () => {
    await expect(startRun({ input_data: {} })).rejects.toThrow(
      /workflow_id or agent_id is required/,
    );
  });

  it("returns canonical run shape with run_id, status, run, is_new", async () => {
    const run = makeRun({ status: "pending" });
    setMockResponse({ status: 201, body: { data: run } });

    const result = await startRun({
      agent_id: "22222222-2222-2222-2222-222222222222",
      input_data: {},
    });

    expect(result.run_id).toBe(run.id);
    expect(result.status).toBe("pending");
    expect(result.is_new).toBe(true);
    expect(result.run.kind).toBe("agent");
  });

  it("treats 200 as idempotency-hit (is_new=false)", async () => {
    const run = makeRun({ status: "running" });
    setMockResponse({ status: 200, body: { data: run } });

    const result = await startRun({
      agent_id: "22222222-2222-2222-2222-222222222222",
      input_data: {},
      idempotency_key: "k",
    });

    expect(result.is_new).toBe(false);
    expect(result.status).toBe("running");
  });

  it("throws structured error on 409 idempotency conflict", async () => {
    setMockResponse({
      status: 409,
      body: {
        error: {
          code: "idempotency_conflict",
          message: "key reused with different input",
          key: "k",
          existing_run_id: "00000000-0000-0000-0000-000000000000",
        },
      },
    });

    await expect(
      startRun({
        agent_id: "22222222-2222-2222-2222-222222222222",
        input_data: { x: 1 },
        idempotency_key: "k",
      }),
    ).rejects.toMatchObject({ code: "idempotency_conflict" });
  });
});

// ── getRun ────────────────────────────────────────────────────────────

describe("getRun", () => {
  it("GETs /api/v1/workflow-runs/{id} when canonical=true (default)", async () => {
    const run = makeRun();
    setMockResponse({ status: 200, body: { data: run } });

    const got = await getRun(run.id);

    expect(fetchCalls[0]!.url).toBe(`/api/v1/workflow-runs/${run.id}`);
    expect(fetchCalls[0]!.init.method).toBe("GET");
    expect(got.id).toBe(run.id);
    expect(got.kind).toBe("agent");
  });

  it("GETs /api/v1/executions/{id}?canonical=true when canonical=false", async () => {
    // The frontend uses ``?canonical=true`` so the response shape stays
    // canonical regardless of which alias the caller chooses.
    const run = makeRun();
    setMockResponse({ status: 200, body: { data: run } });

    await getRun(run.id, { canonical: false });

    expect(fetchCalls[0]!.url).toBe(
      `/api/v1/executions/${run.id}?canonical=true`,
    );
  });

  it("tolerates raw shape (no envelope) and returns the run", async () => {
    const run = makeRun({ status: "completed" });
    setMockResponse({ status: 200, body: run });

    const got = await getRun(run.id);
    expect(got.status).toBe("completed");
  });

  it("throws on non-2xx", async () => {
    setMockResponse({
      status: 404,
      body: { errors: [{ code: "NOT_FOUND", message: "missing" }] },
    });
    await expect(getRun("nope")).rejects.toBeDefined();
  });
});

// ── cancelRun ─────────────────────────────────────────────────────────

describe("cancelRun", () => {
  it("POSTs /api/v1/executions/{id}/cancel and returns shape {status: accepted, run}", async () => {
    const run = makeRun({ status: "cancelled" });
    setMockResponse({ status: 202, body: { data: run, meta: { request_id: "r", timestamp: "t" } } });

    const result = await cancelRun(run.id);

    expect(fetchCalls[0]!.url).toBe(`/api/v1/executions/${run.id}/cancel`);
    expect(fetchCalls[0]!.init.method).toBe("POST");
    expect(result.status).toBe("accepted");
    expect((result.run as WorkflowRun).id).toBe(run.id);
  });

  it("rejects with parsed error on 409 (already terminal)", async () => {
    setMockResponse({
      status: 409,
      body: { errors: [{ code: "CONFLICT", message: "already completed" }] },
    });

    await expect(
      cancelRun("11111111-1111-1111-1111-111111111111"),
    ).rejects.toBeDefined();
  });
});

// ── listRuns ──────────────────────────────────────────────────────────

describe("listRuns", () => {
  it("GETs /api/v1/workflow-runs with no params when opts is empty", async () => {
    setMockResponse({
      status: 200,
      body: { items: [], next_cursor: null },
    });

    const result = await listRuns();
    expect(fetchCalls[0]!.url).toBe("/api/v1/workflow-runs");
    expect(result.items).toEqual([]);
    expect(result.next_cursor).toBeNull();
  });

  it("honors status / kind / cursor / limit query params", async () => {
    setMockResponse({
      status: 200,
      body: { items: [], next_cursor: null },
    });

    await listRuns({
      status: "running",
      kind: "workflow",
      cursor: "2026-04-29T00:00:00Z",
      limit: 25,
    });

    const url = new URL(`http://x${fetchCalls[0]!.url}`);
    expect(url.pathname).toBe("/api/v1/workflow-runs");
    expect(url.searchParams.get("status")).toBe("running");
    expect(url.searchParams.get("kind")).toBe("workflow");
    expect(url.searchParams.get("cursor")).toBe("2026-04-29T00:00:00Z");
    expect(url.searchParams.get("limit")).toBe("25");
  });

  it("returns a list of run summaries with the expected shape", async () => {
    const summary = makeSummary();
    setMockResponse({
      status: 200,
      body: { items: [summary], next_cursor: "2026-04-28T00:00:00Z" },
    });

    const result = await listRuns({ limit: 10 });
    expect(result.items).toHaveLength(1);
    expect(result.items[0]!.id).toBe(summary.id);
    expect(result.items[0]!.status).toBe("completed");
    expect(result.next_cursor).toBe("2026-04-28T00:00:00Z");
  });

  it("filters out undefined / null query values", async () => {
    setMockResponse({
      status: 200,
      body: { items: [], next_cursor: null },
    });

    await listRuns({ status: "running", limit: undefined });

    const url = new URL(`http://x${fetchCalls[0]!.url}`);
    expect(url.searchParams.get("status")).toBe("running");
    expect(url.searchParams.has("limit")).toBe(false);
  });
});
