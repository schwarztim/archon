/**
 * TanStack Query hooks for the approvals surface.
 *
 * Pattern mirrors ``useAgents`` — list / single / mutation hooks with
 * shared query keys so list invalidation flows through after a decision.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveApproval,
  getApproval,
  listApprovals,
  rejectApproval,
  resumeRun,
  type ListApprovalsArgs,
} from "@/api/approvals";

const APPROVALS_KEY = ["approvals"] as const;

/**
 * List approvals. Re-fetches on opts change. Default ``status="pending"``
 * keeps the page focused on actionable items.
 */
export function useApprovalsList(opts: ListApprovalsArgs = {}) {
  return useQuery({
    queryKey: [...APPROVALS_KEY, "list", opts],
    queryFn: () => listApprovals(opts),
  });
}

/** Fetch a single approval by id. */
export function useApproval(id: string | null) {
  return useQuery({
    queryKey: [...APPROVALS_KEY, "single", id],
    queryFn: () => getApproval(id!),
    enabled: !!id,
  });
}

/** Approve an approval and invalidate the list. */
export function useApproveApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      approveApproval(id, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: APPROVALS_KEY });
    },
  });
}

/** Reject an approval and invalidate the list. */
export function useRejectApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      rejectApproval(id, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: APPROVALS_KEY });
    },
  });
}

/** Generic resume — for operator-driven nudges to the dispatcher. */
export function useResumeRun() {
  return useMutation({
    mutationFn: (runId: string) => resumeRun(runId),
  });
}
