import { useNavigate } from "react-router-dom";
import {
  Activity,
  Clock,
  Bot,
  Play,
  Settings,
  Shield,
  UserCheck,
  FileText,
} from "lucide-react";
import type { AuditEntry } from "@/types/models";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function actionIcon(action: string) {
  const lower = action.toLowerCase();
  if (lower.includes("agent")) return <Bot size={14} />;
  if (lower.includes("execut") || lower.includes("run")) return <Play size={14} />;
  if (lower.includes("policy") || lower.includes("compliance")) return <Shield size={14} />;
  if (lower.includes("user") || lower.includes("auth")) return <UserCheck size={14} />;
  if (lower.includes("config") || lower.includes("setting")) return <Settings size={14} />;
  if (lower.includes("model") || lower.includes("template")) return <FileText size={14} />;
  return <Activity size={14} />;
}

interface ActivityFeedProps {
  events: AuditEntry[];
}

export function ActivityFeed({ events }: ActivityFeedProps) {
  const navigate = useNavigate();

  if (events.length === 0) {
    return (
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Recent Activity</h2>
        </div>
        <div className="flex flex-col items-center justify-center py-8">
          <Activity size={32} className="mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">No recent activity</p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Recent Activity</h2>
        <button
          type="button"
          onClick={() => navigate("/governance")}
          className="text-xs text-purple-400 hover:text-purple-300"
        >
          View All →
        </button>
      </div>
      <ul className="divide-y divide-[#2a2d37]">
        {events.slice(0, 10).map((event) => (
          <li key={event.id} className="flex items-start gap-3 px-4 py-3">
            <span className="mt-0.5 shrink-0 text-purple-400">
              {actionIcon(event.action)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-white">
                <span className="font-medium">{event.action}</span>
                <span className="text-gray-400"> on </span>
                <span className="text-gray-300">{event.resource_type}</span>
              </p>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Clock size={12} />
                <span>{relativeTime(event.created_at)}</span>
                {event.actor && <span>· {event.actor}</span>}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
