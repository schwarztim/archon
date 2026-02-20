import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Clock,
  Zap,
  DollarSign,
  Loader2,
  Play,
  Trash2,
  RotateCcw,
  Copy,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import {
  getExecution,
  replayExecution,
  deleteExecution,
  connectExecutionWebSocket,
  type ExecutionEvent,
} from "@/api/executions";
import { listAgents } from "@/api/agents";
import { Button } from "@/components/ui/Button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { StepTimeline, type StepData } from "@/components/executions/StepTimeline";
import { ExecutionGraph } from "@/components/executions/ExecutionGraph";
import { RunAgentDialog } from "@/components/executions/RunAgentDialog";
import type { Execution } from "@/types/models";

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
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium capitalize ${STATUS_STYLES[status] ?? "bg-gray-500/20 text-gray-400"}`}>
      {status === "running" && <Loader2 size={12} className="animate-spin" />}
      {status === "completed" && <CheckCircle2 size={12} />}
      {status === "failed" && <AlertCircle size={12} />}
      {status}
    </span>
  );
}

function formatDuration(ms: number | undefined | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatCost(cost: number | undefined | null): string {
  if (cost == null) return "—";
  return `$${cost.toFixed(4)}`;
}

function getDuration(m: Execution["metrics"]): number | undefined {
  if (!m) return undefined;
  return (m as Record<string, unknown>).total_duration_ms as number | undefined ?? m.duration_ms;
}

function getCost(m: Execution["metrics"]): number | undefined {
  if (!m) return undefined;
  return (m as Record<string, unknown>).total_cost as number | undefined ?? m.estimated_cost;
}

interface AgentSummary {
  id: string;
  name: string;
}

// ── Main Component ──────────────────────────────────────────────────

export function ExecutionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [execution, setExecution] = useState<(Execution & { agent_name?: string }) | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("timeline");
  const [copied, setCopied] = useState(false);
  const [showRerunDialog, setShowRerunDialog] = useState(false);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [rerunning, setRerunning] = useState(false);

  // WS events for real-time updates
  const [wsEvents, setWsEvents] = useState<ExecutionEvent[]>([]);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  const fetchExecution = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getExecution(id);
      setExecution(res.data);
    } catch {
      setError("Failed to load execution.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchAgents = useCallback(async () => {
    try {
      const res = await listAgents(100, 0);
      const list = Array.isArray(res.data) ? res.data : [];
      setAgents(list.map((a: { id: string; name: string }) => ({ id: a.id, name: a.name })));
    } catch {
      // Non-critical
    }
  }, []);

  useEffect(() => {
    void fetchExecution();
    void fetchAgents();
  }, [fetchExecution, fetchAgents]);

  // WebSocket auto-connect for running executions
  useEffect(() => {
    if (!id || !execution) return;
    if (execution.status !== "running" && execution.status !== "pending") return;

    const cleanup = connectExecutionWebSocket(
      id,
      (event) => {
        setWsEvents((prev) => [...prev, event]);

        // Auto-refresh on completion events
        if (event.type === "execution.completed" || event.type === "execution.failed") {
          void fetchExecution();
        }
      },
      () => {
        // Connection closed — refresh to get final state
        void fetchExecution();
      },
    );

    wsCleanupRef.current = cleanup;
    return () => cleanup();
  }, [id, execution?.status, fetchExecution]);

  async function handleDelete() {
    if (!id) return;
    setDeleting(true);
    try {
      await deleteExecution(id);
      navigate("/executions");
    } catch {
      setError("Failed to delete execution.");
    } finally {
      setDeleting(false);
    }
  }

  async function handleRerun() {
    if (!id) return;
    setRerunning(true);
    try {
      const res = await replayExecution(id);
      navigate(`/executions/${res.data.id}`);
    } catch {
      setError("Failed to re-run execution.");
    } finally {
      setRerunning(false);
    }
  }

  function handleCopyJson() {
    if (!execution) return;
    navigator.clipboard.writeText(JSON.stringify(execution, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="animate-spin text-gray-400" />
      </div>
    );
  }

  if (error || !execution) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          {error ?? "Execution not found"}
        </div>
        <Button variant="ghost" size="sm" className="mt-4" onClick={() => navigate("/executions")}>
          <ArrowLeft size={14} className="mr-1" /> Back to Executions
        </Button>
      </div>
    );
  }

  const steps: StepData[] = (execution.steps ?? []).map((s) => ({
    step_name: s.step_name ?? s.name,
    step_type: s.step_type,
    status: s.status,
    duration_ms: s.duration_ms,
    token_usage: s.token_usage ?? s.tokens,
    cost: s.cost,
    input: s.input as Record<string, unknown> | undefined,
    output: s.output as Record<string, unknown> | undefined,
    error: s.error,
  }));

  return (
    <div className="p-6">
      {/* Back button */}
      <Button variant="ghost" size="sm" className="mb-4 text-gray-400" onClick={() => navigate("/executions")}>
        <ArrowLeft size={14} className="mr-1" /> Executions
      </Button>

      {/* Header */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-xl font-bold text-white">
              {execution.agent_name ?? "Execution"}
            </h1>
            <p className="text-xs text-gray-500 font-mono">{execution.id}</p>
          </div>
          {statusBadge(execution.status)}
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRerun}
            disabled={rerunning}
            className="text-gray-400 hover:text-white"
          >
            {rerunning ? <Loader2 size={14} className="mr-1 animate-spin" /> : <RotateCcw size={14} className="mr-1" />}
            Re-run
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowRerunDialog(true)}
            className="text-gray-400 hover:text-white"
          >
            <Play size={14} className="mr-1" /> Run with changes
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDelete}
            disabled={deleting}
            className="text-red-400 hover:text-red-300"
          >
            {deleting ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Trash2 size={14} className="mr-1" />}
            Delete
          </Button>
        </div>
      </div>

      {/* Metrics summary */}
      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Clock size={12} /> Duration
          </div>
          <div className="mt-1 text-lg font-bold text-white">{formatDuration(getDuration(execution.metrics))}</div>
        </div>
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Zap size={12} /> Tokens
          </div>
          <div className="mt-1 text-lg font-bold text-white">{execution.metrics?.total_tokens ?? "—"}</div>
        </div>
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <DollarSign size={12} /> Cost
          </div>
          <div className="mt-1 text-lg font-bold text-white">{formatCost(getCost(execution.metrics))}</div>
        </div>
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            Steps
          </div>
          <div className="mt-1 text-lg font-bold text-white">
            {steps.length}
            {steps.some((s) => s.status === "failed") && (
              <span className="ml-2 text-sm text-red-400">
                ({steps.filter((s) => s.status === "failed").length} failed)
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Error banner */}
      {execution.error && (
        <div className="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          <div className="mb-1 text-xs font-semibold uppercase">Error</div>
          {execution.error}
        </div>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="bg-[#1a1d27] border border-[#2a2d37]">
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="graph">Graph View</TabsTrigger>
          <TabsTrigger value="raw">Raw Data</TabsTrigger>
        </TabsList>

        <TabsContent value="timeline">
          <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6">
            <StepTimeline steps={steps} />
          </div>
        </TabsContent>

        <TabsContent value="graph">
          <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] overflow-hidden">
            <ExecutionGraph steps={steps} />
          </div>
        </TabsContent>

        <TabsContent value="raw">
          <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-400">Full Execution Data</h3>
              <Button variant="ghost" size="sm" onClick={handleCopyJson} className="text-gray-400">
                {copied ? <CheckCircle2 size={14} className="mr-1 text-green-400" /> : <Copy size={14} className="mr-1" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <pre className="max-h-[600px] overflow-auto rounded bg-black/30 p-4 text-xs text-gray-300 font-mono">
              {JSON.stringify(execution, null, 2)}
            </pre>
          </div>
        </TabsContent>
      </Tabs>

      {/* WebSocket events log */}
      {wsEvents.length > 0 && (
        <div className="mt-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase text-gray-500">Real-time Events</h3>
          <div className="max-h-40 overflow-auto space-y-1">
            {wsEvents.map((ev, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-gray-500">{new Date(ev.timestamp).toLocaleTimeString()}</span>
                <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-purple-400">{ev.type}</span>
                <span className="text-gray-400 truncate">{JSON.stringify(ev.data)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Re-run dialog */}
      {showRerunDialog && (
        <RunAgentDialog
          agents={agents}
          onClose={() => setShowRerunDialog(false)}
          onExecuted={(newId) => navigate(`/executions/${newId}`)}
          prefillAgentId={execution.agent_id}
          prefillInput={execution.input_data as Record<string, unknown>}
        />
      )}
    </div>
  );
}
