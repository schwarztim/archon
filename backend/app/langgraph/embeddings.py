"""LiteLLM async embedding wrapper.

Mirror of ``backend/app/langgraph/llm.py`` — keeps the same retry / timeout /
stub-mode discipline so the embedding node executor can be production-classed
without bringing its own provider semantics.

Public surface
--------------

``EmbeddingResponse``
    Typed result dataclass returned by every call.
``call_embedding``
    Async function used by ``app.services.node_executors.embedding``.

Stub mode
---------

When ``LLM_STUB_MODE=true`` (or any case-variant of ``"true"``) is set in the
environment, ``call_embedding`` short-circuits and returns a deterministic
synthesised vector seeded from ``sha256(text + model)``. Two calls with the
same ``text`` + ``model`` produce the **same** vector — bit-for-bit
reproducibility per ADR-001's snapshot philosophy. Vectors are L2-normalised
so cosine-similarity tests have a stable expected behaviour.

Vector length defaults to the ``_KNOWN_DIMENSIONS`` entry for the model and
falls back to 1536 (matching OpenAI ``text-embedding-3-small``) when the
model is unknown.

The real path lazy-imports ``litellm`` so this module loads cleanly in
environments where the package is not installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import struct
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingResponse:
    """Structured result from a single embedding call."""

    vector: list[float]
    dimensions: int
    prompt_tokens: int
    total_tokens: int
    cost_usd: float
    model_used: str
    latency_ms: float


# ---------------------------------------------------------------------------
# Known model dimensions (for stub-mode synthesis)
#
# Real provider responses always carry their own dimension; this table is
# only consulted when LLM_STUB_MODE=true so the synthesised vector matches
# the dimensionality the caller would have received in production.
# ---------------------------------------------------------------------------

_KNOWN_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "voyage-3": 1024,
    # ``stub`` is only used when LLM_STUB_MODE=true and the model is unknown.
    "stub": 1536,
}

_DEFAULT_DIMENSIONS = 1536


# ---------------------------------------------------------------------------
# Stub mode
# ---------------------------------------------------------------------------

_STUB_MODE_ENV = "LLM_STUB_MODE"


def _is_stub_mode() -> bool:
    return os.getenv(_STUB_MODE_ENV, "").lower() == "true"


def _resolve_dimensions(model: str) -> int:
    """Return the dimensions for *model*, defaulting to 1536 on miss."""
    return _KNOWN_DIMENSIONS.get(model, _DEFAULT_DIMENSIONS)


def _stub_vector(text: str, model: str, dimensions: int) -> list[float]:
    """Deterministic pseudo-vector seeded from sha256(text + model).

    Algorithm:
      1. Hash ``text + "::" + model`` repeatedly to produce ``dimensions * 4``
         bytes (each float consumes one 4-byte little-endian uint32 window).
      2. Map each window to ``[-1, 1]`` via ``(u32 / UINT32_MAX) * 2 - 1``.
      3. L2-normalise the result so cosine-similarity tests have a stable
         expected behaviour.
    """
    if dimensions <= 0:
        return []

    # Build enough bytes by chaining hashes so the same (text, model) pair
    # always produces the same byte stream regardless of dimensions.
    bytes_needed = dimensions * 4
    seed = f"{text}::{model}".encode("utf-8")
    chunks: list[bytes] = []
    counter = 0
    while sum(len(c) for c in chunks) < bytes_needed:
        h = hashlib.sha256(seed + counter.to_bytes(4, "little")).digest()
        chunks.append(h)
        counter += 1
    raw = b"".join(chunks)[:bytes_needed]

    # Convert to floats in [-1, 1].
    floats: list[float] = []
    uint32_max = float(0xFFFFFFFF)
    for i in range(dimensions):
        (u,) = struct.unpack_from("<I", raw, i * 4)
        floats.append((u / uint32_max) * 2.0 - 1.0)

    # L2-normalise.
    norm = math.sqrt(sum(f * f for f in floats))
    if norm == 0.0:
        # Degenerate input — return a unit vector along axis 0.
        return [1.0] + [0.0] * (dimensions - 1)
    return [f / norm for f in floats]


def _stub_response(text: str, model: str) -> EmbeddingResponse:
    """Return a deterministic fake embedding response; never calls litellm."""
    dims = _resolve_dimensions(model)
    vec = _stub_vector(text, model, dims)
    # Token count: rough character-based estimate (4 chars / token), min 1.
    prompt_tokens = max(1, len(text) // 4)
    return EmbeddingResponse(
        vector=vec,
        dimensions=dims,
        prompt_tokens=prompt_tokens,
        total_tokens=prompt_tokens,
        cost_usd=0.0,
        model_used=f"{model}-stub",
        latency_ms=1.0,
    )


# ---------------------------------------------------------------------------
# Retry helpers (mirror llm.py: simple backoff loop, no tenacity dependency)
# ---------------------------------------------------------------------------


def _is_transient(exc: BaseException) -> bool:
    """Return True for errors that merit a retry.

    Pattern matches llm.py's transient-error classifier and additionally
    catches ``TimeoutError`` and ``ConnectionError`` by class so callers
    can rely on the exact retry surface documented in ``call_embedding``.
    """
    if isinstance(exc, (TimeoutError, ConnectionError, asyncio.TimeoutError)):
        return True
    msg = str(exc).lower()
    transient_markers = ("timeout", "429", "rate limit", "503", "502", "500")
    return any(m in msg for m in transient_markers)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def call_embedding(
    *,
    text: str,
    model: str = "text-embedding-3-small",
    timeout_s: float = 30.0,
    max_retries: int = 2,
    metadata: dict[str, Any] | None = None,
) -> EmbeddingResponse:
    """Compute an embedding for *text* using *model*.

    Args:
        text: The string to embed. Non-string input is coerced via ``str()``.
        model: LiteLLM-compatible embedding model id (e.g.
            ``"text-embedding-3-small"``, ``"voyage-3"``).
        timeout_s: Per-attempt timeout in seconds passed to LiteLLM.
        max_retries: Number of additional attempts after the first failure.
            Total attempts = ``max_retries + 1``. Only transient errors
            (TimeoutError, ConnectionError, 429/5xx) trigger retries.
        metadata: Optional structured logging context. Forwarded into the
            log records so downstream log aggregators can correlate calls
            with run/step identifiers.

    Returns:
        ``EmbeddingResponse`` with vector, dimensions, token usage, cost,
        wall-clock latency, and the model id used.

    Raises:
        Exception: Re-raises the last error after exhausting retries.
            Class name is preserved so the dispatcher's ``RetryPolicy``
            can classify retryability via ``type(exc).__name__``.
    """
    log_extra = dict(metadata or {})
    log_extra.update({"model": model, "stub_mode": _is_stub_mode()})

    if _is_stub_mode():
        logger.debug("embedding.call.stub", extra=log_extra)
        return _stub_response(text, model)

    return await _call_embedding_real(
        text=text,
        model=model,
        timeout_s=timeout_s,
        max_retries=max_retries,
        log_extra=log_extra,
    )


async def _call_embedding_real(
    *,
    text: str,
    model: str,
    timeout_s: float,
    max_retries: int,
    log_extra: dict[str, Any],
) -> EmbeddingResponse:
    """Real LiteLLM call path with bounded retry on transient failures."""
    # Lazy import so the module is importable without litellm installed.
    import litellm  # noqa: PLC0415

    total_attempts = max(1, max_retries + 1)
    last_exc: BaseException | None = None

    for attempt in range(total_attempts):
        if attempt > 0:
            wait = float(2 ** (attempt - 1))
            logger.warning(
                "embedding.retry",
                extra={
                    **log_extra,
                    "attempt": attempt,
                    "wait_s": wait,
                    "error": str(last_exc),
                },
            )
            await asyncio.sleep(wait)

        t0 = time.perf_counter()
        try:
            response = await litellm.aembedding(
                model=model,
                input=[text],
                timeout=timeout_s,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0

            # Extract vector from the first (and only) item.
            data = _extract_data(response)
            if not data:
                raise RuntimeError(
                    f"litellm.aembedding returned no data for model={model!r}"
                )
            first = data[0]
            vector = list(_get(first, "embedding", []))
            dimensions = len(vector)

            # Token usage
            usage = _get(response, "usage", None) or {}
            prompt_tokens = int(_get(usage, "prompt_tokens", 0) or 0)
            total_tokens = int(_get(usage, "total_tokens", prompt_tokens) or 0)

            # Cost via LiteLLM helper (silently degrade on miss)
            try:
                cost_usd = float(
                    litellm.completion_cost(completion_response=response) or 0.0
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("embedding.cost_calc_failed: %s", exc)
                cost_usd = 0.0

            model_used = str(_get(response, "model", model) or model)

            logger.info(
                "embedding.call.success",
                extra={
                    **log_extra,
                    "dimensions": dimensions,
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": latency_ms,
                    "model_used": model_used,
                },
            )

            return EmbeddingResponse(
                vector=vector,
                dimensions=dimensions,
                prompt_tokens=prompt_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                model_used=model_used,
                latency_ms=latency_ms,
            )

        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "embedding.call.error",
                extra={
                    **log_extra,
                    "attempt": attempt,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )
            if not _is_transient(exc):
                # Non-transient — propagate immediately so RetryPolicy
                # can classify by class name.
                raise

    # All attempts exhausted
    assert last_exc is not None  # narrow for type-checkers
    raise last_exc


# ---------------------------------------------------------------------------
# Response-shape helpers (litellm returns a pydantic-ish object; tests pass
# plain dicts/MagicMocks — handle both uniformly).
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute-or-key accessor; mirrors how litellm responses behave."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_data(response: Any) -> list[Any]:
    """Pull the ``data`` array off a litellm embedding response."""
    data = _get(response, "data", None)
    if data is None:
        return []
    return list(data)


__all__ = [
    "EmbeddingResponse",
    "call_embedding",
]
