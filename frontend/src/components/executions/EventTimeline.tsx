/**
 * EventTimeline
 *
 * Chronological view of ``WorkflowRunEvent`` rows for a single run.
 *
 * Features
 *  - Filter chips per ``event_type``
 *  - Group toggle: "all" / "run-only" / "step-only"
 *  - Hash-chain integrity badge (✓ / ⚠) — value comes from the
 *    ``EventsResponse.chain_verified`` field, surfaced here as a prop
 *  - Per-step "Replay" button (gated behind ``allowReplay``) that calls
 *    ``onReplay(stepId)``. The wiring to the actual backend endpoint
 *    lives one layer up — this component just signals intent.
 */
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  RefreshCcw,
  Filter as FilterIcon,
} from "lucide-react";

import type { EventType, WorkflowRunEvent } from "@/types/events";

interface EventTimelineProps {
  events: WorkflowRunEvent[];
  /** Hash-chain integrity (``EventsResponse.chain_verified``). */
  chainVerified?: boolean | null;
  /** Currently-selected step id — when set the matching events glow. */
  selectedStepId?: string | null;
  /** Optional click handler — receives the clicked event. */
  onEventClick?: (event: WorkflowRunEvent) => void;
  /** Optional click handler for replay button — receives ``step_id``. */
  onReplay?: (stepId: string) => void;
  /** When ``true`` the per-step replay button is rendered. */
  allowReplay?: boolean;
}

const EVENT_BADGE_STYLES: Record<EventType, string> = {
  // Run-level
  "run.created": "bg-gray-500/20 text-gray-300",
  "run.queued": "bg-yellow-500/20 text-yellow-300",
  "run.claimed": "bg-yellow-500/20 text-yellow-300",
  "run.started": "bg-blue-500/20 text-blue-300",
  "run.completed": "bg-green-500/20 text-green-300",
  "run.failed": "bg-red-500/20 text-red-300",
  "run.cancelled": "bg-orange-500/20 text-orange-300",
  "run.paused": "bg-purple-500/20 text-purple-300",
  "run.resumed": "bg-blue-500/20 text-blue-300",
  // Step-level
  "step.started": "bg-blue-500/15 text-blue-200",
  "step.completed": "bg-green-500/15 text-green-200",
  "step.failed": "bg-red-500/15 text-red-200",
  "step.skipped": "bg-gray-500/15 text-gray-300",
  "step.retry": "bg-amber-500/15 text-amber-200",
  "step.paused": "bg-purple-500/15 text-purple-200",
};

function PhaseFilter({
  value,
  onChange,
}: {
  value: "all" | "run" | "step";
  onChange: (v: "all" | "run" | "step") => void;
}) {
  const opts: Array<{ key: "all" | "run" | "step"; label: string }> = [
    { key: "all", label: "All" },
    { key: "run", label: "Run" },
    { key: "step", label: "Step" },
  ];
  return (
    <div className="inline-flex rounded-md border border-surface-border bg-surface-raised text-xs">
      {opts.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={`px-3 py-1 ${
            value === o.key
              ? "bg-purple-500/30 text-purple-100"
              : "text-gray-400 hover:text-white"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function payloadPreview(payload: Record<string, unknown>): string {
  try {
    const s = JSON.stringify(payload);
    return s.length > 120 ? `${s.slice(0, 120)}…` : s;
  } catch {
    return "<unserializable>";
  }
}

export function EventTimeline({
  events,
  chainVerified,
  selectedStepId,
  onEventClick,
  onReplay,
  allowReplay = false,
}: EventTimelineProps) {
  const [phase, setPhase] = useState<"all" | "run" | "step">("all");
  const [typeFilter, setTypeFilter] = useState<Set<EventType>>(new Set());

  // Distinct event types present in the current event list — used to
  // build filter chips dynamically.
  const presentTypes = useMemo(() => {
    const seen = new Set<EventType>();
    for (const e of events) seen.add(e.event_type);
    return [...seen];
  }, [events]);

  const filtered = useMemo(() => {
    return events
      .filter((e) => {
        if (phase === "run" && !e.event_type.startsWith("run.")) return false;
        if (phase === "step" && !e.event_type.startsWith("step.")) return false;
        if (typeFilter.size > 0 && !typeFilter.has(e.event_type)) return false;
        return true;
      })
      .sort((a, b) => a.sequence - b.sequence);
  }, [events, phase, typeFilter]);

  function toggleType(t: EventType) {
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <PhaseFilter value={phase} onChange={setPhase} />

        {presentTypes.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <FilterIcon size={12} className="text-gray-500" />
            {presentTypes.map((t) => {
              const active = typeFilter.has(t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleType(t)}
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    active
                      ? EVENT_BADGE_STYLES[t]
                      : "bg-surface-base text-gray-400 hover:text-white"
                  }`}
                >
                  {t}
                </button>
              );
            })}
          </div>
        )}

        {/* Chain-verified badge */}
        {chainVerified === true && (
          <span
            data-testid="chain-verified"
            className="ml-auto inline-flex items-center gap-1 rounded-full bg-green-500/20 px-2 py-0.5 text-[10px] font-medium text-green-300"
          >
            <CheckCircle2 size={11} /> chain verified
          </span>
        )}
        {chainVerified === false && (
          <span
            data-testid="chain-broken"
            className="ml-auto inline-flex items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 text-[10px] font-medium text-red-300"
          >
            <AlertTriangle size={11} /> chain broken
          </span>
        )}
      </div>

      {/* List */}
      {filtered.length === 0 ? (
        <p className="py-6 text-center text-xs text-gray-500">
          No events match the current filters.
        </p>
      ) : (
        <ul className="space-y-1">
          {filtered.map((ev) => {
            const isStep = ev.event_type.startsWith("step.");
            const stepHighlighted =
              isStep && selectedStepId && ev.step_id === selectedStepId;
            return (
              <li
                key={ev.id}
                onClick={() => onEventClick?.(ev)}
                className={`cursor-pointer rounded-md border p-2 text-xs transition-colors ${
                  stepHighlighted
                    ? "border-purple-500/60 bg-purple-500/10"
                    : "border-surface-border bg-surface-raised hover:bg-white/5"
                }`}
                data-event-type={ev.event_type}
                data-step-id={ev.step_id ?? ""}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-gray-500">
                    #{ev.sequence}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${EVENT_BADGE_STYLES[ev.event_type]}`}
                  >
                    {ev.event_type}
                  </span>
                  {ev.step_id && (
                    <span className="font-mono text-[10px] text-gray-400">
                      step={ev.step_id}
                    </span>
                  )}
                  <span className="ml-auto text-[10px] text-gray-500">
                    {new Date(ev.created_at).toLocaleTimeString()}
                  </span>
                  {allowReplay && isStep && ev.step_id && onReplay && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (ev.step_id) onReplay(ev.step_id);
                      }}
                      className="inline-flex items-center gap-1 rounded border border-surface-border bg-surface-base px-1.5 py-0.5 text-[10px] text-gray-300 hover:text-white"
                      aria-label={`Replay step ${ev.step_id}`}
                    >
                      <RefreshCcw size={10} /> replay
                    </button>
                  )}
                </div>
                <div className="mt-1 truncate font-mono text-[10px] text-gray-400">
                  {payloadPreview(ev.payload)}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
