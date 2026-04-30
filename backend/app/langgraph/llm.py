"""LiteLLM wrapper for Archon agent LLM calls.

Provides a single async entry point ``call_llm`` that handles:
- Stub mode (``LLM_STUB_MODE=true``) for tests without API keys.
- Lazy import of litellm so the module loads in environments where the
  package may not yet be installed.
- Exponential-backoff retries on transient failures (timeout, 429, 5xx).
- Cost calculation via LiteLLM's built-in helper.
- Timing via ``time.perf_counter``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.tracing import add_event as _trace_event
from app.services.tracing import span as _trace_span

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """Structured result from a single LLM call."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None
    model_used: str
    latency_ms: float
    raw: dict[str, Any] | None = field(default=None)


# ---------------------------------------------------------------------------
# Stub mode
# ---------------------------------------------------------------------------

_STUB_MODE_ENV = "LLM_STUB_MODE"


def _is_stub_mode() -> bool:
    return os.getenv(_STUB_MODE_ENV, "").lower() == "true"


def _stub_response(prompt: str | list[dict], model: str) -> LLMResponse:
    """Return a deterministic fake response; never calls litellm."""
    prompt_str = str(prompt)[:80]
    return LLMResponse(
        content=f"[STUB] {prompt_str}",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_usd=0.0,
        model_used=f"{model}-stub",
        latency_ms=1.0,
        raw=None,
    )


# ---------------------------------------------------------------------------
# Retry helpers (no tenacity dependency — simple backoff loop)
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1  # seconds


def _is_transient(exc: BaseException) -> bool:
    """Return True for errors that merit a retry."""
    msg = str(exc).lower()
    transient_markers = ("timeout", "429", "rate limit", "503", "502", "500")
    return any(m in msg for m in transient_markers)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def call_llm(
    prompt: str | list[dict],
    model: str = "gpt-3.5-turbo",
    *,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    timeout_s: float = 60.0,
    api_key: str | None = None,
) -> LLMResponse:
    """Call an LLM via LiteLLM and return a structured ``LLMResponse``.

    Args:
        prompt: Either a plain-text string or a list of OpenAI-style chat
            message dicts (``[{"role": "user", "content": "..."}]``).
        model: LiteLLM model string (e.g. ``"gpt-3.5-turbo"``,
            ``"anthropic/claude-3-haiku"``, ``"azure/my-deployment"``).
        system: Optional system prompt. Prepended as a ``system`` role message
            when the call is made in chat format.
        max_tokens: Maximum completion tokens.
        temperature: Sampling temperature.
        timeout_s: Per-attempt timeout in seconds.
        api_key: API key override; when ``None`` LiteLLM resolves from env
            vars (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, etc.).

    Returns:
        ``LLMResponse`` with content, token counts, cost, model used, and
        wall-clock latency.

    Raises:
        Exception: Re-raises the last error after ``_MAX_ATTEMPTS`` attempts.
    """
    # W5.2 — provider span. Falls through to no-op when tracing is off.
    async with _trace_span(
        "llm.call",
        provider=_provider_for(model),
        model=model,
        requested_model=model,
        stub_mode=_is_stub_mode(),
    ):
        if _is_stub_mode():
            return _stub_response(prompt, model)
        return await _call_llm_real(
            prompt,
            model=model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
            api_key=api_key,
        )


async def _call_llm_real(
    prompt: str | list[dict],
    model: str,
    *,
    system: str | None,
    max_tokens: int,
    temperature: float,
    timeout_s: float,
    api_key: str | None,
) -> LLMResponse:
    """Real LiteLLM call path. Extracted so the tracing span wraps both
    the stub-mode short-circuit and the network path uniformly."""
    # Lazy import so the module is importable without litellm installed
    import litellm  # noqa: PLC0415

    # Build messages list
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})

    if isinstance(prompt, str):
        messages.append({"role": "user", "content": prompt})
    else:
        # Caller already provided full chat history
        messages.extend(prompt)

    opts: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout_s,
    }
    if api_key:
        opts["api_key"] = api_key

    last_exc: BaseException | None = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            wait = _BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                "llm.retry",
                extra={"attempt": attempt, "wait_s": wait, "error": str(last_exc)},
            )
            await asyncio.sleep(wait)

        t0 = time.perf_counter()
        try:
            response = await litellm.acompletion(**opts)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            # Extract content
            content: str = response.choices[0].message.content or ""

            # Token usage
            usage = response.usage or {}
            prompt_tokens: int = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens: int = getattr(usage, "completion_tokens", 0) or 0
            total_tokens: int = getattr(usage, "total_tokens", 0) or (
                prompt_tokens + completion_tokens
            )

            # Cost via LiteLLM helper
            try:
                cost_usd: float | None = litellm.completion_cost(
                    completion_response=response
                )
            except Exception:  # noqa: BLE001
                cost_usd = None

            return LLMResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                model_used=response.model or model,
                latency_ms=latency_ms,
                raw=response.dict() if hasattr(response, "dict") else None,
            )

        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_transient(exc):
                # Non-transient — don't retry
                raise

    # All attempts exhausted
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 4 / WS10 — Routed LLM call
# ---------------------------------------------------------------------------

# These imports are heavy (SQLAlchemy + dataclass machinery) so they live
# at module bottom, only resolved when ``call_llm_routed`` is first invoked.

from datetime import datetime, timezone  # noqa: E402
from uuid import UUID  # noqa: E402


async def call_llm_routed(
    *,
    tenant_id: UUID,
    messages: list[dict],
    requested_model: str | None = None,
    capability_required: list[str] | None = None,
    session: Any = None,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    timeout_s: float = 60.0,
    api_key: str | None = None,
) -> tuple[LLMResponse, "Any"]:
    """Route + call an LLM in one shot.

    Wraps ``call_llm`` with routing decision + provider fallback:

      1. ``router_service.route_request`` picks a model + provider for
         this tenant, capability set, and current circuit state.
      2. ``call_llm`` is invoked with the chosen model.
      3. On failure: provider health is updated (failure recorded) and
         the next model in the fallback chain is tried.  The decision's
         ``reason`` is rewritten to ``fallback_after_<provider>_failed``.
      4. The function returns both the final ``LLMResponse`` and the
         (possibly mutated) ``Phase4RoutingDecision``.

    Stub mode (``LLM_STUB_MODE=true``) bypasses routing and providers
    entirely and returns a synthetic decision with ``reason="stub_mode"``.

    Args:
      tenant_id:           Tenant scope.
      messages:            OpenAI-style chat messages.
      requested_model:     Caller's preferred model id; honored if eligible.
      capability_required: e.g. ``["vision"]`` — passed to the router.
      session:             AsyncSession used by the router for tenant
                           model lookups; may be ``None`` in stub mode.
      system, max_tokens, temperature, timeout_s, api_key: forwarded to
        ``call_llm``.

    Returns:
      ``(LLMResponse, Phase4RoutingDecision)``.

    Raises:
      Re-raises the last LLM error if every model in the chain fails.
    """
    # Local imports to avoid circular import on module load
    from app.services import provider_health  # noqa: PLC0415
    from app.services.router_service import (  # noqa: PLC0415
        Phase4RoutingDecision,
        route_request,
    )

    # ── Stub mode short-circuit ────────────────────────────────────
    if _is_stub_mode():
        decision = Phase4RoutingDecision(
            model=requested_model or "gpt-3.5-turbo",
            provider="stub",
            reason="stub_mode",
            fallback_chain=[requested_model or "gpt-3.5-turbo"],
            estimated_cost_usd=0.0,
            estimated_latency_ms=1.0,
            decision_at=datetime.now(timezone.utc),
        )
        response = _stub_response(messages, decision.model)
        return response, decision

    # Estimate input tokens for cost projection (rough: 4 chars / token)
    msg_text_len = sum(len(str(m.get("content") or "")) for m in (messages or []))
    if system:
        msg_text_len += len(system)
    estimated_input_tokens = max(1, msg_text_len // 4)
    estimated_output_tokens = max_tokens

    decision = await route_request(
        session,
        tenant_id=tenant_id,
        requested_model=requested_model,
        capability_required=list(capability_required or []),
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
    )

    chain: list[str] = list(decision.fallback_chain or [])
    if decision.model and decision.model not in chain:
        chain = [decision.model] + chain

    if not chain:
        raise RuntimeError(
            "call_llm_routed: no eligible model returned by route_request "
            f"(tenant_id={tenant_id}, reason={decision.reason!r})"
        )

    # Phase 5 — defer metrics imports so cold-start LLM call paths
    # never pay middleware import cost. Wrapped to fail silent.
    def _emit_metrics_safe(fn_name: str, *args, **kwargs) -> None:
        try:
            from app.middleware import metrics_middleware as _m  # noqa: PLC0415

            getattr(_m, fn_name)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — emission must never raise
            logger.debug("llm metric emit %s failed: %s", fn_name, exc)

    last_exc: BaseException | None = None
    previous_provider: str | None = None
    for idx, candidate_model in enumerate(chain):
        candidate_provider = (
            decision.provider if idx == 0 else _provider_for(candidate_model)
        )
        # Phase 5: a fallback fires whenever idx > 0. Record the
        # transition before we attempt the next provider so the metric
        # captures the from→to even if the next attempt also fails.
        if idx > 0 and previous_provider:
            _emit_metrics_safe(
                "record_provider_fallback",
                from_provider=previous_provider,
                to_provider=candidate_provider,
                reason=decision.reason or "provider_failed",
            )

        t0 = time.perf_counter()
        try:
            response = await call_llm(
                messages,
                model=candidate_model,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=timeout_s,
                api_key=api_key,
            )
            latency_s = time.perf_counter() - t0
            await provider_health.record_provider_call(
                session,
                candidate_provider,
                success=True,
                latency_ms=latency_s * 1000.0,
            )
            decision.model = candidate_model
            decision.provider = candidate_provider

            # Phase 5: provider latency + token usage + cost.
            tenant_id_str = str(tenant_id) if tenant_id else "unknown"
            _emit_metrics_safe(
                "record_provider_latency",
                latency_s,
                provider=candidate_provider,
                model=candidate_model,
                status="success",
            )
            if response.prompt_tokens:
                _emit_metrics_safe(
                    "record_token_usage",
                    tenant_id_str,
                    candidate_model,
                    "prompt",
                    int(response.prompt_tokens),
                    provider=candidate_provider,
                )
            if response.completion_tokens:
                _emit_metrics_safe(
                    "record_token_usage",
                    tenant_id_str,
                    candidate_model,
                    "completion",
                    int(response.completion_tokens),
                    provider=candidate_provider,
                )
            if response.cost_usd is not None:
                _emit_metrics_safe(
                    "record_cost",
                    tenant_id_str,
                    candidate_model,
                    float(response.cost_usd),
                    provider=candidate_provider,
                )
            return response, decision
        except Exception as exc:  # noqa: BLE001
            latency_s = time.perf_counter() - t0
            last_exc = exc
            await provider_health.record_provider_call(
                session,
                candidate_provider,
                success=False,
                latency_ms=latency_s * 1000.0,
                error=str(exc),
            )
            # Phase 5: emit provider latency on the failure path too so
            # error budgets and percentile latencies stay accurate.
            _emit_metrics_safe(
                "record_provider_latency",
                latency_s,
                provider=candidate_provider,
                model=candidate_model,
                status="failure",
            )
            failed_provider = candidate_provider
            decision.reason = f"fallback_after_{failed_provider}_failed"
            previous_provider = failed_provider
            # W5.2 — record fallback as a span event so the trace shows
            # which provider/model failed and what we're trying next.
            _trace_event(
                "llm.fallback",
                failed_provider=failed_provider,
                failed_model=candidate_model,
                next_index=idx + 1,
                error=str(exc)[:200],
            )
            logger.warning(
                "call_llm_routed.provider_failed",
                extra={
                    "provider": failed_provider,
                    "model": candidate_model,
                    "error": str(exc),
                },
            )
            continue

    raise last_exc or RuntimeError(
        "call_llm_routed: all candidates in fallback chain failed"
    )


def _provider_for(model_id: str) -> str:
    """Best-effort guess of the provider name from a model id string.

    Used only for fallback-chain telemetry when the router did not return
    a per-candidate provider.  Patterns are deliberately permissive — a
    miss simply records the failure under the model id itself.
    """
    if not model_id:
        return ""
    lower = model_id.lower()
    if lower.startswith(("gpt-", "openai/", "o1", "o3", "o4")):
        return "openai"
    if lower.startswith(("claude", "anthropic/")):
        return "anthropic"
    if lower.startswith(("gemini", "google/")):
        return "google"
    if lower.startswith(("mistral", "mistralai/")):
        return "mistral"
    if "/" in lower:
        return lower.split("/", 1)[0]
    return model_id
