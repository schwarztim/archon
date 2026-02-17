import { useState } from "react";
import { CheckCircle, XCircle, Loader2, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { approveRequest, rejectRequest, type ApprovalRequest } from "@/api/governance";

interface Props {
  approval: ApprovalRequest;
  onDecisionMade: () => void;
}

function statusBadge(status: string) {
  if (status === "approved")
    return <span className="rounded-full bg-green-500/20 px-2 py-0.5 text-xs font-medium text-green-400">Approved</span>;
  if (status === "rejected")
    return <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-medium text-red-400">Rejected</span>;
  return <span className="rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs font-medium text-yellow-400">Pending</span>;
}

function ruleLabel(rule: string) {
  if (rule === "any_one") return "Any 1 reviewer";
  if (rule === "all") return "All reviewers";
  if (rule === "majority") return "Majority";
  return rule;
}

export function ApprovalCard({ approval, onDecisionMade }: Props) {
  const [comment, setComment] = useState("");
  const [acting, setActing] = useState(false);

  async function handleApprove() {
    setActing(true);
    try {
      await approveRequest(approval.id, comment);
      setComment("");
      onDecisionMade();
    } catch {
      /* ignore */
    } finally {
      setActing(false);
    }
  }

  async function handleReject() {
    setActing(true);
    try {
      await rejectRequest(approval.id, comment);
      setComment("");
      onDecisionMade();
    } catch {
      /* ignore */
    } finally {
      setActing(false);
    }
  }

  const isPending = approval.status === "pending";

  return (
    <div className="px-4 py-4">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <span className="font-medium text-white">{approval.agent_name || approval.agent_id}</span>
          <span className="ml-2 text-xs text-gray-400">by {approval.requester_name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded bg-purple-500/20 px-2 py-0.5 text-xs text-purple-400">{approval.action}</span>
          {statusBadge(approval.status)}
        </div>
      </div>

      <div className="mb-2 flex items-center gap-3 text-xs text-gray-500">
        <span>Rule: {ruleLabel(approval.approval_rule)}</span>
        {approval.reviewers.length > 0 && (
          <span>Reviewers: {approval.reviewers.join(", ")}</span>
        )}
        <span>{new Date(approval.created_at).toLocaleString()}</span>
      </div>

      {approval.comment && (
        <p className="mb-2 text-xs text-gray-400 italic">&quot;{approval.comment}&quot;</p>
      )}

      {/* Show decisions history */}
      {approval.decisions.length > 0 && (
        <div className="mb-2 space-y-1">
          {approval.decisions.map((d, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              {d.decision === "approved" ? (
                <CheckCircle size={12} className="text-green-400" />
              ) : (
                <XCircle size={12} className="text-red-400" />
              )}
              <span className="text-gray-400">{d.reviewer}</span>
              <span className="text-gray-500">{d.decision}</span>
              {d.comment && <span className="text-gray-600">— {d.comment}</span>}
            </div>
          ))}
        </div>
      )}

      {isPending && (
        <>
          <div className="mb-2 flex items-center gap-2">
            <MessageSquare size={14} className="text-gray-500" />
            <textarea
              className="flex-1 rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-2 text-sm text-white placeholder:text-gray-600"
              rows={2}
              placeholder="Add a comment..."
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={handleApprove} disabled={acting} className="bg-green-600 hover:bg-green-700">
              {acting ? <Loader2 size={14} className="mr-1 animate-spin" /> : <CheckCircle size={14} className="mr-1" />}
              Approve
            </Button>
            <Button size="sm" variant="secondary" onClick={handleReject} disabled={acting} className="border-red-500/30 text-red-400 hover:bg-red-500/10">
              {acting ? <Loader2 size={14} className="mr-1 animate-spin" /> : <XCircle size={14} className="mr-1" />}
              Reject
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
