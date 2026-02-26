# WS-5 Model Router Enhancement — Implementation Report

## Summary

Extended the backend model router with Azure OpenAI integration: 429 retry logic,
auto-registration of Azure models in the DB, and a new embeddings endpoint.

## Files Changed

### `backend/app/config.py`
Added four Azure OpenAI configuration fields (all optional, sourced from env vars):
- `AZURE_OPENAI_ENDPOINT` — base URL for Azure OpenAI resource
- `AZURE_OPENAI_API_KEY` — API key (never hardcoded)
- `AZURE_OPENAI_MODEL` — chat model deployment name (default: `gpt-5.2-codex`)
- `AZURE_OPENAI_EMBEDDINGS_MODEL` — embeddings deployment name (default: `qrg-embedding-experimental`)

### `backend/app/services/router_service.py`
Added to the top of the module:

| Symbol | Purpose |
|---|---|
| `_AZURE_OPENAI_CHAT_URL` | Module constant — Azure chat completions URL |
| `_AZURE_OPENAI_EMBEDDINGS_URL` | Module constant — Azure embeddings URL |
| `_wait_with_backoff(attempt, retry_after)` | Async exponential backoff with jitter (base 1s, max 16s), honours `Retry-After` header |
| `call_azure_openai_with_retry(payload, url, api_key, max_budget_s)` | Calls Azure OpenAI with up to 3 retries on 429, 30s total budget, raises on other errors |
| `register_azure_openai_models()` | Idempotent DB upsert of `gpt-5.2-codex` and `qrg-embedding-experimental` entries |

All three symbols exported via `__all__`.

### `backend/app/routes/router.py`
- Added `EmbeddingsRequest` and `EmbeddingsResponse` Pydantic models
- Added `POST /api/v1/router/embeddings` endpoint:
  - Validates input has at least one text string
  - Calls `call_azure_openai_with_retry` against the embeddings URL
  - Returns base64-encoded embedding vectors and model name
  - Returns 503 if Azure credentials not configured

## Design Decisions

- **Retry budget over retry count:** A 30-second wall-clock budget prevents unbounded retries while still handling transient 429 bursts.
- **Idempotent model registration:** `register_azure_openai_models()` uses `get_or_create` semantics — safe to call on startup without migrations.
- **No new dependencies:** Uses `httpx` (already in requirements) and standard library only.

## Lint Status

`ruff check app/config.py app/services/router_service.py app/routes/router.py` → **All checks passed**
