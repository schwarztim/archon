import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { ServiceFinding } from "@/api/sentinelscan";

interface RemediationPanelProps {
  service: ServiceFinding;
  onApply: (findingId: string, action: string) => Promise<void>;
}

const ACTIONS = ["Block", "Approve", "Monitor", "Ignore"] as const;

export function RemediationPanel({ service, onApply }: RemediationPanelProps) {
  const [selectedAction, setSelectedAction] = useState<string>("");
  const [applying, setApplying] = useState(false);

  async function handleApply() {
    if (!selectedAction) return;
    setApplying(true);
    try {
      await onApply(service.id, selectedAction);
    } finally {
      setApplying(false);
      setSelectedAction("");
    }
  }

  return (
    <div className="flex items-center gap-2">
      <select
        className="rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 py-1 text-xs text-gray-200 focus:border-purple-500 focus:outline-none"
        value={selectedAction}
        onChange={(e) => setSelectedAction(e.target.value)}
      >
        <option value="">Select action…</option>
        {ACTIONS.map((a) => (
          <option key={a} value={a}>{a}</option>
        ))}
      </select>
      <Button
        size="sm"
        onClick={handleApply}
        disabled={!selectedAction || applying}
        className="text-xs px-2 py-1"
      >
        {applying ? <Loader2 size={12} className="animate-spin" /> : "Apply"}
      </Button>
    </div>
  );
}
