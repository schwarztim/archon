import { useState } from "react";
import { Play, Loader2, X } from "lucide-react";
import { createExecution } from "@/api/executions";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";

interface AgentSummary {
  id: string;
  name: string;
}

interface RunAgentDialogProps {
  agents: AgentSummary[];
  onClose: () => void;
  onExecuted: (executionId: string) => void;
  prefillAgentId?: string;
  prefillInput?: Record<string, unknown>;
}

export function RunAgentDialog({
  agents,
  onClose,
  onExecuted,
  prefillAgentId,
  prefillInput,
}: RunAgentDialogProps) {
  const [selectedAgentId, setSelectedAgentId] = useState(prefillAgentId ?? agents[0]?.id ?? "");
  const [inputText, setInputText] = useState(
    prefillInput ? JSON.stringify(prefillInput, null, 2) : '{\n  "prompt": "Hello"\n}',
  );
  const [temperature, setTemperature] = useState("0.7");
  const [maxTokens, setMaxTokens] = useState("1024");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleExecute() {
    if (!selectedAgentId) return;
    setSubmitting(true);
    setError(null);
    try {
      const parsed = JSON.parse(inputText);
      const configOverrides: Record<string, unknown> = {};
      if (temperature) configOverrides.temperature = parseFloat(temperature);
      if (maxTokens) configOverrides.max_tokens = parseInt(maxTokens, 10);

      const res = await createExecution({
        agent_id: selectedAgentId,
        input_data: parsed,
        config_overrides: Object.keys(configOverrides).length > 0 ? configOverrides : undefined,
      });
      onExecuted(res.data.id);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof SyntaxError ? "Invalid JSON input" : "Execution failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-lg rounded-lg border border-surface-border bg-surface-raised p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Run Agent</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={18} />
          </button>
        </div>

        <div className="mb-4">
          <Label className="mb-1 text-gray-300">Agent</Label>
          <select
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            className="w-full rounded-md border border-surface-border bg-surface-base px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>

        <div className="mb-4">
          <Label className="mb-1 text-gray-300">Input Data (JSON)</Label>
          <Textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            rows={6}
            className="border-surface-border bg-surface-base font-mono text-sm text-gray-200"
          />
        </div>

        <div className="mb-4 grid grid-cols-2 gap-3">
          <div>
            <Label className="mb-1 text-gray-300">Temperature</Label>
            <input
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface-base px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            />
          </div>
          <div>
            <Label className="mb-1 text-gray-300">Max Tokens</Label>
            <input
              type="number"
              min="1"
              max="128000"
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface-base px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            />
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleExecute}
            disabled={submitting || !selectedAgentId}
            className="bg-purple-600 hover:bg-purple-700 text-white"
          >
            {submitting ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Play size={14} className="mr-1" />
            )}
            Run
          </Button>
        </div>
      </div>
    </div>
  );
}
