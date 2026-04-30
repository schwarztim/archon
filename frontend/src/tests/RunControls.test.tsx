import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RunControls } from "@/components/executions/RunControls";
import type { RunStatus, WorkflowRun } from "@/types/workflow_run";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/api/runs", () => ({
  cancelRun: vi.fn(),
  startRun: vi.fn(),
}));

vi.mock("@/api/approvals", () => ({
  resumeRun: vi.fn(),
}));

vi.mock("@/api/signals", () => ({
  sendSignal: vi.fn(),
}));

import { cancelRun, startRun } from "@/api/runs";
import { resumeRun } from "@/api/approvals";

// ─── Fixtures ─────────────────────────────────────────────────────────

function makeRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  const base: WorkflowRun = {
    id: "run-1",
    workflow_id: "wf-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    agent_id: null,
    kind: "workflow",
    tenant_id: "00000000-0000-0000-0000-000000000001",
    status: "running",
    trigger_type: "manual",
    input_data: { prompt: "hi" },
    triggered_by: "tester@example.com",
    attempt: 1,
    idempotency_key: null,
    input_hash: null,
    definition_snapshot: { nodes: [], edges: [] },
    output_data: null,
    metrics: null,
    error: null,
    error_code: null,
    queued_at: null,
    claimed_at: null,
    started_at: "2025-01-01T10:00:00Z",
    completed_at: null,
    paused_at: null,
    resumed_at: null,
    cancel_requested_at: null,
    duration_ms: null,
    created_at: "2025-01-01T10:00:00Z",
  };
  return { ...base, ...overrides };
}

function renderControls(status: RunStatus, isAdmin = false) {
  const run = makeRun({ status });
  const onChanged = vi.fn();
  const onReplayed = vi.fn();
  const utils = render(
    <RunControls
      run={run}
      isAdmin={isAdmin}
      onChanged={onChanged}
      onReplayed={onReplayed}
    />,
  );
  return { ...utils, run, onChanged, onReplayed };
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("RunControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows only Cancel (and Pause placeholder) when running", () => {
    renderControls("running");
    expect(screen.getByTestId("btn-cancel")).toBeInTheDocument();
    expect(screen.getByTestId("btn-pause-placeholder")).toBeDisabled();
    expect(screen.queryByTestId("btn-resume")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-retry")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-replay")).not.toBeInTheDocument();
  });

  it("shows Resume and Cancel when paused", () => {
    renderControls("paused");
    expect(screen.getByTestId("btn-resume")).toBeInTheDocument();
    expect(screen.getByTestId("btn-cancel")).toBeInTheDocument();
    expect(screen.queryByTestId("btn-retry")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-replay")).not.toBeInTheDocument();
  });

  it("shows Retry when failed", () => {
    renderControls("failed");
    expect(screen.getByTestId("btn-retry")).toBeInTheDocument();
    expect(screen.queryByTestId("btn-cancel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-resume")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-replay")).not.toBeInTheDocument();
  });

  it("shows Replay when completed", () => {
    renderControls("completed");
    expect(screen.getByTestId("btn-replay")).toBeInTheDocument();
    expect(screen.queryByTestId("btn-cancel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-resume")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-retry")).not.toBeInTheDocument();
  });

  it("never shows Send Signal for non-admin callers", () => {
    renderControls("running", false);
    expect(screen.queryByTestId("btn-send-signal")).not.toBeInTheDocument();
  });

  it("shows Send Signal for admin callers", () => {
    renderControls("running", true);
    expect(screen.getByTestId("btn-send-signal")).toBeInTheDocument();
  });

  it("calls cancelRun when Cancel is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(cancelRun).mockResolvedValueOnce({
      status: "accepted",
      run: makeRun({ status: "cancelled" }),
    });

    const { onChanged } = renderControls("running");

    await act(async () => {
      await user.click(screen.getByTestId("btn-cancel"));
    });

    await waitFor(() => {
      expect(cancelRun).toHaveBeenCalledWith("run-1");
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("calls resumeRun when Resume is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(resumeRun).mockResolvedValueOnce({
      run_id: "run-1",
      status: "running",
      pending_signal_count: 0,
      pending_signal_types: [],
    });

    const { onChanged } = renderControls("paused");

    await act(async () => {
      await user.click(screen.getByTestId("btn-resume"));
    });

    await waitFor(() => {
      expect(resumeRun).toHaveBeenCalledWith("run-1");
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("dispatches a fresh run with idempotency key when Retry is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(startRun).mockResolvedValueOnce({
      run_id: "run-2",
      status: "pending",
      run: makeRun({ id: "run-2", status: "pending" }),
      is_new: true,
    });

    const { onReplayed } = renderControls("failed");

    await act(async () => {
      await user.click(screen.getByTestId("btn-retry"));
    });

    await waitFor(() => {
      expect(startRun).toHaveBeenCalledTimes(1);
    });

    const args = vi.mocked(startRun).mock.calls[0]?.[0];
    expect(args?.workflow_id).toBe("wf-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    expect(args?.input_data).toEqual({ prompt: "hi" });
    expect(args?.idempotency_key).toMatch(/^retry-/);

    await waitFor(() => {
      expect(onReplayed).toHaveBeenCalled();
    });
  });
});
