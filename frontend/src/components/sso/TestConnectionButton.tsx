import { useState } from "react";
import { Loader2, CheckCircle2, XCircle, Wifi } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiPost } from "@/api/client";

interface TestConnectionButtonProps {
  tenantId: string;
  ssoId: string;
  disabled?: boolean;
}

export function TestConnectionButton({ tenantId, ssoId, disabled }: TestConnectionButtonProps) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ status: string; message: string } | null>(null);

  async function handleTest() {
    setTesting(true);
    setResult(null);
    try {
      const res = await apiPost<{ status: string; message: string; details?: Record<string, unknown> }>(
        `/tenants/${tenantId}/sso/${ssoId}/test`,
        {},
      );
      setResult(res.data);
    } catch {
      setResult({ status: "error", message: "Connection test failed." });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button
        size="sm"
        variant="outline"
        onClick={handleTest}
        disabled={disabled || testing}
      >
        {testing ? (
          <Loader2 size={14} className="mr-1.5 animate-spin" />
        ) : (
          <Wifi size={14} className="mr-1.5" />
        )}
        Test Connection
      </Button>
      {result && (
        <span
          className={`flex items-center gap-1.5 text-sm ${
            result.status === "success" ? "text-green-400" : "text-red-400"
          }`}
        >
          {result.status === "success" ? (
            <CheckCircle2 size={14} />
          ) : (
            <XCircle size={14} />
          )}
          {result.message}
        </span>
      )}
    </div>
  );
}
