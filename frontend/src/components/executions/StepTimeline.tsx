import { useState } from "react";
import {
  CheckCircle2,
  AlertCircle,
  Circle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Clock,
  Zap,
  DollarSign,
} from "lucide-react";

export interface StepData {
  step_name?: string;
  name?: string;
  step_type?: string;
  status: string;
  duration_ms?: number;
  token_usage?: number;
  tokens?: number;
  cost?: number;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string | null;
}

interface StepTimelineProps {
  steps: StepData[];
  className?: string;
}

const STEP_TYPE_COLORS: Record<string, string> = {
  llm_call: "border-blue-500/50 bg-blue-500/10",
  tool_call: "border-purple-500/50 bg-purple-500/10",
  condition: "border-yellow-500/50 bg-yellow-500/10",
  transform: "border-cyan-500/50 bg-cyan-500/10",
  retrieval: "border-green-500/50 bg-green-500/10",
};

function stepStatusIcon(status: string) {
  if (status === "completed") return <CheckCircle2 size={16} className="text-green-400" />;
  if (status === "running") return <Loader2 size={16} className="animate-spin text-blue-400" />;
  if (status === "failed") return <AlertCircle size={16} className="text-red-400" />;
  if (status === "skipped") return <Circle size={16} className="text-gray-600" />;
  return <Circle size={16} className="text-gray-500" />;
}

function formatDuration(ms: number | undefined | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatCost(cost: number | undefined | null): string {
  if (cost == null || cost === 0) return "";
  return `$${cost.toFixed(4)}`;
}

function StepItem({ step, index, isLast }: { step: StepData; index: number; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const name = step.step_name ?? step.name ?? `Step ${index + 1}`;
  const tokens = step.token_usage ?? step.tokens;
  const typeStyle = step.step_type ? STEP_TYPE_COLORS[step.step_type] ?? "" : "";

  return (
    <div className="relative flex gap-3">
      {/* Timeline line */}
      <div className="flex flex-col items-center">
        <div className="mt-1">{stepStatusIcon(step.status)}</div>
        {!isLast && <div className="mt-1 h-full w-px bg-[#2a2d37]" />}
      </div>

      {/* Content */}
      <div className="mb-3 flex-1">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-2 text-left"
        >
          {expanded ? <ChevronDown size={12} className="text-gray-500" /> : <ChevronRight size={12} className="text-gray-500" />}
          <span className="text-sm font-medium text-white capitalize">{name}</span>
          {step.step_type && (
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium capitalize ${typeStyle}`}>
              {step.step_type.replace("_", " ")}
            </span>
          )}
        </button>

        {/* Metrics row */}
        <div className="mt-1 flex flex-wrap gap-3 text-xs text-gray-500">
          {step.duration_ms != null && (
            <span className="flex items-center gap-1"><Clock size={10} /> {formatDuration(step.duration_ms)}</span>
          )}
          {tokens != null && tokens > 0 && (
            <span className="flex items-center gap-1"><Zap size={10} /> {tokens} tokens</span>
          )}
          {step.cost != null && step.cost > 0 && (
            <span className="flex items-center gap-1"><DollarSign size={10} /> {formatCost(step.cost)}</span>
          )}
        </div>

        {/* Error */}
        {step.error && (
          <div className="mt-1 rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-400">
            {step.error}
          </div>
        )}

        {/* Expanded detail */}
        {expanded && (
          <div className="mt-2 space-y-2 rounded border border-[#2a2d37] bg-black/30 p-3">
            {step.input && (
              <div>
                <div className="mb-1 text-[10px] font-semibold uppercase text-gray-500">Input</div>
                <pre className="max-h-32 overflow-auto text-xs text-gray-400">
                  {JSON.stringify(step.input, null, 2)}
                </pre>
              </div>
            )}
            {step.output && (
              <div>
                <div className="mb-1 text-[10px] font-semibold uppercase text-gray-500">Output</div>
                <pre className="max-h-32 overflow-auto text-xs text-gray-400">
                  {JSON.stringify(step.output, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function StepTimeline({ steps, className = "" }: StepTimelineProps) {
  if (!steps || steps.length === 0) {
    return (
      <div className={`text-center text-sm text-gray-500 ${className}`}>
        No steps recorded.
      </div>
    );
  }

  return (
    <div className={className}>
      {steps.map((step, i) => (
        <StepItem key={i} step={step} index={i} isLast={i === steps.length - 1} />
      ))}
    </div>
  );
}
