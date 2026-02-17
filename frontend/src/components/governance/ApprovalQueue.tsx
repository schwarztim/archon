import { useState, useEffect } from "react";
import { Clock, Loader2 } from "lucide-react";
import { listApprovals, type ApprovalRequest } from "@/api/governance";
import { ApprovalCard } from "./ApprovalCard";

interface Props {
  refreshKey: number;
}

export function ApprovalQueue({ refreshKey }: Props) {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("pending");

  async function fetchApprovals() {
    setLoading(true);
    try {
      const params = filter ? { status: filter } : {};
      const res = await listApprovals({ ...params, limit: 50 });
      setApprovals(Array.isArray(res.data) ? res.data : []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchApprovals(); }, [refreshKey, filter]);

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <Clock size={14} /> Approval Queue ({approvals.length})
        </h2>
        <div className="flex gap-1">
          {["pending", "approved", "rejected", ""].map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`rounded-md px-2 py-1 text-xs transition-colors ${
                filter === s ? "bg-purple-500/20 text-purple-400" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {s || "All"}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex h-24 items-center justify-center">
          <Loader2 size={20} className="animate-spin text-gray-500" />
        </div>
      ) : approvals.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12">
          <Clock size={32} className="mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">No {filter || ""} approvals.</p>
        </div>
      ) : (
        <div className="divide-y divide-[#2a2d37]">
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              onDecisionMade={fetchApprovals}
            />
          ))}
        </div>
      )}
    </div>
  );
}
