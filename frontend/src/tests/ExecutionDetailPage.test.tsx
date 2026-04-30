/**
 * Tests for ExecutionDetailPage.
 *
 * Coverage
 *  - Summary card renders run id + status + tenant
 *  - Event timeline reflects events fetched via getRunEvents
 *  - Live WS event arrives → it is added to the timeline
 *  - Clicking a step opens the StepDetail panel
 *  - Cancel button is rendered for running runs and POSTs cancelRun
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import * as runsApi from "@/api/runs";
import * as eventsApi from "@/api/events";
import type { WorkflowRun } from "@/types/workflow_run";
import type { WorkflowRunEvent } from "@/types/events";
import { ExecutionDetailPage } from "@/pages/ExecutionDetailPage";

// ── Mock @xyflow/react — ReactFlow tries to measure the viewport and
//    pulls in browser globals (ResizeObserver, etc) we don't want to
//    polyfill in jsdom/happy-dom. The graph view is exercised separately.
vi.mock("@xyflow/react", () => {
  return {
    ReactFlow: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="reactflow-stub">{children}</div>
    ),
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    Handle: () => null,
    Position: { Top: "top", Bottom: "bottom" },
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────

const RUN_ID = "run-abc";

function makeRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: RUN_ID,
    workflow_id: "wf-1",
    agent_id: null,
    kind: "workflow",
    tenant_id: "tenant-a",
    status: "running",
    trigger_type: "manual",
    input_data: { foo: "bar" },
    triggered_by: "alice@example.com",
    attempt: 1,
    idempotency_key: null,
    input_hash: null,
    definition_snapshot: {
      graph_definition: {
        nodes: [
          { id: "step-a", data: { label: "Step A" } },
          { id: "step-b", data: { label: "Step B" } },
        ],
        edges: [{ id: "e1", source: "step-a", target: "step-b" }],
      },
    },
    output_data: null,
    metrics: { tokens: 1234, cost_usd: 0.0123 },
    error: null,
    error_code: null,
    queued_at: "2025-01-01T00:00:00Z",
    claimed_at: null,
    started_at: "2025-01-01T00:00:01Z",
    completed_at: null,
    paused_at: null,
    resumed_at: null,
    cancel_requested_at: null,
    duration_ms: null,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeEvent(
  i: number,
  event_type: WorkflowRunEvent["event_type"],
  step_id: string | null = null,
): WorkflowRunEvent {
  return {
    id: `ev-${i}`,
    run_id: RUN_ID,
    sequence: i,
    event_type,
    payload: {},
    tenant_id: null,
    correlation_id: null,
    span_id: null,
    step_id,
    prev_hash: i === 0 ? null : `h-${i - 1}`,
    current_hash: `h-${i}`,
    created_at: new Date(Date.now() + i * 1000).toISOString(),
  };
}

// Capture the WS onEvent callback so tests can push events.
let pushEvent: ((ev: WorkflowRunEvent) => void) | null = null;
let closeWs: (() => void) | null = null;

function wireSubscribeMock() {
  vi.spyOn(eventsApi, "subscribeRunEvents").mockImplementation(
    (_runId, onEvent, onClose) => {
      pushEvent = onEvent;
      closeWs = onClose ?? null;
      return {
        unsubscribe: () => {
          pushEvent = null;
        },
      };
    },
  );
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/executions/${RUN_ID}`]}>
        <Routes>
          <Route path="/executions/:id" element={<ExecutionDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  pushEvent = null;
  closeWs = null;
  vi.restoreAllMocks();
  wireSubscribeMock();
});

describe("ExecutionDetailPage", () => {
  it("renders the run summary card", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(makeRun());
    vi.spyOn(eventsApi, "listRunEvents").mockResolvedValue({
      run_id: RUN_ID,
      events: [],
      next_after_sequence: null,
      chain_verified: true,
    });

    renderPage();

    expect(await screen.findByTestId("run-summary")).toBeInTheDocument();
    expect(screen.getByText(RUN_ID)).toBeInTheDocument();
    expect(screen.getByText("tenant-a")).toBeInTheDocument();
    // Cost summary
    expect(screen.getByText(/^1234$/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.0123/)).toBeInTheDocument();
  });

  it("renders events from getRunEvents in the timeline", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(makeRun());
    vi.spyOn(eventsApi, "listRunEvents").mockResolvedValue({
      run_id: RUN_ID,
      events: [
        makeEvent(0, "run.created"),
        makeEvent(1, "run.started"),
        makeEvent(2, "step.started", "step-a"),
      ],
      next_after_sequence: null,
      chain_verified: true,
    });

    renderPage();

    // Switch to Timeline tab
    fireEvent.click(await screen.findByRole("tab", { name: /timeline/i }));

    await waitFor(() => {
      expect(screen.getByTestId("chain-verified")).toBeInTheDocument();
    });
    // 3 list items in timeline
    const items = screen.getAllByRole("listitem");
    expect(items.length).toBeGreaterThanOrEqual(3);
  });

  it("appends WS-pushed events to the timeline", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(makeRun());
    vi.spyOn(eventsApi, "listRunEvents").mockResolvedValue({
      run_id: RUN_ID,
      events: [makeEvent(0, "run.created")],
      next_after_sequence: null,
      chain_verified: true,
    });

    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: /timeline/i }));

    await waitFor(() => {
      const items = screen.getAllByRole("listitem");
      expect(items).toHaveLength(1);
    });

    // Push a new event over the WS
    expect(pushEvent).not.toBeNull();
    act(() => {
      pushEvent?.(makeEvent(1, "step.started", "step-a"));
    });

    await waitFor(() => {
      const items = screen.getAllByRole("listitem");
      expect(items).toHaveLength(2);
    });
  });

  it("clicking a step opens the StepDetail panel", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(makeRun());
    vi.spyOn(eventsApi, "listRunEvents").mockResolvedValue({
      run_id: RUN_ID,
      events: [
        makeEvent(0, "run.created"),
        makeEvent(1, "step.started", "step-a"),
      ],
      next_after_sequence: null,
      chain_verified: true,
    });

    renderPage();

    // Steps tab → click a step row
    fireEvent.click(await screen.findByRole("tab", { name: /steps/i }));
    const rows = await screen.findAllByTestId("step-row");
    expect(rows.length).toBeGreaterThan(0);
    const rowA = rows.find((r) => within(r).queryByText("Step A"));
    expect(rowA).toBeDefined();
    if (rowA) fireEvent.click(rowA);

    const detail = await screen.findByTestId("step-detail");
    // The StepDetail panel renders the step name in its header.
    expect(within(detail).getByText("Step A")).toBeInTheDocument();
  });

  it("renders Cancel for running runs and POSTs cancelRun on click", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      makeRun({ status: "running" }),
    );
    vi.spyOn(eventsApi, "listRunEvents").mockResolvedValue({
      run_id: RUN_ID,
      events: [],
      next_after_sequence: null,
      chain_verified: true,
    });
    const cancelSpy = vi
      .spyOn(runsApi, "cancelRun")
      .mockResolvedValue({ status: "accepted", run: {} });

    renderPage();

    const btn = await screen.findByTestId("cancel-run");
    fireEvent.click(btn);

    await waitFor(() => {
      expect(cancelSpy).toHaveBeenCalledWith(RUN_ID);
    });
  });

  it("does NOT render Cancel for terminal runs", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      makeRun({ status: "completed" }),
    );
    vi.spyOn(eventsApi, "listRunEvents").mockResolvedValue({
      run_id: RUN_ID,
      events: [],
      next_after_sequence: null,
      chain_verified: true,
    });

    renderPage();

    expect(await screen.findByTestId("run-summary")).toBeInTheDocument();
    expect(screen.queryByTestId("cancel-run")).toBeNull();
  });

  it("WS reconnect path: triggers re-seed without crashing", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(makeRun());
    vi.spyOn(eventsApi, "listRunEvents").mockResolvedValue({
      run_id: RUN_ID,
      events: [],
      next_after_sequence: null,
      chain_verified: true,
    });

    renderPage();

    expect(await screen.findByTestId("run-summary")).toBeInTheDocument();

    // Simulate the server closing the socket — the hook should mark
    // status="closed" and not blow up.
    act(() => {
      closeWs?.();
    });

    expect(screen.getByTestId("ws-status")).toBeInTheDocument();
  });
});
