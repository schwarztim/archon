import { useState, useEffect } from "react";
import { X, Play, Loader2, Bot, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import { apiGet, apiPost } from "@/api/client";

interface Agent {
  id: string;
  name: string;
  status: string;
}

interface RunAgentDialogProps {
  onClose: () => void;
}

export function RunAgentDialog({ onClose }: RunAgentDialogProps) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [inputData, setInputData] = useState("{}");
  const [loading, setLoading] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await apiGet<Agent[]>("/agents/", { limit: 50 });
        const data = res.data;
        setAgents(Array.isArray(data) ? data : []);
        if (Array.isArray(data) && data.length > 0) {
          setSelectedAgentId(data[0].id);
        }
      } catch {
        setAgents([]);
      } finally {
        setLoadingAgents(false);
      }
    }
    void load();
  }, []);

  async function handleRun() {
    if (!selectedAgentId) return;
    setLoading(true);
    setError(null);
    try {
      let parsed: Record<string, unknown> = {};
      try {
        parsed = JSON.parse(inputData);
      } catch {
        setError("Invalid JSON input");
        setLoading(false);
        return;
      }
      await apiPost("/execute", { agent_id: selectedAgentId, input: parsed });
      setSuccess(true);
      setTimeout(onClose, 1500);
    } catch {
      setError("Failed to start execution");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-[#2a2d37] bg-[#1a1d27] shadow-xl">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <div className="flex items-center gap-2">
            <Play size={16} className="text-purple-400" />
            <h2 className="text-sm font-semibold text-white">Run Agent</h2>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={16} />
          </button>
        </div>
        <div className="p-4 space-y-4">
          {success ? (
            <div className="flex flex-col items-center py-8">
              <CheckCircle2 size={40} className="mb-2 text-green-400" />
              <p className="text-sm text-green-400">Execution started successfully!</p>
            </div>
          ) : (
            <>
              <div>
                <Label htmlFor="agent-select">Agent</Label>
                {loadingAgents ? (
                  <div className="flex items-center gap-2 py-2 text-gray-400">
                    <Loader2 size={14} className="animate-spin" />
                    <span className="text-xs">Loading agents…</span>
                  </div>
                ) : agents.length === 0 ? (
                  <div className="flex items-center gap-2 py-2">
                    <Bot size={14} className="text-gray-500" />
                    <span className="text-xs text-gray-500">No agents available</span>
                  </div>
                ) : (
                  <select
                    id="agent-select"
                    value={selectedAgentId}
                    onChange={(e) => setSelectedAgentId(e.target.value)}
                    className="mt-1 w-full rounded-md border border-[#2a2d37] bg-[#141620] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
                  >
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div>
                <Label htmlFor="input-data">Input Data (JSON)</Label>
                <Textarea
                  id="input-data"
                  value={inputData}
                  onChange={(e) => setInputData(e.target.value)}
                  rows={4}
                  className="mt-1 font-mono text-xs"
                  placeholder='{"key": "value"}'
                />
              </div>
              {error && (
                <p className="text-xs text-red-400">{error}</p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleRun}
                  disabled={loading || !selectedAgentId}
                  className="gap-2 bg-purple-600 hover:bg-purple-700"
                >
                  {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                  Run
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
