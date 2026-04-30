import { useMemo, useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { useAuth } from "@/providers/auth-provider";
import {
  useApprovalsList,
  useApproveApproval,
  useRejectApproval,
} from "@/hooks/useApprovals";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import {
  ApprovalDecisionDialog,
  type Decision,
} from "@/components/approvals/ApprovalDecisionDialog";
import type { Approval, ApprovalStatus } from "@/types/approvals";

type Filter = "pending" | "all" | "decided";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "pending", label: "Pending" },
  { id: "decided", label: "Decided" },
  { id: "all", label: "All" },
];

const DECIDED_STATUSES: ApprovalStatus[] = [
  "approved",
  "rejected",
  "expired",
];

/**
 * Approvals page — operator-facing list of human-in-loop approval requests.
 *
 * Tenant scoping is handled server-side; admins see all tenants, others see
 * only their own. We pass through the user's role only to decide whether
 * to surface a "showing all tenants" badge in the header.
 */
export function ApprovalsPage() {
  const { user, hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [filter, setFilter] = useState<Filter>("pending");
  const [activeApproval, setActiveApproval] = useState<Approval | null>(null);
  const [decision, setDecision] = useState<Decision>("approve");
  const [submitError, setSubmitError] = useState<string | null>(null);

  // The backend currently only supports ``status=pending`` server-side; for
  // ``decided`` and ``all`` we still query pending and filter client-side
  // (the backend returns an empty list with a meta note for non-pending).
  const query = useApprovalsList(
    filter === "pending" ? { status: "pending" } : { status: "pending" },
  );

  const approveMutation = useApproveApproval();
  const rejectMutation = useRejectApproval();
  const submitting = approveMutation.isPending || rejectMutation.isPending;

  const visible = useMemo(() => {
    const data = query.data ?? [];
    if (filter === "pending") {
      return data.filter((a) => a.status === "pending");
    }
    if (filter === "decided") {
      return data.filter((a) => DECIDED_STATUSES.includes(a.status));
    }
    return data;
  }, [query.data, filter]);

  function openDecision(approval: Approval, kind: Decision) {
    setActiveApproval(approval);
    setDecision(kind);
    setSubmitError(null);
  }

  function closeDecision() {
    if (submitting) return;
    setActiveApproval(null);
    setSubmitError(null);
  }

  async function submitDecision(reason: string) {
    if (!activeApproval) return;
    setSubmitError(null);
    const args = { id: activeApproval.id, reason: reason || undefined };
    try {
      if (decision === "approve") {
        await approveMutation.mutateAsync(args);
      } else {
        await rejectMutation.mutateAsync(args);
      }
      setActiveApproval(null);
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : `Failed to ${decision} approval`;
      setSubmitError(msg);
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-white">
            <ShieldCheck size={22} className="text-purple-400" />
            Approvals
          </h1>
          <p className="text-sm text-gray-400">
            Human-in-the-loop approvals for paused runs.
            {isAdmin && (
              <span className="ml-2 rounded bg-purple-500/20 px-1.5 py-0.5 text-xs text-purple-300">
                admin · all tenants
              </span>
            )}
            {!isAdmin && user?.tenant_id && (
              <span className="ml-2 text-xs text-gray-500">
                tenant {user.tenant_id.slice(0, 8)}
              </span>
            )}
          </p>
        </div>
      </div>

      <div className="mb-4 flex gap-1 rounded-md border border-surface-border bg-surface-raised p-1">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            className={
              filter === f.id
                ? "rounded px-3 py-1 text-sm font-medium bg-purple-600 text-white"
                : "rounded px-3 py-1 text-sm font-medium text-gray-400 hover:bg-surface-base hover:text-gray-200"
            }
          >
            {f.label}
          </button>
        ))}
      </div>

      {query.isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={14} className="animate-spin" />
          Loading approvals…
        </div>
      )}

      {query.isError && !query.isLoading && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          Failed to load approvals.{" "}
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="underline"
          >
            Retry
          </button>
        </div>
      )}

      {!query.isLoading && !query.isError && visible.length === 0 && (
        <div className="rounded border border-surface-border bg-surface-raised p-8 text-center text-sm text-gray-400">
          No approvals to show.
        </div>
      )}

      <div className="space-y-3">
        {visible.map((a) => (
          <ApprovalCard
            key={a.id}
            approval={a}
            onApprove={(approval) => openDecision(approval, "approve")}
            onReject={(approval) => openDecision(approval, "reject")}
          />
        ))}
      </div>

      {activeApproval && (
        <ApprovalDecisionDialog
          approval={activeApproval}
          decision={decision}
          onClose={closeDecision}
          onSubmit={submitDecision}
          submitting={submitting}
          error={submitError}
        />
      )}
    </div>
  );
}
