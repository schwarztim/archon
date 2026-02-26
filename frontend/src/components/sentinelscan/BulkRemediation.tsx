import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface BulkRemediationProps {
  selectedCount: number;
  onApply: (action: string) => Promise<void>;
}

const ACTIONS = ["Block", "Approve", "Monitor", "Ignore"] as const;

export function BulkRemediation({ selectedCount, onApply }: BulkRemediationProps) {
  const [action, setAction] = useState<string>("");
  const [applying, setApplying] = useState(false);

  async function handleBulkApply() {
    if (!action || selectedCount === 0) return;
    setApplying(true);
    try {
      await onApply(action);
    } finally {
      setApplying(false);
      setAction("");
    }
  }

  if (selectedCount === 0) return null;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-purple-500/30 bg-purple-500/10 px-4 py-2">
      <span className="text-sm text-purple-300">
        {selectedCount} service{selectedCount > 1 ? "s" : ""} selected
      </span>
      <select
        className="rounded-md border border-surface-border bg-surface-base px-2 py-1 text-xs text-gray-200 focus:border-purple-500 focus:outline-none"
        value={action}
        onChange={(e) => setAction(e.target.value)}
      >
        <option value="">Select action…</option>
        {ACTIONS.map((a) => (
          <option key={a} value={a}>{a}</option>
        ))}
      </select>
      <Button
        size="sm"
        onClick={handleBulkApply}
        disabled={!action || applying}
        className="text-xs"
      >
        {applying ? <Loader2 size={12} className="mr-1 animate-spin" /> : null}
        Apply to All
      </Button>
    </div>
  );
}
