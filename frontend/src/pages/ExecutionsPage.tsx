import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Play, Loader2, ChevronDown, ChevronUp, X, Clock, Zap, DollarSign, CheckCircle2, Circle, AlertCircle, Trash2, RefreshCw } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listExecutions, createExecution, deleteExecution } from "@/api/executions";
import { listAgents } from "@/api/agents";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";

interface AgentSummary {
  id: string;
  name: string;
}

interface ExecutionStep {
  name?: string;
  step_name?: string;
  step_type?: string;
  status: string;
  duration_ms?: number;
  token_usage?: number;
  tokens?: number;
  cost?: number;
  input?: unknown;
  output?: unknown;
  error?: string | null;
}

interface ExecutionMetrics {
  duration_ms?: number;
  total_duration_ms?: number;
  total_tokens?: number;
  estimated_cost?: number;
  total_cost?: number;
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
  return `$${cost.toFixed(4)}`;
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

function getDuration(m: ExecutionMetrics | null): number | undefined {
  return m?.total_duration_ms ?? m?.duration_ms;
}

function getCost(m: ExecutionMetrics | null): number | undefined {
  return m?.total_cost ?? m?.estimated_cost;
}

// ── Run Agent Modal ──────────────────────────────────────────────────

function RunAgentModal({
  agents,
  onClose,
  onExecuted,
}: {
  agents: AgentSummary[];
  onClose: () => void;
  onExecuted: (executionId: string) => void;
}) {
  const [selectedAgentId, setSelectedAgentId] = useState(agents[0]?.id ?? "");
  const [inputText, setInputText] = useState('{\n  "prompt": "Hello"\n}');
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
              className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
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
              className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-purple-500"
            />
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleExecute} disabled={submitting || !selectedAgentId} className="bg-purple-600 hover:bg-purple-700 text-white">
            {submitting ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Play size={14} className="mr-1" />}
            Run
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Execution Detail Panel ───────────────────────────────────────────

function ExecutionDetail({ execution, agentName }: { execution: Execution; agentName: string }) {
  return (
    <td colSpan={8} className="px-6 py-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Summary */}
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase text-gray-500">Summary</h3>
          <div className="flex flex-wrap gap-4 text-xs">
            <span className="flex items-center gap-1 text-gray-400"><Clock size={12} /> {formatDuration(getDuration(execution.metrics))}</span>
            <span className="flex items-center gap-1 text-gray-400"><Zap size={12} /> {execution.metrics?.total_tokens ?? "—"} tokens</span>
            <span className="flex items-center gap-1 text-gray-400"><DollarSign size={12} /> {formatCost(getCost(execution.metrics))}</span>
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
                  <span className="text-gray-300 capitalize">{step.step_name ?? step.name}</span>
                  {step.step_type && <span className="rounded bg-gray-700/50 px-1 text-[10px] text-gray-500">{step.step_type}</span>}
                  {(step.token_usage ?? step.tokens) != null && <span className="text-gray-500">({step.token_usage ?? step.tokens} tokens)</span>}
                  {step.duration_ms != null && <span className="text-gray-500">{formatDuration(step.duration_ms)}</span>}
                  {step.cost != null && step.cost > 0 && <span className="text-gray-500">{formatCost(step.cost)}</span>}
                  {step.error && <span className="text-red-400 text-[10px]">{step.error}</span>}
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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [filterAgentId, setFilterAgentId] = useState<string>("");
  const [filterDateFrom, setFilterDateFrom] = useState<string>("");
  const [filterDateTo, setFilterDateTo] = useState<string>("");

  // Auto-refresh ref
  // ── Build filter params ──────────────────────────────────────────────
  const execParams: Record<string, string | undefined> = {};
  if (filterStatus) execParams.status = filterStatus;
  if (filterAgentId) execParams.agent_id = filterAgentId;

  // ── Queries ──────────────────────────────────────────────────────────
  const { data: executionsData, isLoading, error, refetch: refetchExecutions } = useQuery({
    queryKey: ["executions", execParams],
    queryFn: () => listExecutions(execParams),
  });

  const rawExecutions = Array.isArray(executionsData?.data) ? executionsData.data : [];
  const executions = rawExecutions.filter((e) => {
    if (filterDateFrom) {
      const from = new Date(filterDateFrom).getTime();
      if (new Date(e.created_at).getTime() < from) return false;
    }
    if (filterDateTo) {
      const to = new Date(filterDateTo).getTime() + 86400000;
      if (new Date(e.created_at).getTime() > to) return false;
    }
    return true;
  });

  const { data: agentsData } = useQuery({
    queryKey: ["agents-list"],
    queryFn: () => listAgents(100, 0),
  });
  const agentsList = Array.isArray(agentsData?.data) ? agentsData.data : [];
  const agents: AgentSummary[] = agentsList.map((a: { id: string; name: string }) => ({ id: a.id, name: a.name }));
  const agentMap: Record<string, string> = {};
  for (const a of agents) agentMap[a.id] = a.name;

  // ── Auto-refresh when any execution is running ───────────────────────
  const hasRunning = executions.some((e) => e.status === "running" || e.status === "pending");
  useEffect(() => {
    if (!hasRunning) return;
    const id = setInterval(() => { void refetchExecutions(); }, 10000);
    return () => clearInterval(id);
  }, [hasRunning, refetchExecutions]);

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selectedIds.size === executions.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(executions.map((e) => e.id)));
    }
  }

  async function handleBulkDelete() {
    const ids = Array.from(selectedIds);
    for (const id of ids) {
      try { await deleteExecution(id); } catch { /* ignore */ }
    }
    setSelectedIds(new Set());
    void queryClient.invalidateQueries({ queryKey: ["executions"] });
  }

  function handleRunExecuted(executionId: string) {
    navigate(`/executions/${executionId}`);
  }

  if (isLoading && executions.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="animate-spin text-gray-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">Failed to load executions.</div>
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
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => void refetchExecutions()} className="text-gray-400 hover:text-white">
            <RefreshCw size={14} className="mr-1" /> Refresh
          </Button>
          {selectedIds.size > 0 && (
            <Button variant="ghost" size="sm" onClick={handleBulkDelete} className="text-red-400 hover:text-red-300">
              <Trash2 size={14} className="mr-1" /> Delete ({selectedIds.size})
            </Button>
          )}
          <Button size="sm" onClick={() => setShowRunModal(true)} className="bg-purple-600 hover:bg-purple-700 text-white">
            <Play size={14} className="mr-1" /> Run Agent
          </Button>
        </div>
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
          <option value="pending">Pending</option>
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
        <input
          type="date"
          value={filterDateFrom}
          onChange={(e) => setFilterDateFrom(e.target.value)}
          placeholder="From"
          className="rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-purple-500"
        />
        <input
          type="date"
          value={filterDateTo}
          onChange={(e) => setFilterDateTo(e.target.value)}
          placeholder="To"
          className="rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-purple-500"
        />
        {(filterStatus || filterAgentId || filterDateFrom || filterDateTo) && (
          <button
            onClick={() => { setFilterStatus(""); setFilterAgentId(""); setFilterDateFrom(""); setFilterDateTo(""); }}
            className="text-xs text-gray-500 hover:text-white"
          >
            Clear filters
          </button>
        )}
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
                  <th className="w-8 px-4 py-2">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === executions.length && executions.length > 0}
                      onChange={toggleSelectAll}
                      className="rounded border-gray-600"
                    />
                  </th>
                  <th className="w-5 px-2 py-2 font-medium" />
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
                      onDoubleClick={() => navigate(`/executions/${e.id}`)}
                    >
                      <td className="px-4 py-2" onClick={(ev) => ev.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(e.id)}
                          onChange={() => toggleSelect(e.id)}
                          className="rounded border-gray-600"
                        />
                      </td>
                      <td className="px-2 py-2 text-gray-500">{expandedId === e.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-400">{truncateId(e.id)}</td>
                      <td className="px-4 py-2 font-medium text-white">{agentMap[e.agent_id] ?? truncateId(e.agent_id)}</td>
                      <td className="px-4 py-2">{statusBadge(e.status)}</td>
                      <td className="px-4 py-2 text-gray-400">{formatDuration(getDuration(e.metrics))}</td>
                      <td className="px-4 py-2 text-gray-400">{formatCost(getCost(e.metrics))}</td>
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
          onExecuted={handleRunExecuted}
        />
      )}
    </div>
  );
}
