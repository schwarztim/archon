import { useState } from "react";
import { Loader2, X, Check, XCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import type { Approval } from "@/types/approvals";

export type Decision = "approve" | "reject";

interface ApprovalDecisionDialogProps {
  approval: Approval;
  decision: Decision;
  onClose: () => void;
  onSubmit: (reason: string) => Promise<void> | void;
  submitting?: boolean;
  error?: string | null;
}

/**
 * Modal dialog confirming an approve/reject decision.
 *
 * The reason field is optional — the backend accepts ``reason: null`` —
 * but we encourage entering one for the audit trail.
 */
export function ApprovalDecisionDialog({
  approval,
  decision,
  onClose,
  onSubmit,
  submitting = false,
  error = null,
}: ApprovalDecisionDialogProps) {
  const [reason, setReason] = useState("");

  const isApprove = decision === "approve";
  const verb = isApprove ? "Approve" : "Reject";
  const Icon = isApprove ? Check : XCircle;
  const buttonClass = isApprove
    ? "bg-green-600 hover:bg-green-700 text-white"
    : "bg-red-600 hover:bg-red-700 text-white";

  function handleSubmit() {
    void onSubmit(reason.trim());
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      role="dialog"
      aria-modal="true"
      aria-labelledby="approval-decision-title"
    >
      <div className="w-full max-w-lg rounded-lg border border-surface-border bg-surface-raised p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2
            id="approval-decision-title"
            className="text-lg font-semibold text-white"
          >
            {verb} approval
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mb-4 rounded border border-surface-border bg-surface-base p-3 text-xs text-gray-300">
          <div>
            <span className="text-gray-500">Run:</span>{" "}
            <code className="text-gray-200">{approval.run_id.slice(0, 8)}</code>
          </div>
          <div>
            <span className="text-gray-500">Step:</span>{" "}
            <code className="text-gray-200">{approval.step_id || "—"}</code>
          </div>
        </div>

        <div className="mb-4">
          <Label htmlFor="decision-reason" className="mb-1 text-gray-300">
            Reason (optional)
          </Label>
          <Textarea
            id="decision-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            placeholder={
              isApprove
                ? "Why is this approved? (audit trail)"
                : "Why is this rejected? (audit trail)"
            }
            className="border-surface-border bg-surface-base text-sm text-gray-200"
            disabled={submitting}
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
            className={buttonClass}
          >
            {submitting ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Icon size={14} className="mr-1" />
            )}
            {verb}
          </Button>
        </div>
      </div>
    </div>
  );
}
