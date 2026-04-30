"""delayNode contract tests — Phase 3 / WS9.

Threshold model:
- delay < ``LONG_DELAY_THRESHOLD_SECONDS`` (30s) → sleeps inline,
  ``status="completed"``, output ``{"delayed_seconds": <int|float>}``.
- delay >= threshold → schedules a Timer + returns ``status="paused"``
  with ``{"timer_id": str, "fire_at": iso8601, "delay_seconds": float}``
  and ``paused_reason="durable_delay"``.

When ``ctx.db_session`` is None for a long delay, the executor falls back
to the inline path (Phase-2 safety net so existing in-memory tests work).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_zero_seconds_returns_immediately():
    ctx = make_ctx("delayNode", config={"seconds": 0})
    r = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["delayed_seconds"] == 0


@pytest.mark.asyncio
async def test_delay_ms_converts_to_seconds():
    ctx = make_ctx("delayNode", config={"delayMs": 50})
    r = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert r.status == "completed"
    # 50 ms inline; result records seconds (0.05)
    assert r.output["delayed_seconds"] == pytest.approx(0.05, rel=0.1)


@pytest.mark.asyncio
async def test_delay_camel_and_snake_ms():
    ctx_c = make_ctx("delayNode", config={"delayMs": 10})
    ctx_s = make_ctx("delayNode", config={"delay_ms": 10})
    rc = await NODE_EXECUTORS["delayNode"].execute(ctx_c)
    rs = await NODE_EXECUTORS["delayNode"].execute(ctx_s)
    assert rc.status == "completed" and rs.status == "completed"


# ---------------------------------------------------------------------------
# 2. output schema — short vs durable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_short_output_envelope():
    ctx = make_ctx("delayNode", config={"seconds": 0.01})
    r = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert r.status == "completed"
    assert "delayed_seconds" in r.output


@pytest.mark.asyncio
async def test_delay_durable_output_envelope():
    """Long delay schedules a Timer; output envelope contains timer_id + fire_at."""
    fake_timer = MagicMock()
    fake_timer.id = uuid4()

    session = MagicMock()
    session.flush = AsyncMock()

    ctx = make_ctx(
        "delayNode",
        config={"seconds": 60.0, "long_delay_threshold_seconds": 30.0},
        db_session=session,
        node_data_extra={"run_id": str(uuid4())},
    )
    with patch(
        "app.services.node_executors.delay.schedule_timer",
        new=AsyncMock(return_value=fake_timer),
    ):
        r = await NODE_EXECUTORS["delayNode"].execute(ctx)

    assert r.status == "paused"
    assert r.paused_reason == "durable_delay"
    for key in ("timer_id", "fire_at", "delay_seconds"):
        assert key in r.output
    # fire_at parses as ISO 8601
    datetime.fromisoformat(r.output["fire_at"])
    assert r.output["timer_id"] == str(fake_timer.id)


# ---------------------------------------------------------------------------
# 3. success path — short delay sleeps inline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_short_sleeps_inline():
    """Below threshold → completed without scheduling a Timer."""
    fake_schedule = AsyncMock()
    ctx = make_ctx("delayNode", config={"seconds": 0.05})
    with patch(
        "app.services.node_executors.delay.schedule_timer", new=fake_schedule
    ):
        r = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert r.status == "completed"
    fake_schedule.assert_not_awaited()


# ---------------------------------------------------------------------------
# 4. failure / fallback path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_long_with_no_session_falls_back_to_inline():
    """Long delay with db_session=None falls back to inline; no Timer scheduled."""
    fake_schedule = AsyncMock()
    # Override the threshold to 0.05 so we don't actually wait 30s
    ctx = make_ctx(
        "delayNode",
        config={"seconds": 0.1, "long_delay_threshold_seconds": 0.05},
        db_session=None,
    )
    with patch(
        "app.services.node_executors.delay.schedule_timer", new=fake_schedule
    ):
        r = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert r.status == "completed"
    fake_schedule.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. cancellation — short sleep honours cancel_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_short_sleep_respects_cancel():
    ctx = make_ctx("delayNode", config={"seconds": 10}, cancel_check=lambda: True)
    r = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert r.status == "skipped"
    assert r.output["reason"] == "cancelled"


# ---------------------------------------------------------------------------
# 6. retry classification — N/A (delay is deterministic)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_retry_not_applicable():
    pytest.skip("retry N/A — delay is deterministic / time-based")


# ---------------------------------------------------------------------------
# 7. tenant isolation — output independent of tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_tenant_id_does_not_affect_output():
    cfg = {"seconds": 0}
    ra = await NODE_EXECUTORS["delayNode"].execute(
        make_ctx("delayNode", config=cfg, tenant_id="t-a")
    )
    rb = await NODE_EXECUTORS["delayNode"].execute(
        make_ctx("delayNode", config=cfg, tenant_id="t-b")
    )
    assert ra.output == rb.output


# ---------------------------------------------------------------------------
# 8. event emission — long delay defers to timer_service (out-of-band)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_event_emission_via_timer_service():
    """Long delay calls schedule_timer; that service is the integration point."""
    fake_timer = MagicMock()
    fake_timer.id = uuid4()
    session = MagicMock()
    session.flush = AsyncMock()

    ctx = make_ctx(
        "delayNode",
        config={"seconds": 1.0, "long_delay_threshold_seconds": 0.5},
        db_session=session,
        node_data_extra={"run_id": str(uuid4())},
    )
    with patch(
        "app.services.node_executors.delay.schedule_timer",
        new=AsyncMock(return_value=fake_timer),
    ) as mock_schedule:
        await NODE_EXECUTORS["delayNode"].execute(ctx)

    mock_schedule.assert_awaited_once()
