import { Clock, Rocket, Undo2, ArrowUpRight } from "lucide-react";
import type { DeploymentHistoryEntry } from "@/types/models";

interface DeploymentHistoryProps {
  entries: DeploymentHistoryEntry[];
  loading: boolean;
}

function statusIcon(status: string) {
  switch (status) {
    case "active":
    case "deploying":
      return <Rocket size={12} className="text-green-400" />;
    case "rolled_back":
      return <Undo2 size={12} className="text-red-400" />;
    default:
      return <ArrowUpRight size={12} className="text-gray-400" />;
  }
}

function statusColor(status: string): string {
  const map: Record<string, string> = {
    active: "border-l-green-400",
    deploying: "border-l-blue-400",
    rolled_back: "border-l-red-400",
    shadow: "border-l-purple-400",
    retired: "border-l-gray-600",
  };
  return map[status] ?? "border-l-gray-500";
}

export function DeploymentHistory({ entries, loading }: DeploymentHistoryProps) {
  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center text-gray-500 text-sm">
        Loading history…
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8">
        <Clock size={24} className="mb-2 text-gray-600" />
        <p className="text-sm text-gray-500">No deployment history</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className={`rounded-md border-l-2 bg-black/20 p-3 ${statusColor(entry.status)}`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {statusIcon(entry.status)}
              <span className="text-xs font-medium text-white">
                {entry.agent_name ?? entry.agent_id.slice(0, 8) + "…"}
              </span>
              <span className="text-[10px] text-gray-400">v{entry.version_id.slice(0, 8)}</span>
            </div>
            <div className="flex items-center gap-2 text-[10px] text-gray-500">
              <span className="rounded-full bg-gray-500/20 px-2 py-0.5">{entry.strategy}</span>
              <span className="capitalize">{entry.status}</span>
            </div>
          </div>

          <div className="mt-1 flex items-center gap-3 text-[10px] text-gray-500">
            {entry.started_at && (
              <span className="flex items-center gap-1">
                <Clock size={9} />
                {new Date(entry.started_at).toLocaleString()}
              </span>
            )}
            {entry.duration_seconds != null && (
              <span>{entry.duration_seconds.toFixed(1)}s</span>
            )}
            {entry.deployed_by && <span>by {entry.deployed_by}</span>}
          </div>

          {entry.rollback_reason && (
            <p className="mt-1 text-[10px] text-red-400">{entry.rollback_reason}</p>
          )}
        </div>
      ))}
    </div>
  );
}
