# Golden Path 01: Create and Run an Agent

Create an agent via the API, execute it, and stream results over WebSocket.

## Prerequisites

- Archon API running at `http://localhost:8000`
- A valid JWT token (set as `$TOKEN`), `curl`, and [`websocat`](https://github.com/nickel/websocat)

```bash
export BASE=http://localhost:8000/api/v1
export TOKEN="eyJhbGciOiJSUzI1NiIs..."
```

## Step 1: Create an Agent

```bash
curl -s -X POST "$BASE/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "summariser-v1",
    "description": "Summarises long-form text into bullet points",
    "definition": {
      "nodes": [
        {"id": "input", "type": "input"},
        {"id": "llm", "type": "llm", "model": "gpt-4o", "prompt_template": "Summarise: {{text}}"},
        {"id": "output", "type": "output"}
      ],
      "edges": [{"from": "input", "to": "llm"}, {"from": "llm", "to": "output"}]
    },
    "tags": ["summarisation", "text"]
  }'
```

**Response (201 Created):**

```json
{
  "data": {
    "id": "a1b2c3d4-5678-9abc-def0-1234567890ab",
    "name": "summariser-v1",
    "definition": { "nodes": ["..."], "edges": ["..."] },
    "tags": ["summarisation", "text"],
    "status": "draft",
    "owner_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "created_at": "2025-07-15T10:30:00Z",
    "updated_at": "2025-07-15T10:30:00Z"
  },
  "meta": { "request_id": "c9bf9e57-1685-4c89-bafb-ff5af830be8a", "timestamp": "2025-07-15T10:30:00Z" }
}
```

```bash
export AGENT_ID="a1b2c3d4-5678-9abc-def0-1234567890ab"
```

## Step 2: Execute the Agent

```bash
curl -s -X POST "$BASE/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "'"$AGENT_ID"'",
    "input": { "text": "Archon is an open-source AI orchestration platform..." },
    "parameters": { "timeout_ms": 30000 }
  }'
```

**Response (202 Accepted):**

```json
{
  "data": {
    "id": "e2d3c4b5-a6f7-8901-bcde-f01234567890",
    "agent_id": "a1b2c3d4-5678-9abc-def0-1234567890ab",
    "status": "queued",
    "input": { "text": "Archon is an open-source..." },
    "output": null, "error": null,
    "parameters": { "timeout_ms": 30000 },
    "owner_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "started_at": null, "completed_at": null, "duration_ms": null,
    "created_at": "2025-07-15T10:30:05Z",
    "updated_at": "2025-07-15T10:30:05Z"
  },
  "meta": { "request_id": "d8a7b6c5-4e3f-2a1b-0c9d-8e7f6a5b4c3d", "timestamp": "2025-07-15T10:30:05Z" }
}
```

## Step 3: Stream Results via WebSocket

```bash
export EXEC_ID="e2d3c4b5-a6f7-8901-bcde-f01234567890"
websocat "ws://localhost:8000/api/v1/ws/executions/$EXEC_ID" \
  -H "Authorization: Bearer $TOKEN"
# After connecting, send:  {"type": "subscribe"}
```

The server pushes events as the execution progresses:

```json
{"type": "status_changed", "status": "running",   "timestamp": "2025-07-15T10:30:06Z"}
{"type": "node_started",   "node_id": "llm",      "timestamp": "2025-07-15T10:30:06Z"}
{"type": "output",         "data": {"summary": ["• AI orchestration platform"]}, "timestamp": "2025-07-15T10:30:08Z"}
{"type": "node_completed", "node_id": "llm",      "timestamp": "2025-07-15T10:30:08Z"}
{"type": "status_changed", "status": "completed",  "timestamp": "2025-07-15T10:30:08Z"}
```

The connection closes automatically when the execution reaches a terminal state.

## Next Steps

- [02 — Agent from Template](./02-agent-from-template.md) · [03 — Monitor Execution](./03-monitor-execution.md)
