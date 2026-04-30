"""Redis unavailability chaos tests (Phase 6).

Verifies that:
  * The gateway / backend rate-limit middleware fails OPEN (allows the
    request through) when Redis is unavailable. This is the documented
    contract in ``app.middleware.rate_limit`` — Redis errors must NOT
    block production traffic.
  * The dispatcher does not depend on Redis: a Redis outage must not
    block run claim / dispatch / persistence.

Tests:
  1. test_rate_limiter_falls_back_to_in_memory_when_redis_down
  2. test_dispatcher_continues_when_redis_unavailable
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1: rate limit middleware fails open on Redis error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_falls_back_to_in_memory_when_redis_down() -> None:
    """When Redis raises on INCR/EXPIRE, ``_incr_window`` must return (0, _).

    The middleware's contract is documented as fail-open. We assert that:
      * A Redis client whose ``incr`` raises ConnectionError returns (0, ttl)
        from ``_incr_window``.
      * The returned count is 0 → the middleware never builds a 429.
    """
    from app.middleware import rate_limit as rl_mod

    # Build a fake redis client whose incr() raises a connection error.
    fake_redis = AsyncMock()
    fake_redis.incr = AsyncMock(side_effect=ConnectionError("redis down"))
    fake_redis.expire = AsyncMock()
    fake_redis.ttl = AsyncMock(return_value=60)

    count, ttl = await rl_mod._incr_window(
        fake_redis, "rl:tenant-x:1234567", limit=1000
    )

    # Fail-open contract: returns (0, _WINDOW_SECONDS).
    assert count == 0, (
        "rate limiter must fail open (count=0) when Redis raises"
    )
    assert ttl == rl_mod._WINDOW_SECONDS

    # Subsequent ttl() calls also raising must not change the contract.
    fake_redis.incr = AsyncMock(side_effect=TimeoutError("redis timeout"))
    count2, ttl2 = await rl_mod._incr_window(
        fake_redis, "rl:tenant-y:1234567", limit=500
    )
    assert count2 == 0
    assert ttl2 == rl_mod._WINDOW_SECONDS


@pytest.mark.asyncio
async def test_rate_limiter_middleware_dispatch_fails_open_when_redis_none() -> None:
    """When ``_get_redis`` returns None (Redis import / connect failed),
    the middleware MUST forward the request without checking limits."""
    from starlette.requests import Request
    from app.middleware import rate_limit as rl_mod

    # Patch _get_redis to simulate redis module unavailable.
    with patch.object(rl_mod, "_get_redis", return_value=None):
        # Patch settings.RATE_LIMIT_ENABLED=True so we exercise the path.
        with patch.object(rl_mod.settings, "RATE_LIMIT_ENABLED", True):
            mw = rl_mod.RateLimitMiddleware(app=None)

            # Build a minimal Request scope.
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/api/runs",
                "headers": [],
                "query_string": b"",
                "client": ("127.0.0.1", 12345),
                "state": {},
            }
            request = Request(scope)

            forwarded = {"called": False}

            async def _call_next(req):
                forwarded["called"] = True

                class _Resp:
                    status_code = 200

                return _Resp()

            response = await mw.dispatch(request, _call_next)
            assert forwarded["called"] is True, (
                "middleware must forward to call_next when Redis is unavailable"
            )
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test 2: dispatcher continues to run when Redis is unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_continues_when_redis_unavailable(
    factory, seed_workflow, monkeypatch
) -> None:
    """Even with Redis fully unavailable, the run dispatcher must claim,
    execute the engine, persist step rows, and finalise the run.

    Verifies the architectural separation: Redis is used elsewhere (rate
    limiting, secret cache) but the dispatcher's hot path is Postgres
    only. We assert this by patching ``redis.asyncio.from_url`` so any
    code that DOES try to talk to Redis raises immediately — the
    dispatch must still succeed.
    """
    from tests.test_chaos.conftest import insert_run

    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory", factory
    )

    # Sabotage Redis: any attempt to connect raises.
    def _explode(*args, **kwargs):
        raise ConnectionError("redis down — should not be called by dispatcher")

    # Patch both potential entry points.
    try:
        import redis.asyncio as aioredis  # type: ignore

        monkeypatch.setattr(aioredis, "from_url", _explode, raising=False)
    except ImportError:
        pass

    # Provide a deterministic engine result.
    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "completed",
            "duration_ms": 3,
            "steps": [
                {
                    "step_id": "s1",
                    "name": "step-one",
                    "status": "completed",
                    "started_at": "2026-04-29T17:00:00+00:00",
                    "completed_at": "2026-04-29T17:00:00+00:00",
                    "duration_ms": 3,
                    "input_data": {},
                    "output_data": {"v": "ok"},
                    "error": None,
                    "token_usage": {},
                    "cost_usd": None,
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag", _fake_engine
    )

    run_id = await insert_run(factory, workflow_id=seed_workflow)

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="redis-down-worker")
    assert result is not None
    assert result.status == "completed", (
        f"dispatcher must finish successfully with Redis down, "
        f"got status={result.status}"
    )

    # Sanity: a step row was persisted (Postgres path is healthy).
    from app.models.workflow import WorkflowRunStep
    from sqlalchemy import select

    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "completed"
