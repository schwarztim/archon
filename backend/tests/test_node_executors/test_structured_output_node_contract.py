"""structuredOutputNode contract tests — Phase 3 / WS9 (Executor Workstream 2).

Coverage dimensions (mirrors test_embedding_node_contract.py):

1.  missing schema      — config without ``schema`` → status="failed".
2.  missing prompt      — config without ``prompt`` (and no upstream string)
                          → status="failed".
3.  stub synthesis      — schema is walked; required keys are present and
                          schema-valid.
4.  stub required-only  — optional properties are omitted by the synthesiser.
5.  stub defaults       — schema-level ``default`` values win over the
                          type-placeholder fallback.
6.  stub determinism    — identical (prompt, schema) → identical output across
                          multiple calls.
7.  real-mode JSON      — call_llm is invoked with a JSON-mode prompt; the
                          response is parsed and validated.
8.  real-mode bad JSON  — schema mismatch surfaces as
                          error_code="schema_validation_failed".
9.  retry classification — call_llm raises → status="failed", error string
                           names the exception class so RetryPolicy can
                           classify it.
10. token usage         — populated on the success path.
11. cost_usd            — populated on the success path.
12. registry            — structuredOutputNode is classified BETA.
13. production gate     — assert_node_runnable does not raise after promotion.
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


def _fake_llm_response(content: str, *, model: str = "gpt-4o-mini") -> LLMResponse:
    return LLMResponse(
        content=content,
        prompt_tokens=12,
        completion_tokens=18,
        total_tokens=30,
        cost_usd=0.000456,
        model_used=model,
        latency_ms=3.5,
    )


# ---------------------------------------------------------------------------
# 1. missing schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_schema_returns_failed():
    """No schema in config → status=failed, ValueError-shaped error."""
    ctx = make_ctx("structuredOutputNode", config={"prompt": "anything"})
    result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)
    assert result.status == "failed"
    assert result.error is not None
    assert "ValueError" in result.error
    assert "schema" in result.error.lower()
    assert result.output.get("error_code") == "missing_schema"


# ---------------------------------------------------------------------------
# 2. missing prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_prompt_returns_failed():
    """Schema present but no prompt and no upstream → status=failed."""
    ctx = make_ctx(
        "structuredOutputNode",
        config={"schema": {"type": "object", "properties": {"x": {"type": "string"}}}},
    )
    result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)
    assert result.status == "failed"
    assert result.error is not None
    assert "ValueError" in result.error
    assert "prompt" in result.error.lower()
    assert result.output.get("error_code") == "missing_prompt"


# ---------------------------------------------------------------------------
# 3. stub synthesis (required keys present + schema-valid)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_synthesises_valid_object():
    """LLM_STUB_MODE=true → status=completed; synthesised object satisfies schema."""
    schema = {
        "type": "object",
        "required": ["name", "age", "active"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "active": {"type": "boolean"},
        },
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "describe a user", "schema": schema, "model": "gpt-4o-mini"},
    )
    result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "completed"
    assert isinstance(result.output["output"], dict)
    out = result.output["output"]
    # All required keys present.
    assert set(out.keys()) >= {"name", "age", "active"}
    # Types match the schema.
    assert isinstance(out["name"], str)
    assert isinstance(out["age"], int)
    assert isinstance(out["active"], bool)
    assert result.output["model"].endswith("-stub")
    assert "token_usage" in result.output
    assert {"prompt", "completion", "total"} <= set(result.output["token_usage"].keys())
    assert "cost_usd" in result.output
    assert "latency_ms" in result.output
    assert result.output.get("_stub") is True
    assert isinstance(result.token_usage, dict)
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(
        result.token_usage.keys()
    )

    # Sanity check: output validates against the schema.
    import jsonschema  # noqa: PLC0415
    jsonschema.validate(instance=out, schema=schema)


# ---------------------------------------------------------------------------
# 4. stub required-only (optional properties omitted)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_synthesises_required_only_object_when_optional_omitted():
    """Optional properties are omitted from the synthesised object."""
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "string"},
            "nickname": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "synthesise minimal", "schema": schema},
    )
    result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "completed"
    out = result.output["output"]
    assert set(out.keys()) == {"id"}
    assert isinstance(out["id"], str)


# ---------------------------------------------------------------------------
# 5. stub uses schema-level defaults when present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_uses_schema_defaults_when_present():
    """`default` values override the type-placeholder fallback."""
    schema = {
        "type": "object",
        "required": ["status", "count"],
        "properties": {
            "status": {"type": "string", "default": "approved"},
            "count": {"type": "integer", "default": 42},
        },
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "honour defaults", "schema": schema},
    )
    result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "completed"
    out = result.output["output"]
    assert out["status"] == "approved"
    assert out["count"] == 42


# ---------------------------------------------------------------------------
# 6. stub determinism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_deterministic_for_same_prompt_and_schema():
    """Two calls with identical (prompt, schema) yield identical output."""
    schema = {
        "type": "object",
        "required": ["a", "b"],
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "number"},
        },
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "deterministic", "schema": schema},
    )
    r1 = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)
    r2 = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert r1.status == "completed"
    assert r2.status == "completed"
    assert r1.output["output"] == r2.output["output"]
    assert r1.output["schema_hash"] == r2.output["schema_hash"]


# ---------------------------------------------------------------------------
# 7. real-mode JSON parsing + validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_mode_calls_call_llm_with_json_mode(monkeypatch):
    """Real mode (LLM_STUB_MODE=false): call_llm is invoked, response parsed + validated."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")

    captured: dict = {}

    async def _capture(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        captured["prompt"] = prompt
        captured["model"] = model
        return _fake_llm_response('{"name": "Alice", "age": 30}', model=model)

    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={
            "prompt": "extract user",
            "schema": schema,
            "model": "gpt-4o-mini",
        },
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["output"] == {"name": "Alice", "age": 30}
    # The augmented prompt embeds the JSON Schema instruction.
    assert "JSON Schema" in captured["prompt"]
    assert "extract user" in captured["prompt"]
    assert captured["model"] == "gpt-4o-mini"
    # Stub flag must NOT be set in real mode.
    assert "_stub" not in result.output


# ---------------------------------------------------------------------------
# 8. real-mode validation failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_mode_failed_validation_returns_schema_validation_error(monkeypatch):
    """LLM returns JSON that doesn't match schema → status=failed with error_code."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")

    async def _bad_response(prompt, model, system=None, max_tokens=1024, temperature=0.7):
        # Missing required field "age"; "name" wrong type.
        return _fake_llm_response('{"name": 123}', model=model)

    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "extract", "schema": schema, "model": "gpt-4o-mini"},
    )
    with patch("app.langgraph.llm.call_llm", new=_bad_response):
        result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "schema_validation_failed" in result.error
    assert result.output.get("error_code") == "schema_validation_failed"


# ---------------------------------------------------------------------------
# 9. retry classification (exception class name in error string)
# ---------------------------------------------------------------------------


class _TransientStructuredError(Exception):
    """Stand-in for the dispatcher's transient marker on the structured-output path."""


@pytest.mark.asyncio
async def test_failure_propagates_error_class_name_for_retry_classification(monkeypatch):
    """call_llm raises → status=failed; error names the exc class for RetryPolicy."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")

    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "string"}},
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "go", "schema": schema, "model": "gpt-4o-mini"},
    )
    with patch(
        "app.langgraph.llm.call_llm",
        new=AsyncMock(side_effect=_TransientStructuredError("upstream rate limit")),
    ):
        result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "_TransientStructuredError" in result.error or (
        "TransientStructuredError" in result.error
    )


# ---------------------------------------------------------------------------
# 10. token usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_usage_populated_in_output(monkeypatch):
    """token_usage dict + NodeResult.token_usage carry the prompt/completion/total counts."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    fake = _fake_llm_response('{"x": "ok"}', model="gpt-4o-mini")

    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "string"}},
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "go", "schema": schema, "model": "gpt-4o-mini"},
    )
    with patch("app.langgraph.llm.call_llm", new=AsyncMock(return_value=fake)):
        result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["token_usage"]["prompt"] == fake.prompt_tokens
    assert result.output["token_usage"]["completion"] == fake.completion_tokens
    assert result.output["token_usage"]["total"] == fake.total_tokens
    assert result.token_usage is not None
    assert result.token_usage["prompt_tokens"] == fake.prompt_tokens
    assert result.token_usage["completion_tokens"] == fake.completion_tokens
    assert result.token_usage["total_tokens"] == fake.total_tokens


# ---------------------------------------------------------------------------
# 11. cost_usd
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_usd_populated_in_output(monkeypatch):
    """cost_usd is forwarded from LLMResponse onto the NodeResult."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    fake = _fake_llm_response('{"x": "ok"}', model="gpt-4o-mini")
    fake.cost_usd = 0.000789

    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "string"}},
    }
    ctx = make_ctx(
        "structuredOutputNode",
        config={"prompt": "go", "schema": schema, "model": "gpt-4o-mini"},
    )
    with patch("app.langgraph.llm.call_llm", new=AsyncMock(return_value=fake)):
        result = await NODE_EXECUTORS["structuredOutputNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["cost_usd"] == 0.000789
    assert result.cost_usd == 0.000789


# ---------------------------------------------------------------------------
# 12. registry classification
# ---------------------------------------------------------------------------


def test_executor_registered_with_beta_status():
    """structuredOutputNode is registered AND classified BETA — production-runnable."""
    assert "structuredOutputNode" in NODE_EXECUTORS
    assert NODE_STATUS["structuredOutputNode"] is NodeStatus.BETA


# ---------------------------------------------------------------------------
# 13. production gate
# ---------------------------------------------------------------------------


def test_executor_runs_in_production_env_after_promotion():
    """assert_node_runnable does not raise for structuredOutputNode in production."""
    # No need to actually mutate the environment — pass env explicitly so the
    # check is hermetic.
    assert_node_runnable("structuredOutputNode", env="production")
    assert_node_runnable("structuredOutputNode", env="staging")
