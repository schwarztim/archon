import { useState } from "react";
import { Loader2, Repeat, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import { startRun } from "@/api/runs";
import type { WorkflowRun } from "@/types/workflow_run";

type ReplayMode = "from_beginning" | "from_step" | "with_overrides";

interface ReplayDialogProps {
  run: WorkflowRun;
  onClose: () => void;
  onReplayed: (newRun: WorkflowRun) => void;
}

/** Feature flag — backend lacks "replay from step" support. Always false today. */
const REPLAY_FROM_STEP_ENABLED = false;

function genIdempotencyKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Replay dialog — drives ``POST /api/v1/executions`` with the run's prior
 * inputs (and optional overrides), creating a new run.
 *
 * Modes:
 *   - from_beginning  → re-dispatch with original input_data
 *   - from_step       → DISABLED until backend support lands
 *   - with_overrides  → edit input_data JSON before re-dispatch
 *
 * Each replay receives a fresh ``idempotency_key`` so the server creates a
 * brand new run instead of returning the original run as an idempotency hit.
 */
export function ReplayDialog({ run, onClose, onReplayed }: ReplayDialogProps) {
  const [mode, setMode] = useState<ReplayMode>("from_beginning");
  const [inputText, setInputText] = useState(
    JSON.stringify(run.input_data ?? {}, null, 2),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (mode === "from_step") {
      setError("Replay from step is not yet supported.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      let inputData: Record<string, unknown> = run.input_data ?? {};
      if (mode === "with_overrides") {
        inputData = JSON.parse(inputText) as Record<string, unknown>;
      }
      const args = run.workflow_id
        ? {
            workflow_id: run.workflow_id,
            input_data: inputData,
            idempotency_key: genIdempotencyKey("replay"),
          }
        : run.agent_id
          ? {
              agent_id: run.agent_id,
              input_data: inputData,
              idempotency_key: genIdempotencyKey("replay"),
            }
          : null;
      if (!args) {
        throw new Error("Run has neither workflow_id nor agent_id");
      }
      const res = await startRun(args);
      onReplayed(res.run);
      onClose();
    } catch (err) {
      setError(
        err instanceof SyntaxError
          ? "Invalid JSON input"
          : err instanceof Error
            ? err.message
            : "Replay failed",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      role="dialog"
      aria-modal="true"
      aria-labelledby="replay-dialog-title"
    >
      <div className="w-full max-w-lg rounded-lg border border-surface-border bg-surface-raised p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2
            id="replay-dialog-title"
            className="text-lg font-semibold text-white"
          >
            Replay run
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <fieldset className="mb-4 space-y-2" role="radiogroup">
          <legend className="mb-1 block text-sm font-medium text-gray-300">
            Mode
          </legend>
          <label className="flex items-start gap-2 rounded border border-surface-border bg-surface-base p-3 text-sm text-gray-200 hover:border-purple-500/50">
            <input
              type="radio"
              name="replay-mode"
              value="from_beginning"
              checked={mode === "from_beginning"}
              onChange={() => setMode("from_beginning")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">Replay from beginning</span>
              <span className="block text-xs text-gray-400">
                New run with the original inputs.
              </span>
            </span>
          </label>

          <label
            className={
              REPLAY_FROM_STEP_ENABLED
                ? "flex items-start gap-2 rounded border border-surface-border bg-surface-base p-3 text-sm text-gray-200 hover:border-purple-500/50"
                : "flex items-start gap-2 rounded border border-surface-border bg-surface-base/50 p-3 text-sm text-gray-500 opacity-60"
            }
            title={
              REPLAY_FROM_STEP_ENABLED
                ? undefined
                : "Backend support for replay-from-step is not yet available."
            }
          >
            <input
              type="radio"
              name="replay-mode"
              value="from_step"
              checked={mode === "from_step"}
              onChange={() => setMode("from_step")}
              disabled={!REPLAY_FROM_STEP_ENABLED}
              className="mt-0.5"
              aria-describedby="from-step-hint"
            />
            <span>
              <span className="font-medium">Replay from step</span>
              <span
                id="from-step-hint"
                className="block text-xs text-gray-400"
              >
                {REPLAY_FROM_STEP_ENABLED
                  ? "Resume from a specific step (advanced)."
                  : "Coming soon — backend support pending."}
              </span>
            </span>
          </label>

          <label className="flex items-start gap-2 rounded border border-surface-border bg-surface-base p-3 text-sm text-gray-200 hover:border-purple-500/50">
            <input
              type="radio"
              name="replay-mode"
              value="with_overrides"
              checked={mode === "with_overrides"}
              onChange={() => setMode("with_overrides")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">Replay with overrides</span>
              <span className="block text-xs text-gray-400">
                Edit the input data before re-running.
              </span>
            </span>
          </label>
        </fieldset>

        {mode === "with_overrides" && (
          <div className="mb-4">
            <Label htmlFor="replay-input" className="mb-1 text-gray-300">
              Input Data (JSON)
            </Label>
            <Textarea
              id="replay-input"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              rows={6}
              className="border-surface-border bg-surface-base font-mono text-sm text-gray-200"
              disabled={submitting}
            />
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400"
          >
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleSubmit}
            disabled={submitting || mode === "from_step"}
            className="bg-purple-600 hover:bg-purple-700 text-white"
            data-testid="btn-replay-submit"
          >
            {submitting ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Repeat size={14} className="mr-1" />
            )}
            Replay
          </Button>
        </div>
      </div>
    </div>
  );
}
