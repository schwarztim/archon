"""Phase 5 — dispatcher + LLM lifecycle metric emission tests.

These tests target the integration points where the run dispatcher and
``call_llm_routed`` emit canonical metrics. The dispatcher tests use
the lightweight emitters directly (so we avoid a full DB fixture); the
LLM tests run in stub mode (``LLM_STUB_MODE=true``) so no network
traffic occurs.
"""

from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _reload_metrics():
    """Return the existing ``metrics_middleware`` module after clearing
    its in-memory storage.

    Reloading the module wholesale would invalidate every cached
    reference held by other already-loaded modules (the dispatcher,
    ``app.metrics``, the middleware package). Instead we keep the
    module identity stable and reset the in-memory dicts/lists so each
    test sees a clean state. The middleware module's storage is
    documented as in-memory single-process — clearing it is safe.
    """
    import app.middleware.metrics_middleware as m

    for attr in (
        "_request_counts",
        "_duration_sums",
        "_duration_counts",
        "_duration_buckets",
        "_token_usage_counts",
        "_token_usage_counts_canonical",
        "_cost_totals",
        "_cost_totals_canonical",
        "_workflow_run_counts",
        "_workflow_run_counts_canonical",
        "_workflow_duration_buckets",
        "_workflow_duration_sums_canonical",
        "_workflow_duration_counts_canonical",
        "_workflow_duration_buckets_canonical",
        "_step_duration_sums",
        "_step_duration_counts",
        "_step_duration_buckets",
        "_step_retries_counts",
        "_run_cancellations_counts",
        "_checkpoint_failures_counts",
        "_provider_latency_sums",
        "_provider_latency_counts",
        "_provider_latency_buckets",
        "_provider_fallback_counts",
        "_dlp_finding_counts",
    ):
        try:
            getattr(m, attr).clear()
        except AttributeError:
            pass

    # Reset legacy unlabeled workflow histogram aggregates.
    m._workflow_duration_sums[0] = 0.0
    m._workflow_duration_counts[0] = 0
    return m


def _make_run(
    *,
    tenant_id: str = "tenant-x",
    kind: str = "workflow",
    status: str = "completed",
    error_code: str | None = None,
):
    return SimpleNamespace(
        tenant_id=tenant_id,
        kind=kind,
        status=status,
        error_code=error_code,
    )


# ──────────────────────────────────────────────
# Dispatcher emission tests
# ──────────────────────────────────────────────


def test_dispatcher_emits_runs_total_and_duration():
    """``_emit_run_terminal_metrics`` must increment workflow_runs_total
    and observe workflow_run_duration_seconds with full canonical labels."""
    m = _reload_metrics()
    from app.services import run_dispatcher

    run_dispatcher._emit_run_terminal_metrics(
        _make_run(tenant_id="t1", kind="workflow", status="completed"),
        duration_ms=750,
    )

    canonical = m.get_workflow_run_counts_canonical()
    assert canonical[("t1", "workflow", "completed")] == 1

    duration_key = ("t1", "workflow", "completed")
    assert m._workflow_duration_counts_canonical[duration_key] == 1
    assert abs(m._workflow_duration_sums_canonical[duration_key] - 0.75) < 1e-9


def test_dispatcher_emits_cancellation_metric_for_cancelled_run():
    """A status='cancelled' run must increment archon_run_cancellations_total."""
    m = _reload_metrics()
    from app.services import run_dispatcher

    run_dispatcher._emit_run_terminal_metrics(
        _make_run(
            tenant_id="t1",
            status="cancelled",
            error_code="user_requested",
        ),
        duration_ms=200,
    )

    counts = m.get_run_cancellations_counts()
    assert counts[("t1", "user_requested")] == 1


def test_dispatcher_emits_step_metrics_from_engine_payload():
    """``_emit_step_metrics`` must record duration + retry counters."""
    m = _reload_metrics()
    from app.services import run_dispatcher

    run = _make_run(tenant_id="t1")
    run_dispatcher._emit_step_metrics(
        run,
        {
            "step_id": "step-1",
            "node_type": "llm",
            "status": "completed",
            "duration_ms": 250,
        },
    )
    run_dispatcher._emit_step_metrics(
        run,
        {
            "step_id": "step-2",
            "node_type": "http",
            "status": "retry",
            "duration_ms": 100,
        },
    )

    durations = m.get_step_duration_counts()
    assert durations[("t1", "llm", "completed")] == 1
    assert durations[("t1", "http", "retry")] == 1

    retries = m.get_step_retries_counts()
    assert retries[("t1", "http")] == 1


def test_dispatcher_emits_step_retries_when_RetryPolicy_fires():
    """The retry-orchestration helper must call record_step_retry."""
    m = _reload_metrics()
    from app.services import run_dispatcher

    run = _make_run(tenant_id="t1")
    run_dispatcher._emit_step_retry(run, node_type="llm")

    retries = m.get_step_retries_counts()
    assert retries[("t1", "llm")] == 1


# ──────────────────────────────────────────────
# LLM emission tests (stub mode — no network)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_emits_token_usage_with_correct_kind_label(monkeypatch):
    """``call_llm_routed`` must emit prompt and completion token counts
    separately under the correct ``kind`` label."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    m = _reload_metrics()

    # Reload llm so it picks up the new env var resolution path.
    if "app.langgraph.llm" in sys.modules:
        del sys.modules["app.langgraph.llm"]
    from app.langgraph import llm as llm_mod

    # Stub call_llm to avoid touching litellm. Build a synthetic response.
    fake_response = llm_mod.LLMResponse(
        content="ok",
        prompt_tokens=42,
        completion_tokens=17,
        total_tokens=59,
        cost_usd=0.0123,
        model_used="gpt-4o",
        latency_ms=42.0,
    )

    # Stub the routing decision so we don't need a DB session.
    fake_decision = SimpleNamespace(
        model="gpt-4o",
        provider="openai",
        reason="primary",
        fallback_chain=["gpt-4o"],
    )

    async def _fake_route(*_args, **_kwargs):
        return fake_decision

    async def _fake_call_llm(*_args, **_kwargs):
        return fake_response

    async def _fake_record_provider_call(*_a, **_kw):
        return None

    monkeypatch.setattr(llm_mod, "call_llm", _fake_call_llm)

    with patch(
        "app.services.router_service.route_request", _fake_route
    ), patch(
        "app.services.provider_health.record_provider_call",
        _fake_record_provider_call,
    ):
        response, decision = await llm_mod.call_llm_routed(
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            messages=[{"role": "user", "content": "hi"}],
            session=None,
        )

    assert response.prompt_tokens == 42
    canonical = m.get_token_usage_counts_canonical()
    tenant = "00000000-0000-0000-0000-000000000001"
    assert canonical[(tenant, "openai", "gpt-4o", "prompt")] == 42
    assert canonical[(tenant, "openai", "gpt-4o", "completion")] == 17

    cost = m.get_cost_totals_canonical()
    assert abs(cost[(tenant, "openai", "gpt-4o")] - 0.0123) < 1e-9

    latency = m.get_provider_latency_counts()
    assert latency[("openai", "gpt-4o", "success")] == 1


@pytest.mark.asyncio
async def test_provider_fallback_emits_metric_with_from_to_reason(monkeypatch):
    """When the primary fails and the chain rolls to the next entry,
    ``archon_provider_fallback_total`` must increment with the correct
    ``from_provider``/``to_provider``/``reason`` labels."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    m = _reload_metrics()

    if "app.langgraph.llm" in sys.modules:
        del sys.modules["app.langgraph.llm"]
    from app.langgraph import llm as llm_mod

    fake_decision = SimpleNamespace(
        model="gpt-4o",
        provider="openai",
        reason="primary",
        fallback_chain=["gpt-4o", "claude-3-haiku"],
    )

    async def _fake_route(*_a, **_kw):
        return fake_decision

    async def _fake_record_provider_call(*_a, **_kw):
        return None

    call_count = {"n": 0}

    async def _fake_call_llm(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("rate limit 429")
        return llm_mod.LLMResponse(
            content="ok",
            prompt_tokens=5,
            completion_tokens=10,
            total_tokens=15,
            cost_usd=0.0,
            model_used="claude-3-haiku",
            latency_ms=12.0,
        )

    monkeypatch.setattr(llm_mod, "call_llm", _fake_call_llm)

    with patch(
        "app.services.router_service.route_request", _fake_route
    ), patch(
        "app.services.provider_health.record_provider_call",
        _fake_record_provider_call,
    ):
        response, decision = await llm_mod.call_llm_routed(
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            messages=[{"role": "user", "content": "hi"}],
            session=None,
        )

    assert call_count["n"] == 2
    assert response.model_used == "claude-3-haiku"

    fallback_counts = m.get_provider_fallback_counts()
    # Reason will be "fallback_after_openai_failed" per call_llm_routed.
    expected = ("openai", "anthropic", "fallback_after_openai_failed")
    assert fallback_counts[expected] == 1

    # Provider latency must record both success and failure observations.
    latency_counts = m.get_provider_latency_counts()
    assert latency_counts[("openai", "gpt-4o", "failure")] == 1
    assert latency_counts[("anthropic", "claude-3-haiku", "success")] == 1


# ──────────────────────────────────────────────
# Checkpointer emission test
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkpointer_emits_metric_on_durability_failure(monkeypatch):
    """Postgres durability failure in production must increment
    archon_checkpoint_failures_total before raising."""
    m = _reload_metrics()

    # Force production env so the durability path triggers.
    monkeypatch.setenv("ARCHON_ENV", "production")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "postgres")

    # Reload checkpointer to pick up env vars.
    if "app.langgraph.checkpointer" in sys.modules:
        del sys.modules["app.langgraph.checkpointer"]
    from app.langgraph import checkpointer as cp

    cp.reset_checkpointer()

    async def _boom() -> None:
        raise RuntimeError("could not translate host to address")

    monkeypatch.setattr(cp, "_get_postgres_checkpointer", _boom)

    with pytest.raises(cp.CheckpointerDurabilityFailed):
        await cp.get_checkpointer()

    counts = m.get_checkpoint_failures_counts()
    # Reason classifier matches "could not translate host" → connect_error.
    assert counts[("production", "connect_error")] == 1
