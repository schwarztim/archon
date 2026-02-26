"""Built-in tool execution via Azure OpenAI."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

_RETRY_BASE_S = 1.0
_RETRY_MAX_S = 30.0
_RETRY_MAX_ATTEMPTS = 4


async def call_builtin_ai(
    tool_id: str,
    body: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Execute a tool via Azure OpenAI chat completions.

    The tool input is forwarded as a user message.  The model response is
    returned verbatim along with usage metadata.

    Raises :class:`RuntimeError` if Azure OpenAI is not configured.
    """
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx is required for built-in AI execution") from exc

    from app.config import get_settings

    settings = get_settings()
    api_key = settings.azure_openai_api_key
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    deployment = model or settings.azure_openai_model

    if not api_key:
        raise RuntimeError("AZURE_OPENAI_API_KEY not configured. Cannot execute built-in tool.")

    url = (
        f"{endpoint}/openai/deployments/{deployment}"
        "/chat/completions?api-version=2025-04-01-preview"
    )
    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You are executing tool '{tool_id}'. "
                    "Process the input and return a structured result."
                ),
            },
            {
                "role": "user",
                "content": str(body),
            },
        ],
        "max_tokens": 1024,
    }

    import asyncio
    import random

    last_exc: Exception | None = None
    spent_s = 0.0

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(_RETRY_MAX_ATTEMPTS):
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                )

                if resp.status_code == 429:
                    retry_after_str = resp.headers.get("Retry-After")
                    wait_s = _RETRY_BASE_S * (2**attempt)
                    if retry_after_str:
                        with contextlib.suppress(ValueError, TypeError):
                            wait_s = float(retry_after_str)
                    wait_s = min(wait_s, _RETRY_MAX_S)
                    jitter = wait_s * 0.1 * random.uniform(-1.0, 1.0)  # noqa: S311
                    actual_wait = max(0.0, wait_s + jitter)

                    logger.warning(
                        "builtin_ai_rate_limited",
                        extra={"attempt": attempt, "wait_s": round(actual_wait, 2)},
                    )
                    spent_s += actual_wait
                    await asyncio.sleep(actual_wait)
                    last_exc = Exception(f"429 rate limited after {spent_s:.1f}s")
                    continue

                resp.raise_for_status()
                data = resp.json()

                content = ""
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")

                return {
                    "tool_id": tool_id,
                    "result": content,
                    "model": data.get("model", deployment),
                    "usage": data.get("usage", {}),
                    "execution_mode": "builtin_ai",
                }

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429:
                    raise
                last_exc = exc

    raise last_exc or RuntimeError("All Azure OpenAI retry attempts exhausted")
