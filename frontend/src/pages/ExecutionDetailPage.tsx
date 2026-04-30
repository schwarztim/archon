/**
 * ExecutionDetailPage
 *
 * Phase 7 / WS14 — top-level page for a single canonical run.
 *
 * Layout
 *  1. Run summary card (id, status, started/completed, duration, tenant, kind)
 *  2. Cost summary card (tokens + cost_usd) derived from ``run.metrics``
 *  3. Tabs: Graph · Timeline · Steps · Raw
 *     - Graph    — visual DAG via ``ExecutionGraph`` (clickable)
 *     - Timeline — chronological event timeline via ``EventTimeline``
 *     - Steps    — flat step list (the click target is shared with Graph)
 *     - Raw      — JSON view of the canonical run object
 *  4. ``StepDetail`` panel rendered when a step is selected
 *
 * Live updates come from ``useEventStream``; the run summary is also
 * polled by ``useRun`` while the run is active.
 *
 * Routing: registered at ``/executions/:id`` in App.tsx (already wired).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  DollarSign,
  Loader2,
  Pause,
  StopCircle,
  XCircle,
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ExecutionGraph, type GraphDefinition } from "@/components/executions/ExecutionGraph";
import { EventTimeline } from "@/components/executions/EventTimeline";
import { StepDetail } from "@/components/executions/StepDetail";
import { useCancelRun, useRun, isRunActive } from "@/hooks/useRuns";
import { useEventStream } from "@/hooks/useEventStream";
import type {
  WorkflowRun,
  WorkflowRunStep,
  StepStatus,
  RunStatus,
} from "@/types/workflow_run";

const RUN_STATUS_BADGE: Record<
  string,
  { cls: string; Icon: typeof CheckCircle2 }
> = {
  pending: { cls: "bg-gray-500/20 text-gray-300", Icon: Clock },
  queued: { cls: "bg-yellow-500/20 text-yellow-300", Icon: Clock },
  running: { cls: "bg-blue-500/20 text-blue-300", Icon: Loader2 },
  completed: { cls: "bg-green-500/20 text-green-300", Icon: CheckCircle2 },
  failed: { cls: "bg-red-500/20 text-red-300", Icon: XCircle },
  cancelled: { cls: "bg-orange-500/20 text-orange-300", Icon: AlertCircle },
  paused: { cls: "bg-purple-500/20 text-purple-300", Icon: Pause },
};

function StatusBadge({ status }: { status: string }) {
  const conf = RUN_STATUS_BADGE[status] ?? RUN_STATUS_BADGE.pending;
  if (!conf) return null;
  const { cls, Icon } = conf;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium capitalize ${cls}`}
    >
      <Icon size={12} className={status === "running" ? "animate-spin" : ""} />
      {status}
    </span>
  );
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(2)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1_000)}s`;
}

function fmtCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  return `$${cost.toFixed(4)}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

/**
 * Extract the static graph definition from a canonical run, when present.
 * Tolerates missing/partial shapes — returns ``null`` if no usable shape
 * is found.
 */
function extractGraphDef(
  run: WorkflowRun | undefined,
): GraphDefinition | null {
  if (!run?.definition_snapshot) return null;
  const snap = run.definition_snapshot as Record<string, unknown>;
  const candidate =
    (snap.graph_definition as Record<string, unknown> | undefined) ?? snap;
  const nodes = candidate.nodes;
  const edges = candidate.edges;
  if (!Array.isArray(nodes) || !Array.isArray(edges)) return null;
  return { nodes, edges } as GraphDefinition;
}

/**
 * The canonical run shape exposes ``definition_snapshot`` but does NOT
 * embed a full step list. We synthesise a step list from any embedded
 * ``steps`` array on the snapshot OR from the unique ``step_id`` values
 * we see in the event stream — then we hydrate them with status/timing
 * derived from the events.
 */
function deriveSteps(
  run: WorkflowRun | undefined,
  events: ReturnType<typeof useEventStream>["events"],
): WorkflowRunStep[] {
  const nodeNames = new Map<string, string>();
  const snap = run?.definition_snapshot as Record<string, unknown> | undefined;
  const graphDef = (snap?.graph_definition ?? snap) as
    | { nodes?: { id: string; data?: { label?: string } }[] }
    | undefined;
  if (Array.isArray(graphDef?.nodes)) {
    for (const n of graphDef.nodes) {
      nodeNames.set(n.id, n.data?.label ?? n.id);
    }
  }

  const stepMap = new Map<string, WorkflowRunStep>();

  const ensure = (sid: string): WorkflowRunStep => {
    let s = stepMap.get(sid);
    if (s) return s;
    s = {
      id: sid,
      run_id: run?.id ?? "",
      step_id: sid,
      name: nodeNames.get(sid) ?? sid,
      status: "pending" as StepStatus,
      started_at: null,
      completed_at: null,
      duration_ms: 0,
      input_data: {},
      output_data: null,
      error: null,
      agent_execution_id: null,
      attempt: 1,
      retry_count: 0,
      idempotency_key: null,
      checkpoint_thread_id: null,
      input_hash: null,
      output_artifact_id: null,
      token_usage: {},
      cost_usd: null,
      worker_id: null,
      error_code: null,
      created_at: run?.created_at ?? new Date(0).toISOString(),
    };
    stepMap.set(sid, s);
    return s;
  };

  // Seed from graph definition so we always render every declared step,
  // even before any event arrives.
  for (const id of nodeNames.keys()) ensure(id);

  // Hydrate from the event stream.
  for (const ev of events) {
    if (!ev.step_id) continue;
    const s = ensure(ev.step_id);
    switch (ev.event_type) {
      case "step.started":
        s.status = "running";
        s.started_at = ev.created_at;
        break;
      case "step.completed":
        s.status = "completed";
        s.completed_at = ev.created_at;
        break;
      case "step.failed":
        s.status = "failed";
        s.completed_at = ev.created_at;
        s.error =
          (typeof ev.payload.error === "string" ? ev.payload.error : null) ??
          s.error;
        break;
      case "step.skipped":
        s.status = "skipped";
        break;
      case "step.paused":
        s.status = "paused";
        break;
      case "step.retry":
        s.retry_count += 1;
        s.attempt += 1;
        break;
      default:
        break;
    }
  }

  // Compute durations from the timeline.
  for (const s of stepMap.values()) {
    if (s.started_at && s.completed_at) {
      s.duration_ms = Math.max(
        0,
        new Date(s.completed_at).getTime() - new Date(s.started_at).getTime(),
      );
    }
  }

  return [...stepMap.values()];
}

export function ExecutionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { run, isLoading, isError } = useRun(id);
  const { events, status: streamStatus, chainVerified } = useEventStream(id);

  const [tab, setTab] = useState("graph");
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  const cancelMutation = useCancelRun();

  // Reset selection when run changes
  useEffect(() => {
    setSelectedStepId(null);
  }, [id]);

  const graphDef = useMemo(() => extractGraphDef(run), [run]);
  const steps = useMemo(() => deriveSteps(run, events), [run, events]);

  const selectedStep = useMemo(
    () => steps.find((s) => s.step_id === selectedStepId) ?? null,
    [steps, selectedStepId],
  );

  const handleStepSelect = useCallback((stepId: string) => {
    setSelectedStepId((prev) => (prev === stepId ? null : stepId));
  }, []);

  const handleEventClick = useCallback((ev: { step_id: string | null }) => {
    if (ev.step_id) setSelectedStepId(ev.step_id);
  }, []);

  const handleCancel = useCallback(() => {
    if (!id) return;
    cancelMutation.mutate(id);
  }, [id, cancelMutation]);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !run) {
    return (
      <div className="p-6" data-testid="run-error">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          Run not found.
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="mt-4"
          onClick={() => navigate("/executions")}
        >
          <ArrowLeft size={14} className="mr-1" /> Back
        </Button>
      </div>
    );
  }

  const metrics = run.metrics ?? null;
  const totalTokens =
    (typeof metrics?.total_tokens === "number"
      ? metrics.total_tokens
      : metrics?.tokens) ?? null;
  const cost = typeof metrics?.cost_usd === "number" ? metrics.cost_usd : null;

  const cancellable = isRunActive(run.status as RunStatus);

  return (
    <div className="p-6" data-testid="execution-detail-page">
      <Button
        variant="ghost"
        size="sm"
        className="mb-4 text-gray-400"
        onClick={() => navigate("/executions")}
      >
        <ArrowLeft size={14} className="mr-1" /> Executions
      </Button>

      {/* Summary card */}
      <div
        className="mb-4 rounded-lg border border-surface-border bg-surface-raised p-4"
        data-testid="run-summary"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <h1 className="truncate text-lg font-bold text-white">
                {run.kind === "agent" ? "Agent run" : "Workflow run"}
              </h1>
              <StatusBadge status={run.status} />
              <span
                className="rounded-md border border-surface-border px-2 py-0.5 text-[10px] uppercase text-gray-400"
                data-testid="ws-status"
              >
                stream:{streamStatus}
              </span>
            </div>
            <p className="mt-1 truncate font-mono text-[11px] text-gray-500">
              {run.id}
            </p>
          </div>

          {cancellable && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCancel}
              disabled={cancelMutation.isPending}
              className="text-orange-300 hover:text-orange-200"
              data-testid="cancel-run"
            >
              {cancelMutation.isPending ? (
                <Loader2 size={14} className="mr-1 animate-spin" />
              ) : (
                <StopCircle size={14} className="mr-1" />
              )}
              Cancel
            </Button>
          )}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Started" value={fmtDate(run.started_at)} />
          <Stat label="Completed" value={fmtDate(run.completed_at)} />
          <Stat label="Duration" value={fmtDuration(run.duration_ms)} />
          <Stat label="Tenant" value={run.tenant_id ?? "—"} mono />
          <Stat label="Kind" value={run.kind} />
          <Stat label="Trigger" value={run.trigger_type} />
          <Stat label="Triggered by" value={run.triggered_by} mono />
          <Stat
            label="Attempt"
            value={String(run.attempt)}
          />
        </div>

        {run.error && (
          <div className="mt-3 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">
            <div className="text-[10px] font-semibold uppercase">Error</div>
            <p className="mt-1 whitespace-pre-wrap">{run.error}</p>
            {run.error_code && (
              <p className="mt-1 font-mono text-[10px] text-red-400">
                code={run.error_code}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Cost summary card */}
      <div
        className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3"
        data-testid="cost-summary"
      >
        <div className="rounded-lg border border-surface-border bg-surface-raised p-3">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-gray-500">
            <Zap size={11} /> Tokens
          </div>
          <div className="mt-1 text-lg font-bold text-white">
            {totalTokens ?? "—"}
          </div>
        </div>
        <div className="rounded-lg border border-surface-border bg-surface-raised p-3">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-gray-500">
            <DollarSign size={11} /> Cost
          </div>
          <div className="mt-1 text-lg font-bold text-white">
            {fmtCost(cost)}
          </div>
        </div>
        <div className="rounded-lg border border-surface-border bg-surface-raised p-3">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">
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

      {/* Two-pane layout: tabs (left, fluid) + step detail (right) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="bg-surface-raised border border-surface-border">
              <TabsTrigger value="graph">Graph</TabsTrigger>
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
              <TabsTrigger value="steps">Steps</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
            </TabsList>

            <TabsContent value="graph">
              <div className="rounded-lg border border-surface-border bg-surface-raised">
                <ExecutionGraph
                  steps={steps}
                  graphDefinition={graphDef}
                  selectedStepId={selectedStepId}
                  onStepSelect={handleStepSelect}
                />
              </div>
            </TabsContent>

            <TabsContent value="timeline">
              <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
                <EventTimeline
                  events={events}
                  chainVerified={chainVerified}
                  selectedStepId={selectedStepId}
                  onEventClick={handleEventClick}
                />
              </div>
            </TabsContent>

            <TabsContent value="steps">
              <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
                {steps.length === 0 ? (
                  <p className="text-xs text-gray-500">No steps yet.</p>
                ) : (
                  <ul className="space-y-1">
                    {steps.map((s) => (
                      <li
                        key={s.step_id}
                        onClick={() => handleStepSelect(s.step_id)}
                        data-testid="step-row"
                        className={`flex cursor-pointer items-center gap-3 rounded-md border p-2 text-xs ${
                          selectedStepId === s.step_id
                            ? "border-purple-500/50 bg-purple-500/10"
                            : "border-surface-border bg-surface-base hover:bg-white/5"
                        }`}
                      >
                        <span className="flex-1 truncate font-medium text-white">
                          {s.name}
                        </span>
                        <span className="text-[10px] capitalize text-gray-400">
                          {s.status}
                        </span>
                        <span className="text-[10px] text-gray-500">
                          {fmtDuration(s.duration_ms)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </TabsContent>

            <TabsContent value="raw">
              <pre className="max-h-[600px] overflow-auto rounded bg-black/30 p-4 text-xs text-gray-300 font-mono">
                {JSON.stringify(run, null, 2)}
              </pre>
            </TabsContent>
          </Tabs>
        </div>

        <div>
          <StepDetail
            step={selectedStep}
            onClose={() => setSelectedStepId(null)}
          />
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div
        className={`text-xs text-white ${mono ? "font-mono truncate" : "capitalize"}`}
      >
        {value}
      </div>
    </div>
  );
}

export default ExecutionDetailPage;
