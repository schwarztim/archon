import {
  Shield,
  User,
  Zap,
  Settings,
  Key,
  Globe,
  FileText,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";

export interface AuditEntry {
  id: string;
  timestamp?: string;
  action: string;
  resource_type: string;
  resource_id: string;
  actor_id: string;
  outcome?: string;
  details?: Record<string, unknown>;
  ip_address?: string | null;
  created_at: string;
}

const ACTION_ICONS: Record<string, LucideIcon> = {
  agent: Zap,
  user: User,
  secret: Key,
  policy: Shield,
  deployment: Globe,
  connector: Settings,
  workflow: FileText,
  login: User,
  sso: Globe,
  approval: Shield,
  budget: FileText,
  template: FileText,
};

function getIcon(action: string): LucideIcon {
  const prefix = action.split(".")[0] ?? "";
  return ACTION_ICONS[prefix] ?? AlertTriangle;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

interface Props {
  entry: AuditEntry;
  expanded: boolean;
  onToggle: () => void;
}

export function AuditEventCard({ entry, expanded, onToggle }: Props) {
  const Icon = getIcon(entry.action);
  const ts = entry.timestamp ?? entry.created_at;
  const outcome = entry.outcome ?? (entry.details?.outcome as string) ?? "success";
  const isFail = outcome === "failure" || outcome === "error";

  return (
    <div className="relative pl-8">
      {/* Timeline dot */}
      <div
        className={`absolute left-0 top-3 h-4 w-4 rounded-full border-2 ${
          isFail
            ? "border-red-500 bg-red-500/20"
            : "border-purple-500 bg-purple-500/20"
        }`}
      />

      <div
        className="mb-3 cursor-pointer rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4 transition-colors hover:border-purple-500/30"
        onClick={onToggle}
      >
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <Icon
              size={16}
              className={isFail ? "text-red-400" : "text-purple-400"}
            />
            <div>
              <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-gray-200">
                {entry.action}
              </code>
              <span className="ml-2 text-sm text-gray-400">
                on {entry.resource_type}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                isFail
                  ? "bg-red-500/20 text-red-400"
                  : "bg-green-500/20 text-green-400"
              }`}
            >
              {outcome}
            </span>
            <span className="text-xs text-gray-500">{relativeTime(ts)}</span>
          </div>
        </div>

        <div className="mt-1 text-xs text-gray-500">
          Actor: {entry.actor_id}
        </div>

        {expanded && (
          <div className="mt-3 grid grid-cols-2 gap-3 border-t border-[#2a2d37] pt-3 text-xs">
            <div>
              <span className="text-gray-500">Resource ID:</span>{" "}
              <span className="text-gray-300">{entry.resource_id}</span>
            </div>
            <div>
              <span className="text-gray-500">Time:</span>{" "}
              <span className="text-gray-300">
                {new Date(ts).toLocaleString()}
              </span>
            </div>
            {entry.ip_address && (
              <div>
                <span className="text-gray-500">IP:</span>{" "}
                <span className="text-gray-300">{entry.ip_address}</span>
              </div>
            )}
            {entry.details && (
              <div className="col-span-2">
                <span className="text-gray-500">Details:</span>
                <pre className="mt-1 rounded bg-black/30 p-2 text-gray-300">
                  {JSON.stringify(entry.details, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
