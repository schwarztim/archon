/**
 * useEventStream
 *
 * Subscribes to ``/ws/runs/{run_id}/events`` and returns the running list
 * of ``WorkflowRunEvent`` values plus a connection status.
 *
 * The hook ALSO seeds the event list with the current ``getRunEvents``
 * response on mount so the timeline is dense even before WS messages
 * arrive. WS pushes are appended in order (de-duplicated by ``id``).
 *
 * Auto-reconnects on close with a 3 s back-off. On reconnect, the seed
 * fetch is repeated so any events the client missed during the outage
 * are surfaced.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { listRunEvents, subscribeRunEvents } from "@/api/events";
import type {
  EventType,
  WorkflowRunEvent,
} from "@/types/events";

export type EventStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "error";

export interface UseEventStreamResult {
  events: WorkflowRunEvent[];
  status: EventStreamStatus;
  /** ``true`` when the most recent seed/refresh page reported chain integrity. */
  chainVerified: boolean | null;
  reconnect: () => void;
  /** Forget all events (e.g., when the user switches runs). */
  clear: () => void;
}

const RECONNECT_DELAY_MS = 3_000;

interface Options {
  /** Pre-filter the seed fetch to specific event types. */
  eventTypes?: EventType[];
  /** Cap on the number of events kept in memory. */
  maxBuffer?: number;
}

export function useEventStream(
  runId: string | null | undefined,
  options: Options = {},
): UseEventStreamResult {
  const { eventTypes, maxBuffer = 5_000 } = options;

  const [events, setEvents] = useState<WorkflowRunEvent[]>([]);
  const [status, setStatus] = useState<EventStreamStatus>("idle");
  const [chainVerified, setChainVerified] = useState<boolean | null>(null);
  const [reconnectTick, setReconnectTick] = useState(0);

  const seenIdsRef = useRef<Set<string>>(new Set());
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const subscriptionRef = useRef<{ unsubscribe: () => void } | null>(null);
  const mountedRef = useRef(true);

  const upsertEvent = useCallback(
    (ev: WorkflowRunEvent) => {
      if (seenIdsRef.current.has(ev.id)) return;
      seenIdsRef.current.add(ev.id);
      setEvents((prev) => {
        const next = [...prev, ev];
        if (next.length > maxBuffer) {
          // Trim oldest while keeping the seen-set in sync.
          const drop = next.length - maxBuffer;
          for (let i = 0; i < drop; i++) {
            const removed = next[i];
            if (removed) seenIdsRef.current.delete(removed.id);
          }
          return next.slice(drop);
        }
        return next;
      });
    },
    [maxBuffer],
  );

  const seed = useCallback(
    async (rid: string, signal: AbortSignal) => {
      try {
        const page = await listRunEvents(rid, {
          ...(eventTypes ? { event_types: eventTypes } : {}),
          limit: 200,
        });
        if (signal.aborted || !mountedRef.current) return;
        setChainVerified(page.chain_verified);
        // Seed in chronological order
        page.events
          .slice()
          .sort((a, b) => a.sequence - b.sequence)
          .forEach(upsertEvent);
      } catch {
        // Soft-fail — the WS subscription may still produce events.
      }
    },
    [eventTypes, upsertEvent],
  );

  const clear = useCallback(() => {
    seenIdsRef.current = new Set();
    setEvents([]);
    setChainVerified(null);
  }, []);

  const triggerReconnect = useCallback(() => {
    setReconnectTick((t) => t + 1);
    setStatus("connecting");
  }, []);

  // Effect — open/close subscription whenever runId or reconnect tick changes.
  useEffect(() => {
    mountedRef.current = true;
    if (!runId) {
      setStatus("idle");
      return;
    }

    const ac = new AbortController();
    setStatus("connecting");

    void seed(runId, ac.signal);

    const sub = subscribeRunEvents(
      runId,
      (ev) => {
        if (!mountedRef.current) return;
        setStatus("open");
        upsertEvent(ev);
      },
      () => {
        if (!mountedRef.current) return;
        setStatus("closed");
        // Auto-reconnect
        if (reconnectTimerRef.current !== null) {
          clearTimeout(reconnectTimerRef.current);
        }
        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current) {
            triggerReconnect();
          }
        }, RECONNECT_DELAY_MS);
      },
      () => {
        if (!mountedRef.current) return;
        setStatus("error");
      },
    );

    subscriptionRef.current = sub;
    setStatus("open");

    return () => {
      mountedRef.current = false;
      ac.abort();
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      try {
        sub.unsubscribe();
      } catch {
        // ignore
      }
      subscriptionRef.current = null;
    };
  }, [runId, reconnectTick, seed, triggerReconnect, upsertEvent]);

  return {
    events,
    status,
    chainVerified,
    reconnect: triggerReconnect,
    clear,
  };
}
