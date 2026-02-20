import { useState, useEffect, useCallback } from "react";
import type { VaultStatus } from "@/api/secrets";
import { getVaultStatus } from "@/api/secrets";

const MODE_STYLES: Record<
  string,
  { bg: string; text: string; icon: string; borderColor: string }
> = {
  connected: {
    bg: "bg-green-50 dark:bg-green-950",
    text: "text-green-800 dark:text-green-200",
    icon: "🟢",
    borderColor: "border-green-200 dark:border-green-800",
  },
  stub: {
    bg: "bg-yellow-50 dark:bg-yellow-950",
    text: "text-yellow-800 dark:text-yellow-200",
    icon: "⚠️",
    borderColor: "border-yellow-200 dark:border-yellow-800",
  },
  sealed: {
    bg: "bg-red-50 dark:bg-red-950",
    text: "text-red-800 dark:text-red-200",
    icon: "🔴",
    borderColor: "border-red-200 dark:border-red-800",
  },
  disconnected: {
    bg: "bg-red-50 dark:bg-red-950",
    text: "text-red-800 dark:text-red-200",
    icon: "🔴",
    borderColor: "border-red-200 dark:border-red-800",
  },
};

export default function VaultStatusBanner() {
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getVaultStatus();
      setStatus(res.data);
    } catch {
      setStatus({
        mode: "disconnected",
        initialized: false,
        sealed: false,
        cluster_name: "",
        message: "Unable to reach secrets backend.",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  if (loading) return null;
  if (!status) return null;

  const style = MODE_STYLES[status.mode] ?? MODE_STYLES.disconnected;

  return (
    <div
      className={`flex items-center gap-3 rounded-lg border p-3 ${style?.bg} ${style?.borderColor}`}
      role="status"
      aria-label={`Vault status: ${status.mode}`}
    >
      <span className="text-lg">{style?.icon}</span>
      <div className="flex-1">
        <span className={`text-sm font-semibold ${style?.text}`}>
          Vault: {status.mode.charAt(0).toUpperCase() + status.mode.slice(1)}
        </span>
        {status.cluster_name && (
          <span className="ml-2 text-xs text-muted-foreground">
            ({status.cluster_name})
          </span>
        )}
        <p className={`text-xs ${style?.text} mt-0.5`}>{status.message}</p>
      </div>
      <button
        onClick={fetchStatus}
        className="rounded px-2 py-1 text-xs bg-background/50 hover:bg-background/80 transition-colors"
        aria-label="Refresh Vault status"
      >
        Refresh
      </button>
    </div>
  );
}
