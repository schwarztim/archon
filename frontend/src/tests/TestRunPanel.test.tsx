/**
 * TestRunPanel — live streaming unit tests
 *
 * Strategy:
 * - Mock `runAgent` to resolve with a synthetic runId.
 * - Mock `connectExecutionWebSocket` to capture the onEvent callback, then
 *   fire synthetic events synchronously via `fireEvent` helper.
 * - Mock `cancelExecution` for the cancel button test.
 * - Assert DOM reflects the correct step-timeline state.
 */
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TestRunPanel } from "@/components/builder/TestRunPanel";
import type { ExecutionEvent } from "@/api/executions";

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock("@/api/agents", () => ({
  runAgent: vi.fn(),
}));

vi.mock("@/api/executions", () => ({
  connectExecutionWebSocket: vi.fn(),
  cancelExecution: vi.fn(),
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { runAgent } from "@/api/agents";
import { connectExecutionWebSocket, cancelExecution } from "@/api/executions";

// ── Helpers ───────────────────────────────────────────────────────────────────

const AGENT_ID = "agent-123";
const RUN_ID = "run-abc";

/** Returns the onEvent callback captured by the mock WS, or throws. */
function capturedOnEvent(): (event: ExecutionEvent) => void {
  const mock = connectExecutionWebSocket as Mock;
  const lastCall = mock.mock.calls[mock.mock.calls.length - 1] as [
    string,
    (event: ExecutionEvent) => void,
    (() => void) | undefined,
    ((err: Event) => void) | undefined,
  ];
  if (!lastCall) throw new Error("connectExecutionWebSocket was not called");
  return lastCall[1];
}

function makeEvent(
  type: ExecutionEvent["type"],
  payload: Record<string, unknown> = {},
  extras: Partial<ExecutionEvent> = {},
): ExecutionEvent {
  return {
    id: `evt-${type}`,
    type,
    timestamp: new Date().toISOString(),
    payload,
    ...extras,
  };
}

function renderPanel(agentId: string | null = AGENT_ID) {
  return render(
    <TestRunPanel agentId={agentId} open={true} onClose={vi.fn()} />,
  );
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();

  (runAgent as Mock).mockResolvedValue({ data: { runId: RUN_ID } });

  // Default: WS mock returns a close function, captures callbacks
  (connectExecutionWebSocket as Mock).mockReturnValue(vi.fn());
  (cancelExecution as Mock).mockResolvedValue({ data: {} });
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("TestRunPanel — initial render", () => {
  it("renders the Run Test button", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /run test/i })).toBeInTheDocument();
  });

  it("shows save-first message when agentId is null", () => {
    renderPanel(null);
    expect(screen.getByText(/save the agent/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run test/i })).toBeDisabled();
  });

  it("step timeline is not visible on initial render", () => {
    renderPanel();
    expect(screen.queryByText(/live execution/i)).not.toBeInTheDocument();
  });
});

describe("TestRunPanel — run flow", () => {
  it("calls runAgent and then connectExecutionWebSocket after clicking Run", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));

    expect(runAgent).toHaveBeenCalledWith(AGENT_ID, {});
    expect(connectExecutionWebSocket).toHaveBeenCalledWith(
      RUN_ID,
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });

  it("shows run ID after run starts", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));

    expect(screen.getByText(RUN_ID)).toBeInTheDocument();
  });

  it("renders step-started event in timeline", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));
    const onEvent = capturedOnEvent();

    act(() => {
      onEvent(
        makeEvent("step.started", {
          step_id: "step-1",
          node_name: "LLM Node",
          node_type: "llm",
        }),
      );
    });

    expect(screen.getByText(/live execution/i)).toBeInTheDocument();
    expect(screen.getByText("LLM Node")).toBeInTheDocument();
    // The step status span should show "running"; use getAllByText to allow
    // the button also showing "Running…" at the same time.
    const runningMatches = screen.getAllByText(/running/i);
    expect(runningMatches.length).toBeGreaterThanOrEqual(1);
  });

  it("transitions step to completed when step.completed fires", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));
    const onEvent = capturedOnEvent();

    act(() => {
      onEvent(
        makeEvent("step.started", { step_id: "step-1", node_name: "LLM Node" }),
      );
    });
    act(() => {
      onEvent(
        makeEvent("step.completed", {
          step_id: "step-1",
          node_name: "LLM Node",
          output: { result: "hello" },
        }),
      );
    });

    // Status should now show "completed"
    expect(screen.getByText(/completed/i)).toBeInTheDocument();
    // Output JSON should be rendered
    expect(screen.getByText(/"result": "hello"/)).toBeInTheDocument();
  });

  it("marks step as failed when step.failed fires", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));
    const onEvent = capturedOnEvent();

    act(() => {
      onEvent(
        makeEvent("step.started", { step_id: "step-1", node_name: "HTTP Node" }),
      );
    });
    act(() => {
      onEvent(
        makeEvent("step.failed", {
          step_id: "step-1",
          node_name: "HTTP Node",
          error: "timeout",
        }),
      );
    });

    expect(screen.getByText(/failed/i)).toBeInTheDocument();
    expect(screen.getByText("timeout")).toBeInTheDocument();
  });

  it("renders multiple steps in order", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));
    const onEvent = capturedOnEvent();

    act(() => {
      onEvent(makeEvent("step.started", { step_id: "s1", node_name: "Input" }));
      onEvent(makeEvent("step.started", { step_id: "s2", node_name: "LLM" }));
      onEvent(makeEvent("step.started", { step_id: "s3", node_name: "Output" }));
    });

    // All three step names are present
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("LLM")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
    // Order: Input appears before LLM, LLM before Output
    const allText = document.body.textContent ?? "";
    expect(allText.indexOf("Input")).toBeLessThan(allText.indexOf("LLM"));
    expect(allText.indexOf("LLM")).toBeLessThan(allText.indexOf("Output"));
  });

  it("shows token/cost summary on execution.completed", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));
    const onEvent = capturedOnEvent();

    act(() => {
      onEvent(
        makeEvent(
          "execution.completed",
          { total_tokens: 42 },
          { cost: 0.000123 },
        ),
      );
    });

    expect(screen.getByText(/tokens/i)).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/cost/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.000123/)).toBeInTheDocument();
  });

  it("shows error message on execution.failed", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));
    const onEvent = capturedOnEvent();

    act(() => {
      onEvent(
        makeEvent("execution.failed", { error: "Out of memory" }),
      );
    });

    expect(screen.getByText("Out of memory")).toBeInTheDocument();
  });

  it("shows error for invalid JSON input", async () => {
    const user = userEvent.setup();
    const { container } = renderPanel();

    // Use fireEvent.change — userEvent.type interprets { as a key modifier descriptor
    const textarea = container.querySelector("textarea")!;
    fireEvent.change(textarea, { target: { value: "not valid json @@@@" } });

    await user.click(screen.getByRole("button", { name: /run test/i }));

    expect(screen.getByText(/invalid json/i)).toBeInTheDocument();
    expect(runAgent).not.toHaveBeenCalled();
  });
});

describe("TestRunPanel — cancel", () => {
  it("shows cancel button while running and calls cancelExecution", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /run test/i }));

    const cancelBtn = screen.getByRole("button", { name: /cancel/i });
    expect(cancelBtn).toBeInTheDocument();

    await user.click(cancelBtn);

    expect(cancelExecution).toHaveBeenCalledWith(RUN_ID);
    expect(screen.getByText(/cancelled by user/i)).toBeInTheDocument();
  });
});
