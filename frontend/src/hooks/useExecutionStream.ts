/**
 * useExecutionStream
 *
 * Subscribes to real-time execution events over a WebSocket connection.
 *
 * Features
 * --------
 * - Auto-reconnect with 3 s backoff (passes `last_event_id` for missed-event
 *   replay on reconnect)
 * - Event accumulation — full history available via `events`
 * - Token streaming — `currentToken` accumulates LLM stream tokens
 * - Cost tracking — `totalCost` reflects the latest `cost_update` event
 * - Server heartbeat — server sends `{"type":"ping"}` every 30 s; client
 *   replies with `{"type":"pong"}`
 *
 * Usage
 * -----
 * ```tsx
 * const { events, connected, totalCost, currentToken } =
 *   useExecutionStream(executionId);
 * ```
 */

import { useEffect, useRef, useState, useCallback } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Canonical event types emitted by the backend */
export type ExecutionEventType =
  | "llm_stream_token"
  | "tool_call"
  | "tool_result"
  | "agent_start"
  | "agent_complete"
  | "error"
  | "cost_update"
  | "ping"
  | "pong";

/** Shape of a single execution event */
export interface ExecutionEvent {
  event_id: string;
  type: ExecutionEventType;
  timestamp: string;
  data: Record<string, unknown>;
}

/** Payload for llm_stream_token events */
export interface LLMStreamTokenData {
  token: string;
  model?: string;
  provider?: string;
}

/** Payload for cost_update events */
export interface CostUpdateData {
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  total_cost_usd: number;
}

/** Return value of useExecutionStream */
export interface UseExecutionStreamResult {
  /** All received events in order */
  events: ExecutionEvent[];
  /** Whether the WebSocket is currently open */
  connected: boolean;
  /** Running total cost in USD from the latest cost_update event */
  totalCost: number;
  /** Accumulated LLM stream tokens (resets when executionId changes) */
  currentToken: string;
  /** Imperatively clear the accumulated events (e.g. on new run) */
  clearEvents: () => void;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const RECONNECT_DELAY_MS = 3_000;
const HEARTBEAT_INTERVAL_MS = 30_000;

/**
 * Derive the WebSocket base URL from the current page origin.
 * - In dev (Vite proxy): `ws://localhost:3000` → proxied to `ws://localhost:8000`
 * - In production: `wss://app.example.com` (TLS)
 */
function getWsBaseUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}`;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useExecutionStream(
  executionId: string | null,
): UseExecutionStreamResult {
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [totalCost, setTotalCost] = useState(0);
  const [currentToken, setCurrentToken] = useState("");

  // Refs — survive re-renders without triggering effects
  const wsRef = useRef<WebSocket | null>(null);
  const lastEventIdRef = useRef<string | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  /** Set to true when the hook is intentionally cleaning up to suppress reconnect */
  const unmountedRef = useRef(false);

  const clearEvents = useCallback(() => {
    setEvents([]);
    setCurrentToken("");
    setTotalCost(0);
    lastEventIdRef.current = null;
  }, []);

  useEffect(() => {
    if (!executionId) return;

    // Reset token accumulator when executionId changes
    setCurrentToken("");
    setTotalCost(0);
    lastEventIdRef.current = null;
    unmountedRef.current = false;

    // ── Connect ────────────────────────────────────────────────────────

    function connect() {
      if (unmountedRef.current) return;

      const params = lastEventIdRef.current
        ? `?last_event_id=${encodeURIComponent(lastEventIdRef.current)}`
        : "";
      const url = `${getWsBaseUrl()}/ws/executions/${executionId}${params}`;

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (unmountedRef.current) {
          ws.close();
          return;
        }
        setConnected(true);
      };

      ws.onmessage = (msg: MessageEvent<string>) => {
        let event: ExecutionEvent;
        try {
          event = JSON.parse(msg.data) as ExecutionEvent;
        } catch {
          return;
        }

        // Respond to server heartbeat pings
        if (event.type === "ping") {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "pong" }));
          }
          return;
        }

        // Skip bare pong echoes (shouldn't normally arrive but defensive)
        if (event.type === "pong") return;

        // Track the last seen event_id for reconnect replay
        if (event.event_id) {
          lastEventIdRef.current = event.event_id;
        }

        // Accumulate events
        setEvents((prev) => [...prev, event]);

        // Token streaming
        if (event.type === "llm_stream_token") {
          const data = event.data as Partial<LLMStreamTokenData>;
          if (typeof data.token === "string") {
            setCurrentToken((prev) => prev + data.token);
          }
        }

        // Cost tracking
        if (event.type === "cost_update") {
          const data = event.data as Partial<CostUpdateData>;
          if (typeof data.total_cost_usd === "number") {
            setTotalCost(data.total_cost_usd);
          }
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;

        // Stop heartbeat on close — it restarts in the reconnect
        if (heartbeatIntervalRef.current !== null) {
          clearInterval(heartbeatIntervalRef.current);
          heartbeatIntervalRef.current = null;
        }

        if (!unmountedRef.current) {
          // Schedule auto-reconnect
          reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = () => {
        // onerror is always followed by onclose — let onclose handle reconnect
      };

      // ── Heartbeat ────────────────────────────────────────────────────
      heartbeatIntervalRef.current = setInterval(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: "ping" }));
        }
      }, HEARTBEAT_INTERVAL_MS);
    }

    connect();

    // ── Cleanup ────────────────────────────────────────────────────────

    return () => {
      unmountedRef.current = true;

      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }

      if (heartbeatIntervalRef.current !== null) {
        clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = null;
      }

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      setConnected(false);
    };
  }, [executionId]);

  return { events, connected, totalCost, currentToken, clearEvents };
}
