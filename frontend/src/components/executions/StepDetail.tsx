/**
 * StepDetail
 *
 * Side-panel detail view for a single ``WorkflowRunStep``.
 *
 * Tabs: Input · Output · Logs · Timing · Cost
 *
 * Each tab shows a truncated preview by default with a "Show full" toggle.
 * The Cost tab surfaces the canonical ``token_usage`` (prompt/completion)
 * and ``cost_usd`` fields plus any ``provider`` / ``model`` /
 * ``routing_decision`` keys nested inside ``output_data``.
 */
import { useMemo, useState } from "react";
import { X } from "lucide-react";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import type { WorkflowRunStep } from "@/types/workflow_run";

interface StepDetailProps {
  step: WorkflowRunStep | null;
  onClose?: () => void;
}

const TRUNCATE_LIMIT = 1_500;

function PrettyJSON({
  value,
  truncate,
}: {
  value: unknown;
  truncate: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const json = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return "<unserializable>";
    }
  }, [value]);

  const showTruncated = truncate && !expanded && json.length > TRUNCATE_LIMIT;
  const display = showTruncated ? `${json.slice(0, TRUNCATE_LIMIT)}…` : json;

  return (
    <div className="space-y-2">
      <pre className="max-h-[400px] overflow-auto rounded bg-black/30 p-3 text-[11px] text-gray-300 font-mono">
        {display}
      </pre>
      {truncate && json.length > TRUNCATE_LIMIT && (
        <button
          type="button"
          className="text-[11px] text-purple-300 hover:text-purple-200"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show truncated" : "Show full"}
        </button>
      )}
    </div>
  );
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(2)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1_000)}s`;
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  return `$${cost.toFixed(6)}`;
}

function formatStartEnd(s: string | null, e: string | null): string {
  if (!s) return "—";
  const start = new Date(s).toLocaleString();
  if (!e) return `${start} →`;
  const end = new Date(e).toLocaleString();
  return `${start} → ${end}`;
}

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-gray-500/20 text-gray-300",
  running: "bg-blue-500/20 text-blue-300",
  completed: "bg-green-500/20 text-green-300",
  failed: "bg-red-500/20 text-red-300",
  skipped: "bg-gray-500/20 text-gray-400",
  paused: "bg-purple-500/20 text-purple-300",
};

export function StepDetail({ step, onClose }: StepDetailProps) {
  const [tab, setTab] = useState("input");

  if (!step) {
    return (
      <div className="rounded-lg border border-dashed border-surface-border p-6 text-center text-xs text-gray-500">
        Select a step to inspect its input, output, timing, and cost.
      </div>
    );
  }

  const tokens = step.token_usage ?? {};
  const promptTokens =
    typeof tokens.prompt_tokens === "number" ? tokens.prompt_tokens : null;
  const completionTokens =
    typeof tokens.completion_tokens === "number"
      ? tokens.completion_tokens
      : null;
  const totalTokens =
    typeof tokens.total_tokens === "number"
      ? tokens.total_tokens
      : promptTokens != null && completionTokens != null
        ? promptTokens + completionTokens
        : null;

  const out = step.output_data ?? {};
  const provider =
    typeof (out as Record<string, unknown>).provider === "string"
      ? ((out as Record<string, unknown>).provider as string)
      : null;
  const model =
    typeof (out as Record<string, unknown>).model === "string"
      ? ((out as Record<string, unknown>).model as string)
      : null;
  const routingDecision = (out as Record<string, unknown>).routing_decision;

  return (
    <div
      className="rounded-lg border border-surface-border bg-surface-raised"
      data-testid="step-detail"
    >
      {/* Header */}
      <div className="flex items-start gap-3 border-b border-surface-border p-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-white">
              {step.name}
            </h3>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${STATUS_STYLES[step.status] ?? STATUS_STYLES.pending}`}
            >
              {step.status}
            </span>
          </div>
          <p className="mt-0.5 truncate font-mono text-[10px] text-gray-500">
            {step.id}
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close step detail"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="p-4">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="input">Input</TabsTrigger>
            <TabsTrigger value="output">Output</TabsTrigger>
            <TabsTrigger value="logs">Logs</TabsTrigger>
            <TabsTrigger value="timing">Timing</TabsTrigger>
            <TabsTrigger value="cost">Cost</TabsTrigger>
          </TabsList>

          <TabsContent value="input">
            <PrettyJSON value={step.input_data} truncate />
          </TabsContent>

          <TabsContent value="output">
            {step.error ? (
              <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">
                <div className="text-[10px] font-semibold uppercase">Error</div>
                <p className="mt-1 whitespace-pre-wrap">{step.error}</p>
                {step.error_code && (
                  <p className="mt-1 font-mono text-[10px] text-red-400">
                    code={step.error_code}
                  </p>
                )}
              </div>
            ) : (
              <PrettyJSON value={step.output_data ?? {}} truncate />
            )}
          </TabsContent>

          <TabsContent value="logs">
            <p className="text-xs text-gray-500">
              Inline logs are not yet emitted into the run-events stream — see
              the Output tab for any captured stdout, or the artifact browser
              for full execution logs.
            </p>
          </TabsContent>

          <TabsContent value="timing">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <dt className="text-gray-500">Status</dt>
              <dd className="text-white">{step.status}</dd>
              <dt className="text-gray-500">Duration</dt>
              <dd className="text-white">{formatDuration(step.duration_ms)}</dd>
              <dt className="text-gray-500">Started → Completed</dt>
              <dd className="text-white">
                {formatStartEnd(step.started_at, step.completed_at)}
              </dd>
              <dt className="text-gray-500">Attempt</dt>
              <dd className="text-white">
                {step.attempt} (retries: {step.retry_count})
              </dd>
              {step.worker_id && (
                <>
                  <dt className="text-gray-500">Worker</dt>
                  <dd className="font-mono text-white">{step.worker_id}</dd>
                </>
              )}
            </dl>
          </TabsContent>

          <TabsContent value="cost">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <dt className="text-gray-500">Prompt tokens</dt>
              <dd className="text-white">{promptTokens ?? "—"}</dd>
              <dt className="text-gray-500">Completion tokens</dt>
              <dd className="text-white">{completionTokens ?? "—"}</dd>
              <dt className="text-gray-500">Total tokens</dt>
              <dd className="text-white">{totalTokens ?? "—"}</dd>
              <dt className="text-gray-500">Cost (USD)</dt>
              <dd className="text-white">{formatCost(step.cost_usd)}</dd>
              {provider && (
                <>
                  <dt className="text-gray-500">Provider</dt>
                  <dd className="text-white">{provider}</dd>
                </>
              )}
              {model && (
                <>
                  <dt className="text-gray-500">Model</dt>
                  <dd className="text-white">{model}</dd>
                </>
              )}
              {routingDecision !== undefined && (
                <>
                  <dt className="text-gray-500">Routing decision</dt>
                  <dd className="text-white">
                    <PrettyJSON value={routingDecision} truncate={false} />
                  </dd>
                </>
              )}
            </dl>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
