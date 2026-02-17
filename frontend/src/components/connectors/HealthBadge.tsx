import { Wifi, WifiOff, AlertTriangle, Clock } from "lucide-react";

type HealthLevel = "healthy" | "degraded" | "error" | "unknown" | "connected" | "active" | "inactive" | "pending" | "disconnected";

interface HealthBadgeProps {
  status: HealthLevel;
  lastCheck?: string | null;
  className?: string;
}

const statusConfig: Record<string, { icon: typeof Wifi; label: string; color: string }> = {
  healthy: { icon: Wifi, label: "Healthy", color: "text-green-400 bg-green-500/10 border-green-500/30" },
  connected: { icon: Wifi, label: "Connected", color: "text-green-400 bg-green-500/10 border-green-500/30" },
  active: { icon: Wifi, label: "Active", color: "text-green-400 bg-green-500/10 border-green-500/30" },
  degraded: { icon: AlertTriangle, label: "Degraded", color: "text-yellow-400 bg-yellow-500/10 border-yellow-500/30" },
  error: { icon: WifiOff, label: "Error", color: "text-red-400 bg-red-500/10 border-red-500/30" },
  inactive: { icon: WifiOff, label: "Inactive", color: "text-gray-400 bg-gray-500/10 border-gray-500/30" },
  disconnected: { icon: WifiOff, label: "Disconnected", color: "text-gray-400 bg-gray-500/10 border-gray-500/30" },
  pending: { icon: Clock, label: "Pending", color: "text-blue-400 bg-blue-500/10 border-blue-500/30" },
  unknown: { icon: AlertTriangle, label: "Unknown", color: "text-gray-400 bg-gray-500/10 border-gray-500/30" },
};

export function HealthBadge({ status, lastCheck, className = "" }: HealthBadgeProps) {
  const cfg = statusConfig[status] ?? statusConfig.unknown;
  const Icon = cfg.icon;

  return (
    <div className={`inline-flex items-center gap-1.5 ${className}`}>
      <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${cfg.color}`}>
        <Icon size={12} />
        {cfg.label}
      </span>
      {lastCheck && (
        <span className="text-[10px] text-gray-500 dark:text-gray-500">
          {new Date(lastCheck).toLocaleTimeString()}
        </span>
      )}
    </div>
  );
}
