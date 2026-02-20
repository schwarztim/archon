import { ArrowUpRight, ArrowDownRight } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface StageDeployment {
  id: string;
  agent_id: string;
  agent_name?: string;
  version_id: string;
  status: string;
  environment: string;
}

interface StageColumnProps {
  stage: string;
  label: string;
  deployments: StageDeployment[];
  color: string;
  dot: string;
  text: string;
  isFirst: boolean;
  isLast: boolean;
  onPromote?: (deploymentId: string) => void;
  onDemote?: (deploymentId: string) => void;
}

function statusBadge(status: string) {
  const cls: Record<string, string> = {
    pending: "bg-gray-500/20 text-gray-400",
    deploying: "bg-blue-500/20 text-blue-400",
    active: "bg-green-500/20 text-green-400",
    shadow: "bg-purple-500/20 text-purple-400",
    rolled_back: "bg-red-500/20 text-red-400",
    failed: "bg-red-500/20 text-red-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${cls[status] ?? "bg-gray-500/20 text-gray-400"}`}>
      {status}
    </span>
  );
}

export function StageColumn({
  label,
  deployments,
  color,
  dot,
  text,
  isFirst,
  isLast,
  onPromote,
  onDemote,
}: StageColumnProps) {
  return (
    <div className={`min-w-[200px] flex-1 rounded-lg border p-3 ${color}`}>
      <div className="mb-2 flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
        <span className={`text-xs font-semibold ${text}`}>{label}</span>
        <span className="ml-auto text-[10px] text-gray-500">{deployments.length}</span>
      </div>
      {deployments.length === 0 ? (
        <p className="text-[11px] text-gray-600">No deployments</p>
      ) : (
        <div className="space-y-2">
          {deployments.slice(0, 5).map((d) => (
            <div key={d.id} className="rounded-md bg-black/20 px-2 py-1.5">
              <p className="truncate text-xs font-medium text-white">
                {d.agent_name ?? d.agent_id.slice(0, 8) + "…"}
              </p>
              <div className="flex items-center gap-1 text-[10px]">
                <span className="text-gray-400">v{d.version_id.slice(0, 8)}</span>
                {statusBadge(d.status)}
              </div>
              <div className="mt-1 flex gap-1">
                {!isLast && onPromote && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 px-1 text-[10px]"
                    onClick={() => onPromote(d.id)}
                  >
                    <ArrowUpRight size={10} className="mr-0.5" />
                    Promote
                  </Button>
                )}
                {!isFirst && onDemote && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 px-1 text-[10px]"
                    onClick={() => onDemote(d.id)}
                  >
                    <ArrowDownRight size={10} className="mr-0.5" />
                    Demote
                  </Button>
                )}
              </div>
            </div>
          ))}
          {deployments.length > 5 && (
            <p className="text-[10px] text-gray-500">+{deployments.length - 5} more</p>
          )}
        </div>
      )}
    </div>
  );
}
