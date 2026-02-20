import { useState, useCallback } from "react";
import { Wifi, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { testConnection, type TestConnectionResult } from "@/api/router";

/* ─── Types ──────────────────────────────────────────────────────── */

interface TestConnectionButtonProps {
  providerId: string;
  disabled?: boolean;
}

/* ─── Component ──────────────────────────────────────────────────── */

export default function TestConnectionButton({
  providerId,
  disabled = false,
}: TestConnectionButtonProps) {
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [result, setResult] = useState<TestConnectionResult | null>(null);

  const handleTest = useCallback(async () => {
    setStatus("loading");
    setResult(null);
    try {
      const res = await testConnection(providerId);
      setResult(res.data);
      setStatus(res.data.success ? "success" : "error");
    } catch {
      setResult({
        success: false,
        latency_ms: 0,
        models_found: 0,
        message: "Connection test failed unexpectedly.",
        error: "Request failed",
      });
      setStatus("error");
    }
  }, [providerId]);

  return (
    <div className="space-y-2">
      <Button
        onClick={handleTest}
        disabled={disabled || status === "loading"}
        variant="outline"
        size="sm"
        aria-label="Test connection"
        className="gap-2"
      >
        {status === "loading" ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Wifi className="h-4 w-4" aria-hidden="true" />
        )}
        {status === "loading" ? "Testing…" : "Test Connection"}
      </Button>

      {status === "success" && result && (
        <div
          className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400 rounded-md bg-green-50 dark:bg-green-900/20 px-3 py-2"
          role="status"
          aria-label="Connection successful"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">{result.message}</p>
            <p className="text-xs text-muted-foreground">
              Latency: {result.latency_ms}ms
              {result.models_found > 0 && ` • ${result.models_found} models found`}
            </p>
          </div>
        </div>
      )}

      {status === "error" && result && (
        <div
          className="flex items-center gap-2 text-sm text-destructive rounded-md bg-red-50 dark:bg-red-900/20 px-3 py-2"
          role="alert"
          aria-label="Connection failed"
        >
          <XCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">{result.message}</p>
            {result.error && (
              <p className="text-xs text-muted-foreground">{result.error}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
