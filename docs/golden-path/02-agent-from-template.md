# Golden Path 02: Create an Agent from a Template

List available templates, create an agent from one, customise it, then execute.

## Prerequisites

- Archon API running at `http://localhost:8000`
- A valid JWT token (set as `$TOKEN`), `curl`, and `jq`

```bash
export BASE=http://localhost:8000/api/v1
export TOKEN="eyJhbGciOiJSUzI1NiIs..."
```

## Step 1: List Available Templates

```bash
curl -s "$BASE/templates?limit=10&offset=0" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "b7e1f2a3-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
      "name": "RAG Chatbot",
      "description": "Retrieval-augmented generation chatbot with vector search",
      "definition": { "nodes": ["..."], "edges": ["..."] },
      "tags": ["rag", "chatbot"], "category": "chatbot",
      "author_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "created_at": "2025-07-10T08:00:00Z", "updated_at": "2025-07-10T08:00:00Z"
    }
  ],
  "meta": {
    "request_id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
    "timestamp": "2025-07-15T11:00:00Z",
    "pagination": { "total": 1, "limit": 10, "offset": 0, "has_more": false }
  }
}
```

## Step 2: Create an Agent from the Template

Pass `template_id` when creating the agent, and customise the definition:

```bash
export TEMPLATE_ID="b7e1f2a3-4c5d-6e7f-8a9b-0c1d2e3f4a5b"
curl -s -X POST "$BASE/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "support-bot-v1",
    "description": "Internal support chatbot using company knowledge base",
    "template_id": "'"$TEMPLATE_ID"'",
    "definition": {
      "nodes": [
        {"id": "input", "type": "input"},
        {"id": "retriever", "type": "vector_search", "index": "support-docs", "top_k": 5},
        {"id": "llm", "type": "llm", "model": "gpt-4o"},
        {"id": "output", "type": "output"}
      ],
      "edges": [{"from":"input","to":"retriever"},{"from":"retriever","to":"llm"},{"from":"llm","to":"output"}]
    },
    "tags": ["support", "rag", "internal"]
  }'
```

**Response (201 Created):** Returns the new agent with `template_id` set and `status: "draft"` in the standard `{"data": ..., "meta": {...}}` envelope.

```bash
export AGENT_ID="d9a3b4c5-6e7f-8a9b-0c1d-2e3f4a5b6c7d"  # from response data.id
```

## Step 3: Customise the Agent

```bash
curl -s -X PUT "$BASE/agents/$AGENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "description": "Internal support chatbot — production-ready", "tags": ["support", "rag", "production"] }'
```

## Step 4: Execute the Agent

```bash
curl -s -X POST "$BASE/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "agent_id": "'"$AGENT_ID"'", "input": { "query": "How do I reset my VPN password?" } }'
```

**Response (202 Accepted):**

```json
{
  "data": {
    "id": "e0b4c5d6-7f8a-9b0c-1d2e-3f4a5b6c7d8e",
    "agent_id": "d9a3b4c5-6e7f-8a9b-0c1d-2e3f4a5b6c7d",
    "status": "queued",
    "input": { "query": "How do I reset my VPN password?" },
    "output": null, "error": null,
    "started_at": null, "completed_at": null, "duration_ms": null,
    "created_at": "2025-07-15T11:10:00Z", "updated_at": "2025-07-15T11:10:00Z"
  },
  "meta": { "request_id": "3c4d5e6f-7a8b-9c0d-1e2f-3a4b5c6d7e8f", "timestamp": "2025-07-15T11:10:00Z" }
}
```

Stream results via WebSocket — see [03 — Monitor Execution](./03-monitor-execution.md).

## Next Steps

- [01 — Create and Run an Agent](./01-create-and-run-agent.md) · [03 — Monitor Execution](./03-monitor-execution.md)
