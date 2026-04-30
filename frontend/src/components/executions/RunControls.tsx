import { useState } from "react";
import {
  Pause,
  Play,
  StopCircle,
  RotateCcw,
  Repeat,
  Send,
  Loader2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import { cancelRun, startRun } from "@/api/runs";
import { sendSignal } from "@/api/signals";
import { resumeRun } from "@/api/approvals";
import type { WorkflowRun } from "@/types/workflow_run";
import type { SignalType } from "@/types/signals";
import { ReplayDialog } from "./ReplayDialog";

interface RunControlsProps {
  run: WorkflowRun;
  isAdmin?: boolean;
  onChanged?: () => void;
  onReplayed?: (newRun: WorkflowRun) => void;
}

function genIdempotencyKey(prefix: string): string {
  // Lightweight uuid-ish — enough entropy for an idempotency key.
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

interface SignalDialogProps {
  runId: string;
  onClose: () => void;
  onSubmitted: () => void;
}

function SignalDialog({ runId, onClose, onSubmitted }: SignalDialogProps) {
  const [signalType, setSignalType] = useState<SignalType | string>("custom");
  const [stepId, setStepId] = useState("");
  const [payloadText, setPayloadText] = useState("{}");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const payload = payloadText.trim()
        ? (JSON.parse(payloadText) as Record<string, unknown>)
        : {};
      await sendSignal(runId, {
        signal_type: signalType,
        payload,
        step_id: stepId.trim() || undefined,
      });
      onSubmitted();
      onClose();
    } catch (err) {
      setError(
        err instanceof SyntaxError
          ? "Payload must be valid JSON"
          : err instanceof Error
            ? err.message
            : "Failed to send signal",
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
      aria-labelledby="send-signal-title"
    >
      <div className="w-full max-w-lg rounded-lg border border-surface-border bg-surface-raised p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2
            id="send-signal-title"
            className="text-lg font-semibold text-white"
          >
            Send signal
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mb-4">
          <Label htmlFor="signal-type" className="mb-1 text-gray-300">
            Signal type
          </Label>
          <select
            id="signal-type"
            value={signalType}
            onChange={(e) => setSignalType(e.target.value)}
            className="w-full rounded-md border border-surface-border bg-surface-base px-3 py-2 text-sm text-white"
          >
            <option value="cancel">cancel</option>
            <option value="input.provided">input.provided</option>
            <option value="approval.granted">approval.granted</option>
            <option value="approval.rejected">approval.rejected</option>
            <option value="custom">custom</option>
          </select>
        </div>

        <div className="mb-4">
          <Label htmlFor="signal-step-id" className="mb-1 text-gray-300">
            Step ID (optional)
          </Label>
          <input
            id="signal-step-id"
            type="text"
            value={stepId}
            onChange={(e) => setStepId(e.target.value)}
            placeholder="step_id"
            className="w-full rounded-md border border-surface-border bg-surface-base px-3 py-2 text-sm text-white"
          />
        </div>

        <div className="mb-4">
          <Label htmlFor="signal-payload" className="mb-1 text-gray-300">
            Payload (JSON)
          </Label>
          <Textarea
            id="signal-payload"
            value={payloadText}
            onChange={(e) => setPayloadText(e.target.value)}
            rows={5}
            className="border-surface-border bg-surface-base font-mono text-sm text-gray-200"
          />
        </div>

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
            disabled={submitting}
            className="bg-purple-600 hover:bg-purple-700 text-white"
          >
            {submitting ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Send size={14} className="mr-1" />
            )}
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Composite of run-control buttons gated on the current run status.
 *
 * Button availability matrix:
 *   - running   → Cancel
 *   - paused    → Resume + Cancel
 *   - failed    → Retry
 *   - completed → Replay
 *   - any state → "Send Signal" (admin only)
 *
 * "Pause" is not available — the backend has no first-class pause-from-running
 * endpoint; pausing happens implicitly via approval/input requests.
 */
export function RunControls({
  run,
  isAdmin = false,
  onChanged,
  onReplayed,
}: RunControlsProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showReplay, setShowReplay] = useState(false);
  const [showSignal, setShowSignal] = useState(false);

  const status = run.status;
  const showCancel = status === "running" || status === "paused";
  const showResume = status === "paused";
  const showRetry = status === "failed";
  const showReplayBtn = status === "completed";

  function notifyChanged() {
    if (onChanged) onChanged();
  }

  async function handleCancel() {
    setBusy("cancel");
    setError(null);
    try {
      await cancelRun(run.id);
      notifyChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleResume() {
    setBusy("resume");
    setError(null);
    try {
      await resumeRun(run.id);
      notifyChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resume failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleRetry() {
    setBusy("retry");
    setError(null);
    try {
      // Re-dispatch with same input + a fresh idempotency key so the
      // backend creates a new run rather than replaying the existing one.
      const args = run.workflow_id
        ? {
            workflow_id: run.workflow_id,
            input_data: run.input_data ?? {},
            idempotency_key: genIdempotencyKey("retry"),
          }
        : run.agent_id
          ? {
              agent_id: run.agent_id,
              input_data: run.input_data ?? {},
              idempotency_key: genIdempotencyKey("retry"),
            }
          : null;
      if (!args) {
        throw new Error("Run has neither workflow_id nor agent_id");
      }
      const res = await startRun(args);
      if (onReplayed) onReplayed(res.run);
      notifyChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2" data-testid="run-controls">
      <div className="flex flex-wrap items-center gap-2">
        {showResume && (
          <Button
            size="sm"
            onClick={handleResume}
            disabled={busy !== null}
            className="bg-blue-600 hover:bg-blue-700 text-white"
            data-testid="btn-resume"
          >
            {busy === "resume" ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Play size={14} className="mr-1" />
            )}
            Resume
          </Button>
        )}

        {showCancel && (
          <Button
            size="sm"
            variant="outline"
            onClick={handleCancel}
            disabled={busy !== null}
            className="border-red-500/40 text-red-400 hover:bg-red-500/10"
            data-testid="btn-cancel"
          >
            {busy === "cancel" ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <StopCircle size={14} className="mr-1" />
            )}
            Cancel
          </Button>
        )}

        {showRetry && (
          <Button
            size="sm"
            onClick={handleRetry}
            disabled={busy !== null}
            className="bg-yellow-600 hover:bg-yellow-700 text-white"
            data-testid="btn-retry"
          >
            {busy === "retry" ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <RotateCcw size={14} className="mr-1" />
            )}
            Retry
          </Button>
        )}

        {showReplayBtn && (
          <Button
            size="sm"
            onClick={() => setShowReplay(true)}
            disabled={busy !== null}
            className="bg-purple-600 hover:bg-purple-700 text-white"
            data-testid="btn-replay"
          >
            <Repeat size={14} className="mr-1" />
            Replay
          </Button>
        )}

        {isAdmin && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowSignal(true)}
            disabled={busy !== null}
            data-testid="btn-send-signal"
          >
            <Send size={14} className="mr-1" />
            Send Signal
          </Button>
        )}

        {/* The Pause control is not currently exposed — kept here as a
            disabled placeholder so the operator sees the intended set. */}
        {status === "running" && (
          <Button
            size="sm"
            variant="ghost"
            disabled
            title="Pause is implicit — issued by approval / input nodes"
            data-testid="btn-pause-placeholder"
          >
            <Pause size={14} className="mr-1" />
            Pause
          </Button>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400"
        >
          {error}
        </div>
      )}

      {showReplay && (
        <ReplayDialog
          run={run}
          onClose={() => setShowReplay(false)}
          onReplayed={(newRun) => {
            if (onReplayed) onReplayed(newRun);
            notifyChanged();
          }}
        />
      )}

      {showSignal && (
        <SignalDialog
          runId={run.id}
          onClose={() => setShowSignal(false)}
          onSubmitted={notifyChanged}
        />
      )}
    </div>
  );
}
