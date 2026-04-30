import { Check, XCircle, Clock, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import type { Approval } from "@/types/approvals";

interface ApprovalCardProps {
  approval: Approval;
  onApprove: (approval: Approval) => void;
  onReject: (approval: Approval) => void;
}

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-500/20 text-yellow-400",
  approved: "bg-green-500/20 text-green-400",
  rejected: "bg-red-500/20 text-red-400",
  expired: "bg-gray-500/20 text-gray-400",
};

function statusBadge(status: string) {
  const cls = STATUS_STYLES[status] ?? "bg-gray-500/20 text-gray-400";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${cls}`}
    >
      {status}
    </span>
  );
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function truncate(value: string, max = 8): string {
  if (value.length <= max) return value;
  return value.slice(0, max);
}

/**
 * Compact card showing approval metadata + Approve/Reject actions.
 *
 * Decision buttons are disabled when the approval is no longer pending —
 * the backend will return 409 anyway, but we surface the gate visually.
 */
export function ApprovalCard({
  approval,
  onApprove,
  onReject,
}: ApprovalCardProps) {
  const isPending = approval.status === "pending";

  return (
    <div
      className="rounded-lg border border-surface-border bg-surface-raised p-4 shadow-sm"
      data-testid="approval-card"
      data-approval-id={approval.id}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {statusBadge(approval.status)}
            <span className="text-xs text-gray-500">
              <Clock className="mr-1 inline" size={11} />
              requested {formatTimestamp(approval.requested_at)}
            </span>
          </div>
          <div className="mt-2 text-sm text-gray-200">
            <span className="text-gray-500">Step:</span>{" "}
            <code className="font-mono text-gray-200">
              {approval.step_id || "—"}
            </code>
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
            <span>
              <span className="text-gray-500">Run:</span>{" "}
              <code className="font-mono">{truncate(approval.run_id)}</code>
            </span>
            <Link
              to={`/executions/${approval.run_id}`}
              className="inline-flex items-center gap-0.5 text-purple-400 hover:text-purple-300"
              aria-label={`Open run ${approval.run_id}`}
            >
              <ExternalLink size={11} />
            </Link>
            {approval.requester_id && (
              <span>
                <span className="text-gray-500">requested by</span>{" "}
                <code className="font-mono">
                  {truncate(approval.requester_id)}
                </code>
              </span>
            )}
            {approval.expires_at && (
              <span>
                <span className="text-gray-500">expires</span>{" "}
                {formatTimestamp(approval.expires_at)}
              </span>
            )}
          </div>
          {approval.decision_reason && (
            <div className="mt-2 rounded bg-surface-base p-2 text-xs text-gray-300">
              <span className="text-gray-500">Reason:</span>{" "}
              {approval.decision_reason}
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
          <Button
            size="sm"
            onClick={() => onApprove(approval)}
            disabled={!isPending}
            className="bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
            aria-label={`Approve approval ${approval.id}`}
          >
            <Check size={14} className="mr-1" />
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onReject(approval)}
            disabled={!isPending}
            className="border-red-500/40 text-red-400 hover:bg-red-500/10 disabled:opacity-50"
            aria-label={`Reject approval ${approval.id}`}
          >
            <XCircle size={14} className="mr-1" />
            Reject
          </Button>
        </div>
      </div>
    </div>
  );
}
