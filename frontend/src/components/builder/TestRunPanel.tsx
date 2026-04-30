import { useState, useCallback, useEffect, useRef } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import { runAgent } from "@/api/agents";
import { cancelExecution, connectExecutionWebSocket } from "@/api/executions";
import type { ExecutionEvent } from "@/api/executions";

// ── Types ────────────────────────────────────────────────────────────────────

export type StepStatus = "running" | "completed" | "failed";

export interface StepEvent {
  stepId: string;
  nodeType?: string;
  nodeName?: string;
  status: StepStatus;
  output?: unknown;
  error?: string;
  durationMs?: number;
}

interface CompletionSummary {
  totalTokens?: number;
  costUsd?: number;
}

type RunStatus = "idle" | "running" | "completed" | "failed";

interface TestRunPanelProps {
  agentId: string | null;
  open: boolean;
  onClose: () => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Extract a string step ID from an event payload field, falling back to a default. */
function extractStepId(payload: Record<string, unknown>, fallback: string): string {
  return typeof payload.step_id === "string" ? payload.step_id : fallback;
}

/** Map a raw ExecutionEvent to a StepEvent. Returns null for non-step events. */
function toStepEvent(event: ExecutionEvent, status: StepStatus): StepEvent | null {
  const p = event.payload;
  const rawId = extractStepId(p, event.id);
  return {
    stepId: rawId,
    nodeType: typeof p.node_type === "string" ? p.node_type : undefined,
    nodeName: typeof p.node_name === "string" ? p.node_name : undefined,
    status,
    output: status !== "running" ? p.output : undefined,
    error: typeof p.error === "string" ? p.error : undefined,
    durationMs: typeof p.duration_ms === "number" ? p.duration_ms : undefined,
  };
}

// ── Component ────────────────────────────────────────────────────────────────

/** Side panel for executing test runs against the agent graph */
export function TestRunPanel({ agentId, open, onClose }: TestRunPanelProps) {
  const [input, setInput] = useState("{}");
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [summary, setSummary] = useState<CompletionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

  // Keep a ref to the WS close function so we can cancel
  const wsCloseRef = useRef<(() => void) | null>(null);

  // Clean up WS on unmount
  useEffect(() => {
    return () => {
      wsCloseRef.current?.();
    };
  }, []);

  const handleRun = useCallback(async () => {
    if (!agentId) return;

    // Reset state
    setRunStatus("running");
    setSteps([]);
    setSummary(null);
    setError(null);
    setRunId(null);
    wsCloseRef.current?.();
    wsCloseRef.current = null;

    let parsedInput: Record<string, unknown> = {};
    try {
      parsedInput = JSON.parse(input) as Record<string, unknown>;
    } catch {
      setRunStatus("failed");
      setError("Invalid JSON input.");
      return;
    }

    let executionId: string;
    try {
      const response = await runAgent(agentId, parsedInput);
      executionId = response.data.runId;
      setRunId(executionId);
    } catch (err) {
      setRunStatus("failed");
      setError(err instanceof Error ? err.message : "Execution failed to start.");
      return;
    }

    // Connect WebSocket for live streaming
    const closeWs = connectExecutionWebSocket(
      executionId,
      (event: ExecutionEvent) => {
        switch (event.type) {
          case "step.started": {
            const step = toStepEvent(event, "running");
            if (step) {
              setSteps((s) => [...s, step]);
            }
            break;
          }
          case "step.completed": {
            const step = toStepEvent(event, "completed");
            if (step) {
              setSteps((s) =>
                s.map((existing) =>
                  existing.stepId === step.stepId
                    ? { ...existing, ...step }
                    : existing,
                ),
              );
            }
            break;
          }
          case "step.failed": {
            const step = toStepEvent(event, "failed");
            if (step) {
              setSteps((s) =>
                s.map((existing) =>
                  existing.stepId === step.stepId
                    ? { ...existing, ...step }
                    : existing,
                ),
              );
            }
            break;
          }
          case "execution.completed": {
            const p = event.payload;
            const totalTokens =
              typeof p.total_tokens === "number" ? p.total_tokens : undefined;
            const costUsd =
              typeof event.cost === "number"
                ? event.cost
                : typeof p.total_cost_usd === "number"
                  ? p.total_cost_usd
                  : undefined;
            setSummary({ totalTokens, costUsd });
            setRunStatus("completed");
            wsCloseRef.current?.();
            wsCloseRef.current = null;
            break;
          }
          case "execution.failed": {
            const msg = typeof event.payload.error === "string"
              ? event.payload.error
              : "Execution failed.";
            setError(msg);
            setRunStatus("failed");
            wsCloseRef.current?.();
            wsCloseRef.current = null;
            break;
          }
          case "agent_complete": {
            // Backend native event equivalent of execution.completed
            const p = event.payload;
            const totalTokens =
              typeof p.total_tokens === "number" ? p.total_tokens : undefined;
            const costUsd =
              typeof event.cost === "number" ? event.cost : undefined;
            setSummary({ totalTokens, costUsd });
            setRunStatus("completed");
            break;
          }
          default:
            break;
        }
      },
      () => {
        // WS closed — if still running, mark completed (backend closed cleanly)
        setRunStatus((prev) => (prev === "running" ? "completed" : prev));
      },
      () => {
        setError("WebSocket connection error.");
        setRunStatus("failed");
      },
    );

    wsCloseRef.current = closeWs;
  }, [agentId, input]);

  const handleCancel = useCallback(async () => {
    if (!runId) return;
    wsCloseRef.current?.();
    wsCloseRef.current = null;
    setRunStatus("failed");
    setError("Cancelled by user.");
    try {
      await cancelExecution(runId);
    } catch {
      // Best-effort cancel; UI already reflects cancellation
    }
  }, [runId]);

  if (!open) return null;

  const isRunning = runStatus === "running";

  return (
    <aside
      className="flex h-full w-80 flex-col border-l border-border bg-card"
      aria-label="Test run panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Test Run</h2>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close test panel">
          ✕
        </Button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {!agentId && (
          <p className="text-sm text-muted-foreground">
            Save the agent before running tests.
          </p>
        )}

        {/* Input */}
        <div className="space-y-1.5">
          <Label htmlFor="test-input">Test Input (JSON)</Label>
          <Textarea
            id="test-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={6}
            className="font-mono text-xs"
            placeholder='{"message": "Hello"}'
            disabled={isRunning}
          />
        </div>

        {/* Run / Cancel buttons */}
        <div className="flex gap-2">
          <Button
            className="flex-1"
            onClick={() => void handleRun()}
            disabled={!agentId || isRunning}
          >
            {isRunning ? "Running…" : "▶ Run Test"}
          </Button>
          {isRunning && runId && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => void handleCancel()}
              aria-label="Cancel execution"
            >
              ✕ Cancel
            </Button>
          )}
        </div>

        {/* Run ID badge */}
        {runId && (
          <p className="text-xs text-muted-foreground">
            Run: <span className="font-mono">{runId}</span>
          </p>
        )}

        {/* Status indicators */}
        {runStatus === "completed" && (
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
            <span className="text-xs font-medium text-green-600 dark:text-green-400">
              Completed
            </span>
          </div>
        )}
        {runStatus === "failed" && error && (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-destructive" />
              <span className="text-xs font-medium text-destructive">Failed</span>
            </div>
            <pre className="max-h-32 overflow-auto rounded-md bg-destructive/10 p-2 text-xs font-mono text-destructive">
              {error}
            </pre>
          </div>
        )}

        {/* Completion summary (tokens + cost) */}
        {summary && (
          <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs space-y-0.5">
            {summary.totalTokens !== undefined && (
              <p>
                <span className="font-medium">Tokens:</span>{" "}
                {summary.totalTokens.toLocaleString()}
              </p>
            )}
            {summary.costUsd !== undefined && (
              <p>
                <span className="font-medium">Cost:</span> $
                {summary.costUsd.toFixed(6)}
              </p>
            )}
          </div>
        )}

        {/* Live execution timeline */}
        {steps.length > 0 && (
          <div className="step-timeline space-y-1">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Live Execution
            </h4>
            {steps.map((step) => (
              <div
                key={step.stepId}
                className={`step-row step-${step.status} flex flex-col gap-0.5 rounded-md border border-border px-2 py-1.5 text-xs`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full ${
                      step.status === "completed"
                        ? "bg-green-500"
                        : step.status === "failed"
                          ? "bg-destructive"
                          : "bg-amber-500 animate-pulse"
                    }`}
                    aria-hidden="true"
                  />
                  <span className="step-name font-medium">
                    {step.nodeName ?? step.nodeType ?? step.stepId}
                  </span>
                  <span className="step-status ml-auto text-muted-foreground capitalize">
                    {step.status}
                  </span>
                </div>
                {step.output !== undefined && (
                  <pre className="step-output mt-1 max-h-24 overflow-auto rounded bg-muted p-1.5 font-mono text-muted-foreground text-[10px]">
                    {JSON.stringify(step.output, null, 2)}
                  </pre>
                )}
                {step.error && (
                  <p className="text-destructive font-mono text-[10px] break-words">
                    {step.error}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
