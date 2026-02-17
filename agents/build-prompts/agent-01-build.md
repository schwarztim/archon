# Agent 01 — Core Backend & API Gateway — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context

You are building **Core Backend & API Gateway** for Archon, an enterprise AI orchestration platform.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)

- `backend/app/models/__init__.py` (279 lines) — Agent model with 16+ fields already defined. EXTEND, do not replace.
- `backend/app/routes/agents.py` (160 lines) — Basic CRUD for agents. EXTEND with execution endpoint.
- `backend/app/routes/executions.py` (164 lines) — Read-only list/get endpoints. ADD execution creation.
- `backend/app/routes/audit_logs.py` (134 lines) — Basic list endpoint. FIX auth and empty DB handling.
- `backend/app/services/agent_service.py` (367 lines) — Agent CRUD service. EXTEND.
- `backend/app/services/execution_service.py` (326 lines) — Execution service. EXTEND with creation logic.
- `backend/app/services/audit_log_service.py` (98 lines) — Audit log service. EXTEND.
- `frontend/src/pages/SettingsPage.tsx` (451 lines) — Calls /api/v1/health. Backend needs this alias.

## What to Build

### 1. Expand Agent Schemas
Create Pydantic models for structured sub-schemas (don't rely on raw dict):
- `AgentStep` — step_name: str, step_type: Literal["llm","tool","condition","human","subagent"], config: dict
- `ToolBinding` — tool_name: str, mcp_server_ref: str | None, parameter_overrides: dict | None
- `LLMConfig` — model_id: str, temperature: float = 0.7, max_tokens: int = 4096, system_prompt: str | None, provider_ref: str | None
- `RAGConfig` — collection_id: str | None, chunk_strategy: str = "recursive", top_k: int = 5, rerank: bool = False
- `MCPConfig` — server_url: str | None, tools_enabled: list[str] | None, sandbox_mode: bool = True
- `SecurityPolicy` — dlp_enabled: bool = True, guardrails: list[str] | None, allowed_domains: list[str] | None, max_cost_per_run: float | None

Update `AgentCreate` and `AgentUpdate` schemas to accept these typed sub-schemas.

### 2. Execution Engine
Add `POST /api/v1/agents/{agent_id}/execute`:
- Accept `{"input": {...}, "config_overrides": {...}}`
- Create Execution record with status "running"
- (Stub) Process through agent graph — for now, record input, set status to "completed" after processing
- Return `{"data": {"execution_id": "..."}, "meta": {...}}`
- Future: wire to LangGraph runtime and WebSocket streaming

### 3. Health Endpoint Fix
Add `/api/v1/health` alias that returns `{"status": "healthy", "version": "1.0.0", "timestamp": "..."}`.

### 4. Audit Log Fix
- Add `Depends(get_current_user)` to all audit_logs routes
- Handle empty DB gracefully: return `{"data": [], "meta": {...}}` not 500
- Ensure pagination works

### 5. API Envelope Enforcement
Review all routes — ensure every response follows the envelope format.

## Patterns to Follow (from OSS)

### Pattern 1: Dify App Model (from dify/api/models/model.py)
Dify structures apps with a `mode` field (chat, completion, workflow, agent-chat) and stores config in a typed `app_model_config` relationship table. Each config version is immutable. Archon adaptation: Use the existing Agent model's JSON fields but validate with Pydantic sub-schemas. Create an `AgentConfigVersion` if needed for immutability.

### Pattern 2: Dify API Structure (from dify/api/)
Dify uses Flask blueprints with consistent error handling via decorators. Every endpoint returns a structured response. Archon adaptation: FastAPI already provides this via Pydantic response models. Create a reusable `APIResponse[T]` generic wrapper.

### Pattern 3: Coze Studio Bot Configuration (from coze-studio)
Coze structures bot configs with separate sections for prompt, model, plugins, and knowledge — each independently versioned. Archon adaptation: The Agent model's separate fields (llm_config, tools, rag_config, etc.) already follow this pattern. Ensure each can be updated independently.

## Backend Deliverables

| Endpoint | Method | What It Does |
|---|---|---|
| `/api/v1/agents/{agent_id}/execute` | POST | Create and run execution |
| `/api/v1/health` | GET | Health check alias |
| `/api/v1/audit-logs/` | GET | Fixed: auth + empty handling |

New/modified files:
- `backend/app/schemas/agent_schemas.py` — CREATE — Pydantic sub-schemas (AgentStep, LLMConfig, etc.)
- `backend/app/routes/agents.py` — MODIFY — Add execute endpoint
- `backend/app/routes/audit_logs.py` — MODIFY — Add auth, fix empty handling
- `backend/app/main.py` — MODIFY — Add /api/v1/health route

Request shape for execute:
```json
{
  "input": {"message": "Hello"},
  "config_overrides": {"temperature": 0.5}
}
```

Response shape:
```json
{
  "data": {
    "execution_id": "uuid",
    "status": "running",
    "agent_id": "uuid"
  },
  "meta": {"request_id": "uuid", "timestamp": "ISO8601"}
}
```

## Frontend Deliverables

No frontend changes for Agent 01. Frontend impacts are handled by other agents.

## Integration Points

- **Agent 06 (Executions)**: The execute endpoint creates records that Agent 06's UI displays
- **Agent 08 (Router)**: `llm_config.provider_ref` resolves via `/router/models` — Agent 08 provides this
- **Agent 12 (DLP)**: Future: execution I/O passes through DLP middleware before/after LLM calls
- **Agent 17 (Secrets)**: `from backend.app.secrets.manager import SecretsManager` for any credential access
- **Agent 18 (Audit)**: Every mutation must call `audit_log(user, action, resource_type, resource_id, details)`

## Acceptance Criteria

1. `AgentCreate` accepts typed sub-schemas (LLMConfig, SecurityPolicy, etc.) not just raw dicts
2. `POST /api/v1/agents/{agent_id}/execute` creates Execution record and returns execution_id
3. `GET /api/v1/health` returns `{"status":"healthy"}` (Settings page stops showing 404)
4. `GET /api/v1/audit-logs/` returns `{"data":[], "meta":{...}}` when DB is empty (not 500)
5. All audit_logs routes require authentication
6. All responses follow envelope format
7. All existing tests pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`

## Files to Read Before Starting

- `~/Scripts/Archon/agents/AGENT_RULES.md` (mandatory coding standards)
- `~/Scripts/Archon/backend/app/models/__init__.py` (existing models)
- `~/Scripts/Archon/backend/app/routes/agents.py` (existing agent routes)

## Files to Create/Modify

| Path | Action |
|---|---|
| `backend/app/schemas/agent_schemas.py` | CREATE |
| `backend/app/routes/agents.py` | MODIFY |
| `backend/app/routes/audit_logs.py` | MODIFY |
| `backend/app/main.py` | MODIFY |
| `tests/test_agent_schemas.py` | CREATE |
| `tests/test_execute.py` | CREATE |
| `tests/test_health.py` | CREATE |

## Testing

```bash
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q
curl http://localhost:8000/api/v1/health
curl -X POST http://localhost:8000/api/v1/agents/{id}/execute -H "Authorization: Bearer $TOKEN" -d '{"input":{"message":"test"}}'
curl http://localhost:8000/api/v1/audit-logs/ -H "Authorization: Bearer $TOKEN"
```

## Constraints

- Python 3.12, type hints, docstrings. Use `python3` not `python`.
- Always `PYTHONPATH=backend` for pytest.
- API envelope: `{"data": ..., "meta": {"request_id", "timestamp"}}`
- No raw JSON fields on any user-facing form.
- All credentials via SecretsManager, never in DB.
- Never use `password=value` directly — use dict unpacking.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md.
- Tests must pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`
