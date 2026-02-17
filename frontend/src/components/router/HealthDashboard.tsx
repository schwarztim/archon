import { useState, useEffect, useCallback } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
  getAllProviderHealthDetail,
  type ProviderHealthDetail,
} from "@/api/router";

/* ─── Constants ──────────────────────────────────────────────────── */

const STATUS_CONFIG: Record<
  string,
  { icon: typeof CheckCircle2; color: string; bgColor: string; label: string }
> = {
  healthy: {
    icon: CheckCircle2,
    color: "text-green-600 dark:text-green-400",
    bgColor: "bg-green-50 dark:bg-green-900/20",
    label: "Healthy",
  },
  degraded: {
    icon: AlertTriangle,
    color: "text-yellow-600 dark:text-yellow-400",
    bgColor: "bg-yellow-50 dark:bg-yellow-900/20",
    label: "Degraded",
  },
  unhealthy: {
    icon: XCircle,
    color: "text-red-600 dark:text-red-400",
    bgColor: "bg-red-50 dark:bg-red-900/20",
    label: "Unhealthy",
  },
  circuit_open: {
    icon: AlertTriangle,
    color: "text-orange-600 dark:text-orange-400",
    bgColor: "bg-orange-50 dark:bg-orange-900/20",
    label: "Circuit Open",
  },
};

const POLL_INTERVAL_MS = 30_000;

/* ─── Component ──────────────────────────────────────────────────── */

export default function HealthDashboard(): JSX.Element {
  const [healthData, setHealthData] = useState<ProviderHealthDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await getAllProviderHealthDetail();
      setHealthData(res.data);
      setError(null);
    } catch {
      setError("Failed to load health data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const timer = setInterval(fetchHealth, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchHealth]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground p-4" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading health data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-sm text-destructive p-4" role="alert">
        {error}
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchHealth}
          className="ml-2"
          aria-label="Retry loading health data"
        >
          <RefreshCw className="h-3 w-3" />
        </Button>
      </div>
    );
  }

  if (healthData.length === 0) {
    return (
      <div className="text-sm text-muted-foreground p-4" role="status">
        No providers registered. Add a provider to see health metrics.
      </div>
    );
  }

  return (
    <div
      className="space-y-4"
      role="region"
      aria-label="Provider health dashboard"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <Activity className="h-4 w-4" aria-hidden="true" />
          Provider Health
        </h3>
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchHealth}
          aria-label="Refresh health data"
        >
          <RefreshCw className="h-3 w-3" />
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {healthData.map((provider) => {
          const config = STATUS_CONFIG[provider.status] ?? STATUS_CONFIG.unhealthy;
          const StatusIcon = config.icon;

          return (
            <div
              key={provider.provider_id}
              className={`rounded-lg border p-4 ${config.bgColor} transition-colors`}
              role="article"
              aria-label={`${provider.provider_name} health status: ${config.label}`}
            >
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-medium text-foreground">
                  {provider.provider_name}
                </h4>
                <div className={`flex items-center gap-1 text-xs ${config.color}`}>
                  <StatusIcon className="h-3.5 w-3.5" aria-hidden="true" />
                  {config.label}
                </div>
              </div>

              {/* Latency metrics */}
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between text-muted-foreground">
                  <span>Avg Latency</span>
                  <span className="font-mono text-foreground">
                    {provider.metrics.avg_latency_ms}ms
                  </span>
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>P95 Latency</span>
                  <span className="font-mono text-foreground">
                    {provider.metrics.p95_latency_ms}ms
                  </span>
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>P99 Latency</span>
                  <span className="font-mono text-foreground">
                    {provider.metrics.p99_latency_ms}ms
                  </span>
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>Error Rate</span>
                  <span className="font-mono text-foreground">
                    {provider.metrics.error_rate_percent}%
                  </span>
                </div>
              </div>

              {/* Circuit breaker */}
              <div className="mt-3 pt-2 border-t border-border/50">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Circuit Breaker</span>
                  <span
                    className={`font-medium ${
                      provider.circuit_breaker.state === "closed"
                        ? "text-green-600 dark:text-green-400"
                        : provider.circuit_breaker.state === "half_open"
                          ? "text-yellow-600 dark:text-yellow-400"
                          : "text-red-600 dark:text-red-400"
                    }`}
                  >
                    {provider.circuit_breaker.state}
                  </span>
                </div>
                <div className="flex justify-between text-xs text-muted-foreground mt-1">
                  <span>Failures</span>
                  <span className="font-mono text-foreground">
                    {provider.circuit_breaker.failure_count}/{provider.circuit_breaker.threshold}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
