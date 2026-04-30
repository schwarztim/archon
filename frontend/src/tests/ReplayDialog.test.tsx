import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReplayDialog } from "@/components/executions/ReplayDialog";
import type { WorkflowRun } from "@/types/workflow_run";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/api/runs", () => ({
  startRun: vi.fn(),
}));

import { startRun } from "@/api/runs";

// ─── Fixtures ─────────────────────────────────────────────────────────

function makeRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: "run-1",
    workflow_id: "wf-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    agent_id: null,
    kind: "workflow",
    tenant_id: "00000000-0000-0000-0000-000000000001",
    status: "completed",
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
    completed_at: "2025-01-01T10:01:00Z",
    paused_at: null,
    resumed_at: null,
    cancel_requested_at: null,
    duration_ms: 60000,
    created_at: "2025-01-01T10:00:00Z",
    ...overrides,
  };
}

function renderDialog(run: WorkflowRun = makeRun()) {
  const onClose = vi.fn();
  const onReplayed = vi.fn();
  const utils = render(
    <ReplayDialog run={run} onClose={onClose} onReplayed={onReplayed} />,
  );
  return { ...utils, onClose, onReplayed };
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("ReplayDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the three replay mode options", () => {
    renderDialog();
    expect(screen.getByText(/replay from beginning/i)).toBeInTheDocument();
    expect(screen.getByText(/replay from step/i)).toBeInTheDocument();
    expect(screen.getByText(/replay with overrides/i)).toBeInTheDocument();
  });

  it("disables 'from step' with an explanatory tooltip and hint", () => {
    renderDialog();
    const fromStepRadio = screen.getByRole("radio", {
      name: /replay from step/i,
    });
    expect(fromStepRadio).toBeDisabled();
    expect(
      screen.getByText(/coming soon — backend support pending/i),
    ).toBeInTheDocument();
  });

  it("submits a fresh run with original inputs in 'from beginning' mode", async () => {
    const user = userEvent.setup();
    vi.mocked(startRun).mockResolvedValueOnce({
      run_id: "run-2",
      status: "pending",
      run: makeRun({ id: "run-2", status: "pending" }),
      is_new: true,
    });

    const { onReplayed, onClose } = renderDialog();

    await act(async () => {
      await user.click(screen.getByTestId("btn-replay-submit"));
    });

    await waitFor(() => {
      expect(startRun).toHaveBeenCalledTimes(1);
    });

    const args = vi.mocked(startRun).mock.calls[0]?.[0];
    expect(args?.workflow_id).toBe("wf-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    expect(args?.input_data).toEqual({ prompt: "hi" });
    expect(args?.idempotency_key).toMatch(/^replay-/);

    expect(onReplayed).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("submits with overrides parsed from the textarea", async () => {
    const user = userEvent.setup();
    vi.mocked(startRun).mockResolvedValueOnce({
      run_id: "run-3",
      status: "pending",
      run: makeRun({ id: "run-3", status: "pending" }),
      is_new: true,
    });

    renderDialog();

    await act(async () => {
      await user.click(
        screen.getByRole("radio", { name: /replay with overrides/i }),
      );
    });

    const textarea = await screen.findByLabelText(/input data \(json\)/i);
    // userEvent.type interprets {/} as keystroke modifiers — for raw JSON
    // we use fireEvent.change to bypass the parser entirely.
    await act(async () => {
      fireEvent.change(textarea, { target: { value: '{"prompt":"override"}' } });
      await user.click(screen.getByTestId("btn-replay-submit"));
    });

    await waitFor(() => {
      expect(startRun).toHaveBeenCalled();
    });
    const args = vi.mocked(startRun).mock.calls[0]?.[0];
    expect(args?.input_data).toEqual({ prompt: "override" });
  });

  it("shows an error for invalid JSON in overrides mode", async () => {
    const user = userEvent.setup();
    renderDialog();

    await act(async () => {
      await user.click(
        screen.getByRole("radio", { name: /replay with overrides/i }),
      );
    });

    const textarea = await screen.findByLabelText(/input data \(json\)/i);
    await act(async () => {
      await user.clear(textarea);
      await user.type(textarea, "not-json");
      await user.click(screen.getByTestId("btn-replay-submit"));
    });

    expect(await screen.findByText(/invalid json input/i)).toBeInTheDocument();
    expect(startRun).not.toHaveBeenCalled();
  });
});
