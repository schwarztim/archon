import { useState } from "react";
import { Loader2, Wifi, CheckCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface TestConnectionButtonProps {
  onTest: () => Promise<{ success: boolean; message: string }>;
  className?: string;
}

export function TestConnectionButton({ onTest, className = "" }: TestConnectionButtonProps) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  async function handleTest() {
    setTesting(true);
    setResult(null);
    try {
      const res = await onTest();
      setResult(res);
    } catch {
      setResult({ success: false, message: "Connection test failed" });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className={className}>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleTest}
        disabled={testing}
        className="border-gray-600 dark:border-gray-600"
      >
        {testing ? (
          <Loader2 size={14} className="mr-1.5 animate-spin" />
        ) : (
          <Wifi size={14} className="mr-1.5" />
        )}
        Test Connection
      </Button>
      {result && (
        <div
          className={`mt-2 flex items-center gap-2 rounded-md border p-2.5 text-sm ${
            result.success
              ? "border-green-500/30 bg-green-500/10 text-green-400 dark:text-green-400"
              : "border-red-500/30 bg-red-500/10 text-red-400 dark:text-red-400"
          }`}
        >
          {result.success ? <CheckCircle size={14} /> : <XCircle size={14} />}
          {result.message}
        </div>
      )}
    </div>
  );
}
