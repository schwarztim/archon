"""visionNode contract tests — Phase 3 / WS9 (Executor Workstream 3).

Coverage dimensions (mirrors test_embedding_node_contract.py and
test_structured_output_node_contract.py):

1.  missing prompt           — config without ``prompt`` → status="failed".
2.  missing image            — config without ``image_url`` AND
                               ``image_base64`` → status="failed".
3.  image_url path           — call_llm receives a multi-modal message with
                               an ``image_url`` part containing the URL.
4.  image_base64 path        — raw base64 is wrapped as a data URI with the
                               configured MIME type before forwarding.
5.  default model            — when config omits ``model``, the executor
                               uses ``gpt-4o-mini``.
6.  config model override    — ``config['model']`` is honoured.
7.  default detail           — when config omits ``detail``, ``"auto"`` is
                               passed to the provider.
8.  detail override          — ``config['detail']`` is forwarded.
9.  stub determinism         — same (prompt, image_id, model) → same output.
10. stub variability         — different image yields different content.
11. real-mode call           — call_llm is invoked with the multi-modal
                               message; output mirrors LLMResponse.
12. retry classification     — call_llm raises → status="failed", error
                               string names the exception class so
                               RetryPolicy can classify it.
13. token usage              — populated on the success path.
14. cost_usd                 — populated on the success path.
15. image_id_hash safety     — the URL / base64 NEVER appear in output;
                               only the sha256[:16] hash is surfaced.
16. registry classification  — visionNode is classified BETA.
17. production gate          — assert_node_runnable does not raise after
                               promotion.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

# Tests run in stub mode by default so they are deterministic regardless of
# whether the host has provider credentials. The package conftest also sets
# this; the duplicate ``setdefault`` is defensive when the file is run alone.
os.environ.setdefault("LLM_STUB_MODE", "true")

from app.langgraph.llm import LLMResponse  # noqa: E402
from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from app.services.node_executors._stub_block import assert_node_runnable  # noqa: E402
from app.services.node_executors.status_registry import (  # noqa: E402
    NODE_STATUS,
    NodeStatus,
)
from tests.test_node_executors import make_ctx  # noqa: E402


def _fake_llm_response(
    content: str = "a photo of a cat",
    *,
    model: str = "gpt-4o-mini",
) -> LLMResponse:
    return LLMResponse(
        content=content,
        prompt_tokens=42,
        completion_tokens=17,
        total_tokens=59,
        cost_usd=0.000789,
        model_used=model,
        latency_ms=4.2,
    )


# A small valid base64 PNG-ish blob for tests. Not a real image — the
# executor never decodes it; it only wraps as a data URI.
_FAKE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEX///+nxBvIAAAACklEQVQI12NgAAAAAgAB4iG8MwAAAABJRU5ErkJggg=="
_SAMPLE_URL = "https://example.com/cat.png"


def _extract_user_message(captured_call: dict) -> dict:
    """Pull the first (and only) user message dict from a captured call."""
    prompt = captured_call.get("prompt")
    assert isinstance(prompt, list), f"expected message list, got {type(prompt)}"
    assert len(prompt) == 1, f"expected 1 message, got {len(prompt)}"
    msg = prompt[0]
    assert isinstance(msg, dict)
    assert msg.get("role") == "user"
    return msg


def _extract_image_url_part(user_message: dict) -> dict:
    """Pull the ``image_url`` content part from a multi-modal user message."""
    content = user_message.get("content")
    assert isinstance(content, list), f"expected multi-modal list, got {type(content)}"
    image_parts = [p for p in content if isinstance(p, dict) and p.get("type") == "image_url"]
    assert len(image_parts) == 1, f"expected 1 image_url part, got {len(image_parts)}"
    return image_parts[0]


def _extract_text_part(user_message: dict) -> dict:
    """Pull the ``text`` content part from a multi-modal user message."""
    content = user_message.get("content")
    assert isinstance(content, list)
    text_parts = [p for p in content if isinstance(p, dict) and p.get("type") == "text"]
    assert len(text_parts) == 1, f"expected 1 text part, got {len(text_parts)}"
    return text_parts[0]


# ---------------------------------------------------------------------------
# 1. missing prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_prompt_returns_failed():
    """No prompt in config → status=failed, ValueError-shaped error."""
    ctx = make_ctx("visionNode", config={"image_url": _SAMPLE_URL})
    result = await NODE_EXECUTORS["visionNode"].execute(ctx)
    assert result.status == "failed"
    assert result.error is not None
    assert "ValueError" in result.error
    assert "prompt" in result.error.lower()
    assert result.output.get("error_code") == "missing_prompt"


# ---------------------------------------------------------------------------
# 2. missing image
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_image_returns_failed():
    """No image_url AND no image_base64 → status=failed."""
    ctx = make_ctx("visionNode", config={"prompt": "describe this"})
    result = await NODE_EXECUTORS["visionNode"].execute(ctx)
    assert result.status == "failed"
    assert result.error is not None
    assert "ValueError" in result.error
    assert "image" in result.error.lower()
    assert result.output.get("error_code") == "missing_image"


# ---------------------------------------------------------------------------
# 3. image_url path builds multi-modal message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_url_path_builds_multimodal_message(monkeypatch):
    """Real mode + image_url: call_llm receives a [text, image_url] message."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    captured: dict = {}

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        captured["prompt"] = prompt
        captured["model"] = model
        return _fake_llm_response(model=model)

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "describe this", "image_url": _SAMPLE_URL, "model": "gpt-4o-mini"},
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    msg = _extract_user_message(captured)
    img_part = _extract_image_url_part(msg)
    txt_part = _extract_text_part(msg)
    # The forwarded URL is the original https URL (not wrapped).
    assert img_part["image_url"]["url"] == _SAMPLE_URL
    assert txt_part["text"] == "describe this"


# ---------------------------------------------------------------------------
# 4. image_base64 path wraps in data URI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_base64_path_wraps_in_data_uri(monkeypatch):
    """Real mode + image_base64: payload is wrapped as data:<mime>;base64,..."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    captured: dict = {}

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        captured["prompt"] = prompt
        return _fake_llm_response(model=model)

    ctx = make_ctx(
        "visionNode",
        config={
            "prompt": "describe this",
            "image_base64": _FAKE_B64,
            "image_mime": "image/jpeg",
            "model": "gpt-4o-mini",
        },
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    msg = _extract_user_message(captured)
    img_part = _extract_image_url_part(msg)
    forwarded_url = img_part["image_url"]["url"]
    assert forwarded_url.startswith("data:image/jpeg;base64,"), (
        f"expected data URI prefix, got {forwarded_url[:40]!r}"
    )
    assert _FAKE_B64 in forwarded_url


# ---------------------------------------------------------------------------
# 5. default model used when config omits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_model_used_when_config_omits(monkeypatch):
    """When config has no ``model``, the default is gpt-4o-mini."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    captured: dict = {}

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        captured["model"] = model
        return _fake_llm_response(model=model)

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "describe", "image_url": _SAMPLE_URL},
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    assert captured["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 6. config model override used when present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_model_override_used_when_present(monkeypatch):
    """``config['model']`` is honoured by the executor."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    captured: dict = {}

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        captured["model"] = model
        return _fake_llm_response(model=model)

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "go", "image_url": _SAMPLE_URL, "model": "gpt-4o"},
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    assert captured["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# 7. default detail is "auto"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_detail_is_auto(monkeypatch):
    """No detail in config → "auto" is forwarded inside the image_url part."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    captured: dict = {}

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        captured["prompt"] = prompt
        return _fake_llm_response(model=model)

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "go", "image_url": _SAMPLE_URL},
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    msg = _extract_user_message(captured)
    img_part = _extract_image_url_part(msg)
    assert img_part["image_url"]["detail"] == "auto"


# ---------------------------------------------------------------------------
# 8. detail override passed to llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_override_passed_to_llm(monkeypatch):
    """config['detail'] = 'high' is forwarded inside the image_url part."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    captured: dict = {}

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        captured["prompt"] = prompt
        return _fake_llm_response(model=model)

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "go", "image_url": _SAMPLE_URL, "detail": "high"},
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    msg = _extract_user_message(captured)
    img_part = _extract_image_url_part(msg)
    assert img_part["image_url"]["detail"] == "high"


# ---------------------------------------------------------------------------
# 9. stub mode determinism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_returns_deterministic_content_for_same_inputs():
    """Two calls with identical (prompt, image_id, model) yield identical content."""
    ctx = make_ctx(
        "visionNode",
        config={
            "prompt": "deterministic check",
            "image_url": _SAMPLE_URL,
            "model": "gpt-4o-mini",
        },
    )
    r1 = await NODE_EXECUTORS["visionNode"].execute(ctx)
    r2 = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert r1.status == "completed"
    assert r2.status == "completed"
    assert r1.output["content"] == r2.output["content"]
    assert r1.output["image_id_hash"] == r2.output["image_id_hash"]
    assert r1.output.get("_stub") is True
    assert r1.output["image_described"] is True


# ---------------------------------------------------------------------------
# 10. stub mode variability across images
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_different_image_yields_different_content():
    """Different image (same prompt, same model) → different stub content."""
    ctx_a = make_ctx(
        "visionNode",
        config={
            "prompt": "describe",
            "image_url": "https://example.com/cat.png",
            "model": "gpt-4o-mini",
        },
    )
    ctx_b = make_ctx(
        "visionNode",
        config={
            "prompt": "describe",
            "image_url": "https://example.com/dog.png",
            "model": "gpt-4o-mini",
        },
    )
    ra = await NODE_EXECUTORS["visionNode"].execute(ctx_a)
    rb = await NODE_EXECUTORS["visionNode"].execute(ctx_b)

    assert ra.status == "completed"
    assert rb.status == "completed"
    assert ra.output["image_id_hash"] != rb.output["image_id_hash"]
    assert ra.output["content"] != rb.output["content"]


# ---------------------------------------------------------------------------
# 11. real mode calls call_llm with image message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_mode_calls_call_llm_with_image_message(monkeypatch):
    """Real mode: call_llm is invoked; output mirrors the LLMResponse content."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        return _fake_llm_response(content="a sleeping tabby cat", model=model)

    ctx = make_ctx(
        "visionNode",
        config={
            "prompt": "describe",
            "image_url": _SAMPLE_URL,
            "model": "gpt-4o-mini",
        },
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    # Real-mode content is the LLM response — no [STUB-VISION:...] prefix.
    assert result.output["content"] == "a sleeping tabby cat"
    # Real-mode output must NOT carry the _stub flag.
    assert "_stub" not in result.output


# ---------------------------------------------------------------------------
# 12. retry classification (exception class name in error string)
# ---------------------------------------------------------------------------


class _TransientVisionError(Exception):
    """Stand-in for the dispatcher's transient marker on the vision path."""


@pytest.mark.asyncio
async def test_failure_propagates_error_class_name_for_retry_classification(monkeypatch):
    """call_llm raises → status=failed; error names the exc class for RetryPolicy."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "go", "image_url": _SAMPLE_URL, "model": "gpt-4o-mini"},
    )
    with patch(
        "app.langgraph.llm.call_llm",
        new=AsyncMock(side_effect=_TransientVisionError("upstream rate limit")),
    ):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "_TransientVisionError" in result.error or (
        "TransientVisionError" in result.error
    )


# ---------------------------------------------------------------------------
# 13. token usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_usage_populated_in_output(monkeypatch):
    """token_usage dict + NodeResult.token_usage carry prompt/completion/total counts."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    fake = _fake_llm_response(content="ok", model="gpt-4o-mini")

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "go", "image_url": _SAMPLE_URL, "model": "gpt-4o-mini"},
    )
    with patch("app.langgraph.llm.call_llm", new=AsyncMock(return_value=fake)):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["token_usage"]["prompt"] == fake.prompt_tokens
    assert result.output["token_usage"]["completion"] == fake.completion_tokens
    assert result.output["token_usage"]["total"] == fake.total_tokens
    assert result.token_usage is not None
    assert result.token_usage["prompt_tokens"] == fake.prompt_tokens
    assert result.token_usage["completion_tokens"] == fake.completion_tokens
    assert result.token_usage["total_tokens"] == fake.total_tokens


# ---------------------------------------------------------------------------
# 14. cost_usd
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_usd_populated_in_output(monkeypatch):
    """cost_usd is forwarded from LLMResponse onto the NodeResult."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    fake = _fake_llm_response(content="ok", model="gpt-4o-mini")
    fake.cost_usd = 0.001234

    ctx = make_ctx(
        "visionNode",
        config={"prompt": "go", "image_url": _SAMPLE_URL, "model": "gpt-4o-mini"},
    )
    with patch("app.langgraph.llm.call_llm", new=AsyncMock(return_value=fake)):
        result = await NODE_EXECUTORS["visionNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["cost_usd"] == 0.001234
    assert result.cost_usd == 0.001234


# ---------------------------------------------------------------------------
# 15. image_id_hash NEVER leaks the URL or base64
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_id_hash_in_output_does_not_leak_url_or_base64():
    """image_id_hash is sha256[:16]; URL / base64 must NOT appear anywhere in output."""
    sensitive_url = "https://internal.example.com/secret-token-abc123/image.png"
    ctx_url = make_ctx(
        "visionNode",
        config={"prompt": "describe", "image_url": sensitive_url, "model": "gpt-4o-mini"},
    )
    r_url = await NODE_EXECUTORS["visionNode"].execute(ctx_url)
    assert r_url.status == "completed"
    out_str = str(r_url.output)
    assert sensitive_url not in out_str, (
        "URL must NOT appear in output (only sha256[:16] hash is allowed)"
    )
    assert "secret-token-abc123" not in out_str
    # The hash itself is 16 hex chars.
    assert isinstance(r_url.output["image_id_hash"], str)
    assert len(r_url.output["image_id_hash"]) == 16
    assert all(c in "0123456789abcdef" for c in r_url.output["image_id_hash"])

    # And the base64 path also must not leak.
    ctx_b64 = make_ctx(
        "visionNode",
        config={"prompt": "describe", "image_base64": _FAKE_B64, "model": "gpt-4o-mini"},
    )
    r_b64 = await NODE_EXECUTORS["visionNode"].execute(ctx_b64)
    assert r_b64.status == "completed"
    out_str_b64 = str(r_b64.output)
    assert _FAKE_B64 not in out_str_b64, (
        "Base64 must NOT appear in output (only sha256[:16] hash is allowed)"
    )
    assert "data:image" not in out_str_b64, (
        "Wrapped data URI must NOT appear in output"
    )


# ---------------------------------------------------------------------------
# 16. registry classification
# ---------------------------------------------------------------------------


def test_executor_registered_with_beta_status():
    """visionNode is registered AND classified BETA — production-runnable."""
    assert "visionNode" in NODE_EXECUTORS
    assert NODE_STATUS["visionNode"] is NodeStatus.BETA


# ---------------------------------------------------------------------------
# 17. production gate
# ---------------------------------------------------------------------------


def test_executor_runs_in_production_env_after_promotion():
    """assert_node_runnable does not raise for visionNode in production / staging."""
    # No need to actually mutate the environment — pass env explicitly so the
    # check is hermetic.
    assert_node_runnable("visionNode", env="production")
    assert_node_runnable("visionNode", env="staging")
