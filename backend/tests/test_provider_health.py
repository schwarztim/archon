"""Tests for app.services.provider_health.

Phase 4 / WS10 — Model Routing Squad.

Run with::

    PYTHONPATH=backend python3 -m pytest backend/tests/test_provider_health.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.services import provider_health
from app.services.provider_health import (
    FAILURE_THRESHOLD,
    RECOVERY_TIMEOUT_S,
    check_provider,
    is_circuit_open,
    record_provider_call,
    reset_state,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_health() -> None:
    """Clear in-memory state between tests."""
    reset_state()
    yield
    reset_state()


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_provider_returns_default_for_unknown() -> None:
    """An unseen provider returns a healthy default snapshot."""
    health = await check_provider(None, "openai")
    assert health.provider == "openai"
    assert health.healthy is True
    assert health.error_rate == 0.0
    assert health.p99_latency_ms is None
    assert health.last_error is None
    assert health.last_check_at is None
    assert health.circuit_state == "closed"


@pytest.mark.asyncio
async def test_record_provider_call_updates_error_rate() -> None:
    """Recording a mix of successes and failures populates the rolling error rate."""
    for _ in range(3):
        await record_provider_call(None, "openai", success=True, latency_ms=100.0)
    for _ in range(2):
        await record_provider_call(
            None,
            "openai",
            success=False,
            latency_ms=300.0,
            error="timeout",
        )

    health = await check_provider(None, "openai")
    # 2 failures out of 5 samples = 0.4 (still below the 0.5 unhealthy threshold)
    assert health.error_rate == pytest.approx(0.4, abs=1e-6)
    assert health.last_error == "timeout"
    assert health.last_check_at is not None
    # 3 successes recorded → p99 from successful latencies should be 100.0
    assert health.p99_latency_ms == pytest.approx(100.0, abs=1e-6)


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_5_consecutive_failures() -> None:
    """Five consecutive failures open the circuit."""
    # Up to threshold-1 failures → circuit stays closed
    for _ in range(FAILURE_THRESHOLD - 1):
        await record_provider_call(
            None,
            "anthropic",
            success=False,
            latency_ms=200.0,
            error="500 internal server error",
        )
    assert await is_circuit_open(None, "anthropic") is False

    # Crossing the threshold opens the circuit
    await record_provider_call(
        None,
        "anthropic",
        success=False,
        latency_ms=200.0,
        error="500 internal server error",
    )
    assert await is_circuit_open(None, "anthropic") is True

    health = await check_provider(None, "anthropic")
    assert health.circuit_state == "open"
    assert health.healthy is False


@pytest.mark.asyncio
async def test_circuit_breaker_half_opens_after_cooldown() -> None:
    """After the cooldown elapses, the circuit transitions to half_open."""
    for _ in range(FAILURE_THRESHOLD):
        await record_provider_call(
            None, "google", success=False, latency_ms=50.0, error="boom"
        )
    assert await is_circuit_open(None, "google") is True

    # Simulate cooldown: monkeypatch time.monotonic to jump RECOVERY_TIMEOUT_S+1
    base = 1_000_000.0
    state = provider_health._get_state("google")
    state.opened_at_monotonic = base
    with patch.object(
        provider_health.time,
        "monotonic",
        return_value=base + RECOVERY_TIMEOUT_S + 1.0,
    ):
        # is_circuit_open returns False because we transitioned to half_open
        assert await is_circuit_open(None, "google") is False

    health = await check_provider(None, "google")
    assert health.circuit_state == "half_open"


@pytest.mark.asyncio
async def test_circuit_breaker_closes_on_successful_trial() -> None:
    """A successful call from half_open closes the circuit."""
    # Open it.
    for _ in range(FAILURE_THRESHOLD):
        await record_provider_call(
            None, "mistral", success=False, latency_ms=10.0, error="x"
        )

    # Force half_open by manipulating opened_at_monotonic + reading state.
    base = 1_000_000.0
    state = provider_health._get_state("mistral")
    state.opened_at_monotonic = base
    with patch.object(
        provider_health.time,
        "monotonic",
        return_value=base + RECOVERY_TIMEOUT_S + 0.1,
    ):
        await is_circuit_open(None, "mistral")  # triggers transition

    assert state.circuit_state == "half_open"

    # Successful trial → closed
    await record_provider_call(None, "mistral", success=True, latency_ms=42.0)
    health = await check_provider(None, "mistral")
    assert health.circuit_state == "closed"
    assert state.consecutive_failures == 0


@pytest.mark.asyncio
async def test_is_circuit_open_returns_correct_state() -> None:
    """is_circuit_open mirrors the underlying circuit state across transitions."""
    # closed
    assert await is_circuit_open(None, "fresh-provider") is False

    # below threshold → still closed
    for _ in range(FAILURE_THRESHOLD - 1):
        await record_provider_call(
            None, "fresh-provider", success=False, latency_ms=1.0, error="e"
        )
    assert await is_circuit_open(None, "fresh-provider") is False

    # threshold → open
    await record_provider_call(
        None, "fresh-provider", success=False, latency_ms=1.0, error="e"
    )
    assert await is_circuit_open(None, "fresh-provider") is True

    # half_open trial fails → re-opens
    base = 2_000_000.0
    state = provider_health._get_state("fresh-provider")
    state.opened_at_monotonic = base
    with patch.object(
        provider_health.time,
        "monotonic",
        return_value=base + RECOVERY_TIMEOUT_S + 0.1,
    ):
        # half_open transition
        assert await is_circuit_open(None, "fresh-provider") is False
        # Trial fails → goes back to open immediately
        await record_provider_call(
            None, "fresh-provider", success=False, latency_ms=1.0, error="boom"
        )
        # Without bumping the cooldown forward, it's open again
        assert state.circuit_state == "open"
