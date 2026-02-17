# Golden Path 03: Monitor Execution

Start an execution, stream real-time updates via WebSocket, and poll REST as a fallback.

## Prerequisites

- Archon API running at `http://localhost:8000`
- A valid JWT token (set as `$TOKEN`), an existing agent, `curl`, `jq`, and [`websocat`](https://github.com/nickel/websocat)

```bash
export BASE=http://localhost:8000/api/v1
export TOKEN="eyJhbGciOiJSUzI1NiIs..."
export AGENT_ID="a1b2c3d4-5678-9abc-def0-1234567890ab"
```

## Step 1: Start an Execution

```bash
curl -s -X POST "$BASE/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "'"$AGENT_ID"'",
    "input": { "text": "Explain quantum computing in simple terms." },
    "parameters": { "timeout_ms": 60000 }
  }' | jq .
```

Save the execution ID from the **202 Accepted** response:

```bash
export EXEC_ID="e2d3c4b5-a6f7-8901-bcde-f01234567890"
```

## Step 2: Stream via WebSocket (Primary)

```bash
websocat "ws://localhost:8000/api/v1/ws/executions/$EXEC_ID" \
  -H "Authorization: Bearer $TOKEN"
# After connecting, send:  {"type": "subscribe"}
```

### Event Types

| Event | Description |
|---|---|
| `status_changed` | Execution transitioned (`queued` → `running` → `completed`/`failed`/`cancelled`) |
| `node_started` | A graph node began processing |
| `node_completed` | A graph node finished |
| `log` | Structured log entry |
| `output` | Final or intermediate output data |
| `error` | Error details |

### Example Event Stream

```json
{"type": "status_changed", "status": "running",   "timestamp": "2025-07-15T12:00:01Z"}
{"type": "node_started",   "node_id": "input",    "timestamp": "2025-07-15T12:00:01Z"}
{"type": "node_completed", "node_id": "input",    "timestamp": "2025-07-15T12:00:01Z"}
{"type": "node_started",   "node_id": "llm",      "timestamp": "2025-07-15T12:00:02Z"}
{"type": "log",            "level": "info", "message": "LLM inference started", "node_id": "llm", "timestamp": "2025-07-15T12:00:02Z"}
{"type": "output",         "data": {"answer": "Quantum computing uses qubits..."}, "timestamp": "2025-07-15T12:00:05Z"}
{"type": "node_completed", "node_id": "llm",      "timestamp": "2025-07-15T12:00:05Z"}
{"type": "status_changed", "status": "completed",  "timestamp": "2025-07-15T12:00:05Z"}
```

The connection closes automatically on terminal states (`completed`, `failed`, `cancelled`).

## Step 3: Poll via REST (Fallback)

Use when WebSocket is unavailable (e.g. proxy strips upgrade headers). Poll every 2–5 seconds:

```bash
curl -s "$BASE/executions/$EXEC_ID" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**Response (200 OK) — while running:**

```json
{
  "data": {
    "id": "e2d3c4b5-a6f7-8901-bcde-f01234567890",
    "agent_id": "a1b2c3d4-5678-9abc-def0-1234567890ab",
    "status": "running",
    "output": null, "error": null,
    "started_at": "2025-07-15T12:00:01Z", "completed_at": null, "duration_ms": null,
    "created_at": "2025-07-15T12:00:00Z", "updated_at": "2025-07-15T12:00:01Z"
  },
  "meta": { "request_id": "4d5e6f7a-8b9c-0d1e-2f3a-4b5c6d7e8f9a", "timestamp": "2025-07-15T12:00:03Z" }
}
```

## Step 4: Handle Errors

On failure, the `error` field is populated. Via REST:

```json
{
  "data": {
    "status": "failed",
    "error": { "code": "LLM_TIMEOUT", "message": "LLM inference exceeded timeout of 60000ms", "details": "Node 'llm' timed out" },
    "completed_at": "2025-07-15T12:01:00Z", "duration_ms": 60000
  },
  "meta": { "request_id": "5e6f7a8b-9c0d-1e2f-3a4b-5c6d7e8f9a0b", "timestamp": "2025-07-15T12:01:00Z" }
}
```

Via WebSocket, `error` arrives before the final `status_changed`:

```json
{"type": "error",          "code": "LLM_TIMEOUT", "message": "LLM inference exceeded timeout of 60000ms", "node_id": "llm", "timestamp": "2025-07-15T12:01:00Z"}
{"type": "status_changed", "status": "failed",    "timestamp": "2025-07-15T12:01:00Z"}
```

## Next Steps

- [01 — Create and Run an Agent](./01-create-and-run-agent.md) · [02 — Agent from Template](./02-agent-from-template.md)
