# WS-6 MCP Host Gateway — Implementation Report

## Summary

Built a production-ready FastAPI gateway (`gateway/`) that fronts all MCP tool invocations
with Entra ID auth, YAML-driven plugin discovery, guardrails (rate limiting + audit logging),
and tool dispatch routing (builtin AI / container / backend forward).

## Architecture

```
Client → GET  /api/v1/mcp/capabilities        → lists tools user's groups can see
       → POST /api/v1/mcp/tools/{id}/invoke   → auth → guardrails → dispatch
       → GET  /health  /ready                 → health probes
```

## Files Created

### Config & Auth

| File | Description |
|---|---|
| `gateway/app/config.py` | Extended settings: `auth_dev_mode`, `oidc_*`, `azure_openai_*`, `rate_limit_*`, `backend_url` |
| `gateway/app/auth/models.py` | `GatewayUser` Pydantic model (oid, email, name, groups, roles, tenant_id, is_dev) |
| `gateway/app/auth/middleware.py` | `get_current_user()` FastAPI dependency — dev bypass (literal `dev-token` or HS256 JWT) or Entra RS256 via OIDC discovery |

### Plugin System

| File | Description |
|---|---|
| `gateway/app/plugins/models.py` | `Plugin`, `ToolSchema`, `ContainerConfig`, `ResourceLimits` Pydantic models |
| `gateway/app/plugins/loader.py` | `PluginLoader` — scans `gateway/plugins/*.yaml`, validates, hot-reloads via watchfiles. `PluginRegistry` alias exported. |
| `gateway/plugins/finance-revenue-mcp.yaml` | Sample plugin: 3 tools, restricted to `MCP-Users-Finance` group |

### Guardrails

| File | Description |
|---|---|
| `gateway/app/guardrails/middleware.py` | `_RateLimiter` (token-bucket per user), `validate_tool_input()` (JSON schema), `audit_log_invocation()` (structured log), `GuardrailsMiddleware` |

### Tool Dispatch

| File | Description |
|---|---|
| `gateway/app/tools/builtin_ai.py` | `call_builtin_ai()` — calls Azure OpenAI with 429 retry |
| `gateway/app/tools/forwarder.py` | `forward_to_backend()` — proxies to backend via httpx |
| `gateway/app/tools/container.py` | Docker container lifecycle manager (ToolHive pattern) |
| `gateway/app/tools/dispatch.py` | `dispatch()` — routes to builtin / container / forward based on plugin type |

### Routes

| File | Endpoint |
|---|---|
| `gateway/app/routes/capabilities.py` | `GET /api/v1/mcp/capabilities` — returns tools filtered by user groups |
| `gateway/app/routes/invoke.py` | `POST /api/v1/mcp/tools/{tool_id}/invoke` — full auth + guardrails pipeline |
| `gateway/app/routes/health.py` | `GET /health`, `GET /ready` |
| `gateway/app/routes/plugins.py` | Updated to use new `Plugin` model |

### Tests (31 tests, 31 passing)

| File | Coverage |
|---|---|
| `gateway/tests/conftest.py` | Shared fixtures: test plugin dir, dev client, dev headers |
| `gateway/tests/test_auth_middleware.py` | Dev bypass, HS256 dev JWT, missing token → 401 |
| `gateway/tests/test_capabilities.py` | Group filtering, empty groups, all-visible tools |
| `gateway/tests/test_dispatch.py` | Builtin / forward / container routing |
| `gateway/tests/test_guardrails.py` | Rate limiter allow/block, valid input pass, audit log |
| `gateway/tests/test_invoke.py` | 404 unknown tool, builtin call, group auth, 502 on error |
| `gateway/tests/test_plugin_loader.py` | Load/skip/invalid YAML, get_tool, get_plugin, len |

## Key Design Decisions

- **YAML plugin manifests:** Operators add tools by dropping `.yaml` files — no code changes needed.
- **Group-based access control:** Each plugin declares `required_groups: [...]`; empty list = public. Enforced at both capabilities listing and invocation.
- **Dev mode bypass:** `AUTH_DEV_MODE=true` accepts literal `dev-token` or any HS256 JWT, enabling local development without Entra credentials.
- **Rate limiting is per-user per-tool:** Token bucket keyed by `(user_oid, tool_id)` to prevent a single user from flooding a slow tool.
- **No new auth library at gateway:** Token extraction from raw `Authorization` header — avoids FastAPI body-parsing conflict with `HTTPBearer` dependency injection.

## Bug Fixed During Implementation

`get_current_user` originally declared `credentials: HTTPAuthorizationCredentials | None = None` as a parameter. FastAPI interpreted this as a required request body field (not a `Depends`), causing 422 on all invocations. Fixed by removing the unused parameter — the token is read directly from `request.headers`.

## Test & Lint Status

```
AUTH_DEV_MODE=true python3 -m pytest tests/ -v   →  31 passed in 0.20s
python3 -m ruff check app/ tests/               →  All checks passed!
```
