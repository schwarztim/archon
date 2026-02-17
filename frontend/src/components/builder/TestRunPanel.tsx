import { useState, useCallback } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import { runAgent } from "@/api/agents";

interface TestRunPanelProps {
  agentId: string | null;
  open: boolean;
  onClose: () => void;
}

interface TestRunResult {
  status: "idle" | "running" | "success" | "error";
  output?: string;
  error?: string;
  runId?: string;
  steps?: Array<{ node: string; status: string; output?: string }>;
}

/** Side panel for executing test runs against the agent graph */
export function TestRunPanel({ agentId, open, onClose }: TestRunPanelProps) {
  const [input, setInput] = useState("{}");
  const [result, setResult] = useState<TestRunResult>({ status: "idle" });

  const handleRun = useCallback(async () => {
    if (!agentId) return;
    setResult({ status: "running" });

    try {
      let parsedInput: Record<string, unknown> = {};
      try {
        parsedInput = JSON.parse(input) as Record<string, unknown>;
      } catch {
        setResult({ status: "error", error: "Invalid JSON input." });
        return;
      }

      const response = await runAgent(agentId, parsedInput);
      setResult({
        status: "success",
        runId: response.data.runId,
        output: JSON.stringify(response.data, null, 2),
      });
    } catch (err) {
      setResult({
        status: "error",
        error: err instanceof Error ? err.message : "Execution failed.",
      });
    }
  }, [agentId, input]);

  if (!open) return null;

  return (
    <aside
      className="flex h-full w-80 flex-col border-l border-border bg-card"
      aria-label="Test run panel"
    >
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
          />
        </div>

        {/* Run button */}
        <Button
          className="w-full"
          onClick={() => void handleRun()}
          disabled={!agentId || result.status === "running"}
          aria-label="Execute test run"
        >
          {result.status === "running" ? "Running…" : "▶ Run Test"}
        </Button>

        {/* Results */}
        {result.status === "success" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              <span className="text-xs font-medium text-green-600 dark:text-green-400">
                Success
              </span>
              {result.runId && (
                <span className="text-xs text-muted-foreground">
                  Run: {result.runId}
                </span>
              )}
            </div>
            <pre className="max-h-60 overflow-auto rounded-md bg-muted p-3 text-xs font-mono">
              {result.output}
            </pre>
          </div>
        )}

        {result.status === "error" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-destructive" />
              <span className="text-xs font-medium text-destructive">Error</span>
            </div>
            <pre className="max-h-60 overflow-auto rounded-md bg-destructive/10 p-3 text-xs font-mono text-destructive">
              {result.error}
            </pre>
          </div>
        )}

        {/* Step-by-step results (when available via WebSocket) */}
        {result.steps && result.steps.length > 0 && (
          <div className="space-y-1">
            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Execution Steps
            </h3>
            {result.steps.map((step, i) => (
              <div
                key={i}
                className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-xs"
              >
                <span
                  className={`inline-block h-1.5 w-1.5 rounded-full ${
                    step.status === "success"
                      ? "bg-green-500"
                      : step.status === "error"
                        ? "bg-destructive"
                        : "bg-amber-500"
                  }`}
                />
                <span className="font-medium">{step.node}</span>
                {step.output && (
                  <span className="truncate text-muted-foreground">
                    {step.output}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
