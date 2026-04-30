"""Embedding node executor — calls ``app.langgraph.embeddings.call_embedding``.

Phase 3 / WS9 — Executor Workstream 1.

Promoted from STUB to BETA: a real LiteLLM ``aembedding`` wrapper backs this
executor, with the same stub-mode discipline as ``llmNode`` so tests stay
deterministic. Output mirrors the typed ``EmbeddingResponse``:

    {
        "embedding": [floats],
        "dimensions": int,
        "model": str,
        "token_usage": {"prompt": int, "total": int},
        "cost_usd": float,
        "latency_ms": float,
        "_stub": bool,    # only present when LLM_STUB_MODE=true
    }

Caveats (BETA gap):
  - One text per call. Batch embedding (``input=[text1, text2, ...]``) is not
    yet wired through the node API.
  - Tenant-aware routing is not applied — embeddings have no tenant model
    mapping today; isolation is upstream of this executor.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "text-embedding-3-small"


def _is_stub_mode() -> bool:
    return os.getenv("LLM_STUB_MODE", "").lower() == "true"


def _coerce_text(ctx: NodeContext) -> str | None:
    """Resolve the input text from config or upstream inputs.

    Resolution order:
      1. ``ctx.config["text"]`` — explicit configuration.
      2. ``ctx.inputs["text"]`` — upstream node bound to a "text" key.
      3. Single string upstream input — auto-unwrap when only one upstream
         step produced a string output.
    Returns ``None`` if no text can be resolved (caller then fails fast).
    """
    config = ctx.config
    cfg_text = config.get("text")
    if isinstance(cfg_text, str) and cfg_text:
        return cfg_text

    inputs = ctx.inputs or {}
    if isinstance(inputs.get("text"), str) and inputs["text"]:
        return inputs["text"]

    # Single-string upstream: e.g. {"step-1": "hello"} → "hello".
    if len(inputs) == 1:
        only = next(iter(inputs.values()))
        if isinstance(only, str) and only:
            return only

    return None


@register("embeddingNode")
class EmbeddingNodeExecutor(NodeExecutor):
    """Execute an embeddingNode: produce a vector embedding for input text."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.langgraph.embeddings import call_embedding  # noqa: PLC0415

        config = ctx.config
        model: str = config.get("model") or _DEFAULT_MODEL
        timeout_s: float = float(config.get("timeoutSeconds") or config.get("timeout_s") or 30.0)
        max_retries: int = int(
            config.get("maxRetries")
            if config.get("maxRetries") is not None
            else (config.get("max_retries") if config.get("max_retries") is not None else 2)
        )

        text = _coerce_text(ctx)
        if text is None:
            return NodeResult(
                status="failed",
                error="ValueError: embeddingNode requires non-empty 'text' input",
            )

        try:
            response = await call_embedding(
                text=text,
                model=model,
                timeout_s=timeout_s,
                max_retries=max_retries,
                metadata={"step_id": ctx.step_id, "node_type": ctx.node_type},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("embeddingNode.execute_error", exc_info=True)
            return NodeResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

        output: dict[str, Any] = {
            "embedding": response.vector,
            "dimensions": response.dimensions,
            "model": response.model_used,
            "token_usage": {
                "prompt": response.prompt_tokens,
                "total": response.total_tokens,
            },
            "cost_usd": response.cost_usd,
            "latency_ms": response.latency_ms,
        }
        if _is_stub_mode():
            output["_stub"] = True

        return NodeResult(
            status="completed",
            output=output,
            token_usage={
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": 0,
                "total_tokens": response.total_tokens,
            },
            cost_usd=response.cost_usd,
        )
