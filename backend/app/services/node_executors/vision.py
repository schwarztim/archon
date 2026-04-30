"""Vision node executor — multi-modal LLM call with image + text input.

Phase 3 / WS9 — Executor Workstream 3.

Promoted from STUB to BETA: a real ``call_llm`` wrapper with OpenAI-style
multi-modal messaging backs this executor, with the same stub-mode discipline
as ``llmNode`` / ``embeddingNode`` / ``structuredOutputNode`` so tests stay
deterministic.

Multi-modal message shape
-------------------------
LiteLLM forwards OpenAI-style multi-modal content. A single user message is
constructed with ``content`` as a list of parts::

    [
        {"type": "text", "text": "<prompt>"},
        {"type": "image_url", "image_url": {"url": "<url>", "detail": "auto"}},
    ]

The URL is either an HTTPS image URL (e.g. ``https://.../cat.png``) or a
``data:image/<mime>;base64,<b64>`` URI. When the caller supplies raw base64
via ``image_base64``, the executor wraps it as a data URI with
``image_mime`` (default ``image/png``).

Step config schema
------------------
- ``prompt``        : str  — required text instruction.
- ``image_url``     : str  — alternative to image_base64; HTTP(S) or data URI.
- ``image_base64``  : str  — alternative to image_url; raw base64 (wrapped).
- ``image_mime``    : str  — MIME type used when wrapping base64; default
                             ``image/png``.
- ``model``         : str  — vision-capable model (default ``gpt-4o-mini``).
- ``detail``        : str  — ``"low" | "high" | "auto"`` (default ``"auto"``).
- ``system``        : str  — optional system prompt.
- ``max_tokens``    : int  — default 1024.
- ``temperature``   : float — default 0.0.

Stub mode (``LLM_STUB_MODE=true``)
----------------------------------
Synthesises a deterministic vision-response string seeded from
``sha256(prompt + image_id_hash + model)``. The synthesised string never
embeds the URL or base64 content — only the truncated hash — so trace logs
cannot leak provided imagery.

Output shape (success)
----------------------

    {
        "content": str,           # model's text response
        "model": str,             # provider model id (with -stub suffix in stub mode)
        "image_described": bool,  # always True (we sent an image)
        "image_id_hash": str,     # sha256[:16] for traceability — never URL/base64
        "token_usage": {"prompt": int, "completion": int, "total": int},
        "cost_usd": float | None,
        "latency_ms": float,
        "_stub": bool,            # only present in stub mode
    }

Failure modes
-------------
- Missing ``prompt`` → status="failed", error_code="missing_prompt".
- Missing both ``image_url`` and ``image_base64`` → status="failed",
  error_code="missing_image".
- ``call_llm`` raises → status="failed", error string names the exception
  class so the dispatcher's RetryPolicy can classify by class name.

Caveats (BETA gap)
------------------
  - Single image per call. Batched multi-image input is not yet wired.
  - No image preprocessing / resize / format conversion. The bytes the
    caller hands in are the bytes the provider sees.
  - Streaming is not supported. The node always waits for the full response
    before returning.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_DETAIL = "auto"
_DEFAULT_MIME = "image/png"


def _is_stub_mode() -> bool:
    return os.getenv("LLM_STUB_MODE", "").lower() == "true"


def _image_id_hash(image_url: str | None, image_base64: str | None) -> str:
    """Return sha256[:16] over the image identifier.

    The hash uses the URL when present, else a short prefix of the base64
    payload. The full base64 is never hashed — that would force the entire
    payload through hashlib on every call. The 256-character prefix is
    sufficient to discriminate distinct images while keeping the cost
    bounded.

    The hash is what surfaces in ``output["image_id_hash"]`` for trace /
    audit purposes — the URL or base64 itself MUST NOT appear in any
    output field, by design.
    """
    if image_url:
        seed = f"url:{image_url}"
    elif image_base64:
        seed = f"b64:{image_base64[:256]}"
    else:
        seed = "none"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _resolve_image_payload(config: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (image_url, image_base64) from config; either may be None."""
    raw_url = config.get("image_url") or config.get("imageUrl")
    raw_b64 = config.get("image_base64") or config.get("imageBase64")
    image_url = raw_url if isinstance(raw_url, str) and raw_url.strip() else None
    image_base64 = raw_b64 if isinstance(raw_b64, str) and raw_b64.strip() else None
    return image_url, image_base64


def _wrap_base64_as_data_uri(image_base64: str, mime: str) -> str:
    """Wrap raw base64 as a ``data:<mime>;base64,<b64>`` URI."""
    return f"data:{mime};base64,{image_base64}"


def _build_multimodal_message(
    *,
    prompt: str,
    image_url_or_data_uri: str,
    detail: str,
) -> dict[str, Any]:
    """Build the OpenAI-style user message with text + image_url parts."""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": image_url_or_data_uri,
                    "detail": detail,
                },
            },
        ],
    }


def _stub_content(prompt: str, image_id_hash: str, model: str) -> str:
    """Synthesise a deterministic vision-response string.

    The string never embeds the URL or base64 content — only the prompt
    and the truncated image_id_hash — so logs cannot leak the image.
    """
    seed = f"{prompt}\x1e{image_id_hash}\x1e{model}".encode()
    digest = hashlib.sha256(seed).hexdigest()[:16]
    return f"[STUB-VISION:{digest}] described image {image_id_hash} for prompt: {prompt[:60]}"


@register("visionNode")
class VisionNodeExecutor(NodeExecutor):
    """Execute a visionNode: multi-modal LLM call with prompt + image."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.langgraph.llm import call_llm  # noqa: PLC0415

        config = ctx.config

        # ── Required: prompt ──────────────────────────────────────────
        prompt = config.get("prompt") or config.get("userPrompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return NodeResult(
                status="failed",
                error="ValueError: visionNode requires non-empty 'prompt' in config",
                output={"error_code": "missing_prompt"},
            )

        # ── Required: image_url XOR image_base64 ──────────────────────
        image_url, image_base64 = _resolve_image_payload(config)
        if not image_url and not image_base64:
            return NodeResult(
                status="failed",
                error="ValueError: visionNode requires either 'image_url' or 'image_base64' in config",
                output={"error_code": "missing_image"},
            )

        # ── Optional: model / detail / mime / system / token controls ─
        model: str = config.get("model") or _DEFAULT_MODEL
        detail: str = config.get("detail") or _DEFAULT_DETAIL
        image_mime: str = config.get("image_mime") or config.get("imageMime") or _DEFAULT_MIME
        system: str | None = config.get("system") or config.get("systemPrompt")
        max_tokens: int = int(config.get("max_tokens") or config.get("maxTokens") or 1024)
        temperature: float = float(
            config.get("temperature") if config.get("temperature") is not None else 0.0
        )

        # Compute image identifier hash for traceability. This is what the
        # output surfaces — never the URL or base64 itself.
        img_hash = _image_id_hash(image_url, image_base64)

        # Resolve the URL string the provider receives. http(s):// / data:
        # URIs are forwarded as-is; raw base64 is wrapped.
        if image_url:
            url_for_provider = image_url
        else:
            assert image_base64 is not None  # narrowed by guard above
            url_for_provider = _wrap_base64_as_data_uri(image_base64, image_mime)

        user_message = _build_multimodal_message(
            prompt=prompt,
            image_url_or_data_uri=url_for_provider,
            detail=detail,
        )

        # In stub mode, synthesise a deterministic content string but still
        # call call_llm so token / cost / latency stay consistent with the
        # other BETA nodes.
        try:
            response = await call_llm(
                [user_message],
                model=model,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("visionNode.call_llm_error", exc_info=True)
            # Preserve exception class name so RetryPolicy can classify it.
            return NodeResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

        if _is_stub_mode():
            content = _stub_content(prompt, img_hash, model)
        else:
            content = response.content

        output: dict[str, Any] = {
            "content": content,
            "model": response.model_used,
            "image_described": True,
            "image_id_hash": img_hash,
            "token_usage": {
                "prompt": response.prompt_tokens,
                "completion": response.completion_tokens,
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
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
            },
            cost_usd=response.cost_usd,
        )
