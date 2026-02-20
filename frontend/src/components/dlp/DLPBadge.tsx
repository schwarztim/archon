import { Shield, ShieldAlert, ShieldCheck, ShieldOff } from "lucide-react";

interface DLPBadgeProps {
  /** Number of DLP detections or status indicator */
  status?: "clean" | "detected" | "blocked" | "redacted";
  /** Count of findings to show */
  count?: number;
  /** Size variant */
  size?: "sm" | "md";
  /** Tooltip text */
  title?: string;
}

const STATUS_CONFIG: Record<string, { icon: React.ReactNode; bg: string; label: string }> = {
  clean: {
    icon: <ShieldCheck size={12} />,
    bg: "bg-green-500/20 text-green-400 border-green-500/30",
    label: "Clean",
  },
  detected: {
    icon: <ShieldAlert size={12} />,
    bg: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    label: "Detected",
  },
  blocked: {
    icon: <ShieldOff size={12} />,
    bg: "bg-red-500/20 text-red-400 border-red-500/30",
    label: "Blocked",
  },
  redacted: {
    icon: <Shield size={12} />,
    bg: "bg-purple-500/20 text-purple-400 border-purple-500/30",
    label: "Redacted",
  },
};

/**
 * Inline DLP badge for agent cards and execution traces.
 * Shows DLP scan status with optional finding count.
 */
export function DLPBadge({
  status = "clean",
  count,
  size = "sm",
  title,
}: DLPBadgeProps) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.clean;
  const isLarge = size === "md";

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border ${config?.bg} ${
        isLarge ? "px-2.5 py-1 text-xs" : "px-1.5 py-0.5 text-[10px]"
      } font-medium`}
      title={title ?? `DLP: ${config?.label}${count != null ? ` (${count} findings)` : ""}`}
    >
      {config?.icon}
      {isLarge && <span>{config?.label}</span>}
      {count != null && count > 0 && (
        <span className="ml-0.5 rounded-full bg-white/10 px-1 text-[9px]">{count}</span>
      )}
    </span>
  );
}
