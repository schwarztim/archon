import { Server, HeartPulse, Clock } from "lucide-react";
import type { EnvironmentInfo } from "@/types/models";

interface EnvironmentCardProps {
  env: EnvironmentInfo;
  onSelect?: (envName: string) => void;
}

function healthDot(status: string) {
  const cls: Record<string, string> = {
    healthy: "bg-green-400",
    degraded: "bg-yellow-400",
    unhealthy: "bg-red-400",
    unknown: "bg-gray-400",
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${cls[status] ?? "bg-gray-400"}`} />;
}

export function EnvironmentCard({ env, onSelect }: EnvironmentCardProps) {
  return (
    <div
      className="cursor-pointer rounded-lg border border-surface-border bg-surface-raised p-4 transition-colors hover:border-purple-500/30"
      onClick={() => onSelect?.(env.name)}
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server size={14} className="text-purple-400" />
          <span className="text-sm font-medium text-white">{env.display_name}</span>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
          env.status === "active"
            ? "bg-green-500/20 text-green-400"
            : "bg-gray-500/20 text-gray-400"
        }`}>
          {env.status}
        </span>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">Version</span>
          <span className="text-gray-300">{env.deployed_version?.slice(0, 8) ?? "—"}</span>
        </div>

        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">Health</span>
          <div className="flex items-center gap-1.5">
            {healthDot(env.health_status)}
            <span className="capitalize text-gray-300">{env.health_status}</span>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">Instances</span>
          <span className="text-gray-300">{env.instance_count}</span>
        </div>

        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">Last Deploy</span>
          <span className="text-gray-300">
            {env.last_deploy_at ? (
              <span className="flex items-center gap-1">
                <Clock size={10} />
                {new Date(env.last_deploy_at).toLocaleDateString()}
              </span>
            ) : (
              "—"
            )}
          </span>
        </div>
      </div>

      {env.agent_name && (
        <div className="mt-2 rounded-md bg-black/20 px-2 py-1 text-[10px] text-gray-400">
          <HeartPulse size={10} className="mr-1 inline" />
          {env.agent_name}
        </div>
      )}
    </div>
  );
}
