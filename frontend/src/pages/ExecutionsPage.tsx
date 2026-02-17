import { useState, useEffect, useCallback } from "react";
import { Play, Loader2, ChevronDown, ChevronUp, X, Clock, Zap, DollarSign, CheckCircle2, Circle, AlertCircle } from "lucide-react";
import { apiGet } from "@/api/client";
import { executeAgent, listExecutions } from "@/api/executions";
import { listAgents } from "@/api/agents";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import type { ExecutionStatus as ExecStatus } from "@/types/models";

interface AgentSummary {
  id: string;
  name: string;
}

interface ExecutionStep {
  name: string;
  status: string;
  tokens?: number;
}

interface ExecutionMetrics {
  duration_ms?: number;
  total_tokens?: number;
  estimated_cost?: number;
}

interface Execution {
  id: string;
  agent_id: string;
  status: string;
  input_data: unknown;
  output_data: unknown;
  error: string | null;
  steps: ExecutionStep[] | null;
  metrics: ExecutionMetrics | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

// ── Helpers ──────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-gray-500/20 text-gray-400",
  pending: "bg-gray-500/20 text-gray-400",
  running: "bg-blue-500/20 text-blue-400",
  completed: "bg-green-500/20 text-green-400",
  failed: "bg-red-500/20 text-red-400",
  cancelled: "bg-yellow-500/20 text-yellow-400",
};

function statusBadge(status: string) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status] ?? "bg-gray-500/20 text-gray-400"}`}>
      {status === "running" && <Loader2 size={10} className="animate-spin" />}
      {status}
    </span>
  );
}

function formatDuration(ms: number | undefined | null) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatCost(cost: number | undefined | null) {
  if (cost == null) return "—";
  return `$${cost.toFixed(6)}`;
}

function truncateId(id: string) {
  return id.slice(0, 8);
}

function stepIcon(status: string) {
  if (status === "completed") return <CheckCircle2 size={14} className="text-green-400" />;
  if (status === "running") return <Loader2 size={14} className="animate-spin text-blue-400" />;
  if (status === "failed") return <AlertCircle size={14} className="text-red-400" />;
  return <Circle size={14} className="text-gray-500" />;
}

// ── Run Agent Modal ──────────────────────────────────────────────────

function RunAgentModal({
  agents,
  onClose,
  onExecuted,
}: {
  agents: AgentSummary[];
  onClose: () => void;
  onExecuted: () => void;
}) {
  const [selectedAgentId, setSelectedAgentId] = useState(agents[0]?.id ?? "");
  const [inputText, setInputText] = useState('{\n  "prompt": "Hello"\n}');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleExecute() {
    if (!selectedAgentId) return;
    setSubmitting(true);
    setError(null);
    try {
      const parsed = JSON.parse(inputText);
      await executeAgent(selectedAgentId, parsed);
      onExecuted();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof SyntaxError ? "Invalid JSON input" : "Execution failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-lg rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Run Agent</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white"><X size={18} /></button>
        </div>

        <div className="mb-4">
          <Label className="mb-1 text-gray-300">Agent</Label>
          <select
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>

        <div className="mb-4">
          <Label className="mb-1 text-gray-300">Input Data (JSON)</Label>
          <Textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            rows={6}
            className="border-[#2a2d37] bg-[#0f1117] font-mono text-sm text-gray-200"
          />
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleExecute} disabled={submitting || !selectedAgentId} className="bg-purple-600 hover:bg-purple-700 text-white">
            {submitting ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Play size={14} className="mr-1" />}
            Execute
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Execution Detail Panel ───────────────────────────────────────────

function ExecutionDetail({ execution, agentName }: { execution: Execution; agentName: string }) {
  return (
    <td colSpan={7} className="px-6 py-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Summary */}
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase text-gray-500">Summary</h3>
          <div className="flex flex-wrap gap-4 text-xs">
            <span className="flex items-center gap-1 text-gray-400"><Clock size={12} /> {formatDuration(execution.metrics?.duration_ms)}</span>
            <span className="flex items-center gap-1 text-gray-400"><Zap size={12} /> {execution.metrics?.total_tokens ?? "—"} tokens</span>
            <span className="flex items-center gap-1 text-gray-400"><DollarSign size={12} /> {formatCost(execution.metrics?.estimated_cost)}</span>
          </div>
          <div className="text-xs text-gray-500">Agent: <span className="text-gray-300">{agentName}</span></div>
          <div className="text-xs text-gray-500">Execution ID: <span className="text-gray-300 font-mono">{execution.id}</span></div>
        </div>

        {/* Step Timeline */}
        {execution.steps && execution.steps.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase text-gray-500">Step Timeline</h3>
            <div className="space-y-1">
              {execution.steps.map((step, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  {stepIcon(step.status)}
                  <span className="text-gray-300 capitalize">{step.name}</span>
                  {step.tokens != null && <span className="text-gray-500">({step.tokens} tokens)</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Input */}
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-gray-500">Input Data</h3>
          <pre className="max-h-40 overflow-auto rounded bg-black/30 p-2 text-xs text-gray-300">{JSON.stringify(execution.input_data, null, 2)}</pre>
        </div>

        {/* Output / Error */}
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-gray-500">Output / Error</h3>
          <pre className="max-h-40 overflow-auto rounded bg-black/30 p-2 text-xs text-gray-300">
            {execution.output_data ? JSON.stringify(execution.output_data, null, 2) : execution.error ?? "—"}
          </pre>
        </div>
      </div>
    </td>
  );
}

// ── Main Page ────────────────────────────────────────────────────────

export function ExecutionsPage() {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [agentMap, setAgentMap] = useState<Record<string, string>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRunModal, setShowRunModal] = useState(false);

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [filterAgentId, setFilterAgentId] = useState<string>("");

  const fetchExecutions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | undefined> = {};
      if (filterStatus) params.status = filterStatus;
      if (filterAgentId) params.agent_id = filterAgentId;
      const res = await listExecutions(params);
      setExecutions(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load executions.");
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterAgentId]);

  const fetchAgents = useCallback(async () => {
    try {
      const res = await listAgents(100, 0);
      const list = Array.isArray(res.data) ? res.data : [];
      const summaries: AgentSummary[] = list.map((a: { id: string; name: string }) => ({ id: a.id, name: a.name }));
      setAgents(summaries);
      const map: Record<string, string> = {};
      for (const a of summaries) map[a.id] = a.name;
      setAgentMap(map);
    } catch {
      // Non-critical — agent names just won't show
    }
  }, []);

  useEffect(() => { void fetchAgents(); }, [fetchAgents]);
  useEffect(() => { void fetchExecutions(); }, [fetchExecutions]);

  if (loading && executions.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="animate-spin text-gray-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Play size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Executions</h1>
        </div>
        <Button size="sm" onClick={() => setShowRunModal(true)} className="bg-purple-600 hover:bg-purple-700 text-white">
          <Play size={14} className="mr-1" /> Run Agent
        </Button>
      </div>
      <p className="mb-4 text-gray-400">Monitor and manage real-time and historical agent execution runs.</p>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-purple-500"
        >
          <option value="">All Statuses</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <select
          value={filterAgentId}
          onChange={(e) => setFilterAgentId(e.target.value)}
          className="rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-purple-500"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="overflow-x-auto">
          {executions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Play size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No executions yet. Click &quot;Run Agent&quot; to start one.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="w-5 px-4 py-2 font-medium" />
                  <th className="px-4 py-2 font-medium">ID</th>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Duration</th>
                  <th className="px-4 py-2 font-medium">Cost</th>
                  <th className="px-4 py-2 font-medium text-right">Created</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((e) => (
                  <>
                    <tr
                      key={e.id}
                      className="border-b border-[#2a2d37] hover:bg-white/5 cursor-pointer"
                      onClick={() => setExpandedId(expandedId === e.id ? null : e.id)}
                    >
                      <td className="px-4 py-2 text-gray-500">{expandedId === e.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-400">{truncateId(e.id)}</td>
                      <td className="px-4 py-2 font-medium text-white">{agentMap[e.agent_id] ?? truncateId(e.agent_id)}</td>
                      <td className="px-4 py-2">{statusBadge(e.status)}</td>
                      <td className="px-4 py-2 text-gray-400">{formatDuration(e.metrics?.duration_ms)}</td>
                      <td className="px-4 py-2 text-gray-400">{formatCost(e.metrics?.estimated_cost)}</td>
                      <td className="px-4 py-2 text-right text-gray-400">{new Date(e.created_at).toLocaleString()}</td>
                    </tr>
                    {expandedId === e.id && (
                      <tr key={`${e.id}-detail`} className="border-b border-[#2a2d37] bg-[#0f1117]">
                        <ExecutionDetail execution={e} agentName={agentMap[e.agent_id] ?? e.agent_id} />
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Run Agent Modal */}
      {showRunModal && (
        <RunAgentModal
          agents={agents}
          onClose={() => setShowRunModal(false)}
          onExecuted={() => void fetchExecutions()}
        />
      )}
    </div>
  );
}
