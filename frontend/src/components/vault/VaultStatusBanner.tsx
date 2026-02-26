import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getVaultStatus } from "@/api/secrets";
import type { VaultStatus } from "@/api/secrets";

// ── Styles per vault mode ────────────────────────────────────────────

type VaultMode = VaultStatus["mode"];

interface ModeStyle {
  bg: string;
  text: string;
  icon: string;
  borderColor: string;
}

const MODE_STYLES: Record<VaultMode, ModeStyle> = {
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

const DISCONNECTED_FALLBACK: VaultStatus = {
  mode: "disconnected",
  initialized: false,
  sealed: false,
  cluster_name: "",
  message: "Unable to reach secrets backend.",
};

// ── Component ────────────────────────────────────────────────────────

export default function VaultStatusBanner() {
  const queryClient = useQueryClient();

  const { data: status, isLoading } = useQuery<VaultStatus>({
    queryKey: ["vault", "status"],
    queryFn: async () => {
      const res = await getVaultStatus();
      return res.data;
    },
    // Retry silently and fall back to disconnected on permanent error
    retry: 1,
    retryDelay: 1000,
    staleTime: 30_000,
    // On error, the query returns undefined — we show the disconnected fallback
  });

  function handleRefresh() {
    void queryClient.invalidateQueries({ queryKey: ["vault", "status"] });
  }

  // Don't render while loading to avoid flash
  if (isLoading) return null;

  const resolved: VaultStatus = status ?? DISCONNECTED_FALLBACK;
  const style: ModeStyle = MODE_STYLES[resolved.mode] ?? MODE_STYLES.disconnected;

  return (
    <div
      className={`flex items-center gap-3 rounded-lg border p-3 ${style.bg} ${style.borderColor}`}
      role="status"
      aria-label={`Vault status: ${resolved.mode}`}
    >
      <span className="text-lg" aria-hidden="true">
        {style.icon}
      </span>
      <div className="flex-1 min-w-0">
        <span className={`text-sm font-semibold ${style.text}`}>
          Vault:{" "}
          {resolved.mode.charAt(0).toUpperCase() + resolved.mode.slice(1)}
        </span>
        {resolved.cluster_name && (
          <span className="ml-2 text-xs text-muted-foreground">
            ({resolved.cluster_name})
          </span>
        )}
        <p className={`text-xs mt-0.5 ${style.text}`}>{resolved.message}</p>
      </div>
      <button
        type="button"
        onClick={handleRefresh}
        className="shrink-0 rounded px-2 py-1 text-xs bg-background/50 hover:bg-background/80 transition-colors"
        aria-label="Refresh Vault status"
      >
        Refresh
      </button>
    </div>
  );
}
