import { useState, useEffect, useCallback } from "react";
import {
  Server,
  Loader2,
  RefreshCw,
  Activity,
  Database,
  HardDrive,
  Lock,
  Shield,
} from "lucide-react";
import { Button } from "@/components/ui/Button";

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        ok ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-green-400" : "bg-red-400"}`} />
      {label}
    </span>
  );
}

interface HealthData {
  status: string;
  version?: string;
  services?: Record<string, string>;
  timestamp?: string;
}

export function SystemHealthTab() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/health", { credentials: "include" });
      if (res.ok) {
        setHealth(await res.json());
      } else {
        setError(`Health check failed: HTTP ${res.status}`);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchHealth();
  }, [fetchHealth]);

  const serviceIcons: Record<string, React.ElementType> = {
    api: Activity,
    database: Database,
    redis: HardDrive,
    vault: Lock,
    keycloak: Shield,
  };

  const services = health?.services || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-400">Service Status</h3>
        <Button variant="ghost" size="sm" onClick={() => void fetchHealth()} disabled={loading}>
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          <span className="ml-1.5">Refresh</span>
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={14} className="animate-spin" /> Checking service health…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
          {error}
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(services).map(([name, status]) => {
              const Icon = serviceIcons[name] || Server;
              const ok = status === "up" || status === "connected";
              return (
                <div
                  key={name}
                  className="flex items-center justify-between rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4"
                >
                  <div className="flex items-center gap-3">
                    <Icon size={16} className="text-purple-400" />
                    <span className="text-sm font-medium capitalize">{name}</span>
                  </div>
                  <StatusBadge ok={ok} label={status} />
                </div>
              );
            })}
          </div>

          {health?.version && (
            <div className="flex gap-4 text-sm text-gray-400">
              <span>Version: <code className="font-mono">{health.version}</code></span>
              {health.timestamp && (
                <span>Checked: {new Date(health.timestamp).toLocaleString()}</span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
