import { useState } from "react";
import { CheckCircle, XCircle, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/utils/cn";

// ── Types ────────────────────────────────────────────────────────────

interface ApprovalPanelProps {
  title: string;
  description?: string;
  metadata?: Record<string, string>;
  requireComment?: boolean;
  onAction: (decision: "approve" | "reject", comment: string) => void;
}

// ── Component ────────────────────────────────────────────────────────

export function ApprovalPanel({
  title,
  description,
  metadata,
  requireComment = false,
  onAction,
}: ApprovalPanelProps) {
  const [comment, setComment] = useState("");
  const [decided, setDecided] = useState<"approve" | "reject" | null>(null);

  function handleDecision(decision: "approve" | "reject") {
    if (requireComment && !comment.trim()) return;
    setDecided(decision);
    onAction(decision, comment);
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] p-4">
      <h4 className="mb-1 text-sm font-semibold text-white">{title}</h4>
      {description && (
        <p className="mb-3 text-xs text-gray-400">{description}</p>
      )}

      {metadata && Object.keys(metadata).length > 0 && (
        <div className="mb-3 space-y-1 rounded border border-[#2a2d37] bg-[#1a1d27] p-3">
          {Object.entries(metadata).map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs">
              <span className="text-gray-500">{k}</span>
              <span className="text-gray-300">{v}</span>
            </div>
          ))}
        </div>
      )}

      {decided ? (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md p-3 text-sm",
            decided === "approve"
              ? "bg-green-500/10 text-green-400"
              : "bg-red-500/10 text-red-400",
          )}
        >
          {decided === "approve" ? (
            <CheckCircle size={16} />
          ) : (
            <XCircle size={16} />
          )}
          <span>
            {decided === "approve" ? "Approved" : "Rejected"}
            {comment && ` — "${comment}"`}
          </span>
        </div>
      ) : (
        <>
          <div className="mb-3">
            <label className="mb-1 flex items-center gap-1 text-xs text-gray-400">
              <MessageSquare size={12} />
              Comment {requireComment && <span className="text-red-400">*</span>}
            </label>
            <textarea
              className="w-full rounded-md border border-[#2a2d37] bg-[#1a1d27] px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
              placeholder="Add a comment…"
              rows={2}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => handleDecision("approve")}
              disabled={requireComment && !comment.trim()}
            >
              <CheckCircle size={14} className="mr-1" />
              Approve
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={() => handleDecision("reject")}
              disabled={requireComment && !comment.trim()}
            >
              <XCircle size={14} className="mr-1" />
              Reject
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
