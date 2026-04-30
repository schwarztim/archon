"""Delay node executor — short waits sleep inline; long waits use a Timer.

Threshold model:
  - delay_seconds < ``LONG_DELAY_THRESHOLD_SECONDS`` (30s default):
    sleep in-process with cancel checks, return ``status="completed"``.
  - delay_seconds >= threshold: schedule a durable Timer row via
    ``timer_service.schedule_timer``, return ``status="paused"`` with a
    structured hint dict. The dispatcher (W2.4) is expected to release
    the worker lease and resume the run when the timer fires.

The threshold prevents writing a DB row for every tiny pause while
guaranteeing crash-safety for any wait long enough that a worker
restart would otherwise lose the schedule.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register
from app.services.timer_service import schedule_timer

logger = logging.getLogger(__name__)


# Delays at or above this threshold are scheduled as durable Timer rows
# instead of consuming a worker via asyncio.sleep. Configurable via the
# step's config dict (key ``long_delay_threshold_seconds``) so tests and
# specific workflows can opt in/out, but a sensible default keeps the
# distinction structural.
LONG_DELAY_THRESHOLD_SECONDS: float = 30.0


@register("delayNode")
class DelayNodeExecutor(NodeExecutor):
    """Wait for a configured duration. Short waits inline; long waits durable."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        # Support both seconds and milliseconds config keys
        delay_seconds: float = float(config.get("seconds") or 0.0)
        delay_ms: float = float(config.get("delayMs") or config.get("delay_ms") or 0.0)

        if delay_seconds == 0.0 and delay_ms > 0:
            delay_seconds = delay_ms / 1000.0

        if delay_seconds <= 0:
            return NodeResult(status="completed", output={"delayed_seconds": 0})

        threshold = float(
            config.get("long_delay_threshold_seconds")
            or LONG_DELAY_THRESHOLD_SECONDS
        )

        # ── Long wait: schedule a durable Timer and pause ─────────────────
        if delay_seconds >= threshold:
            return await self._schedule_durable(ctx, delay_seconds)

        # ── Short wait: sleep inline with cancel-check chunks ────────────
        return await self._sleep_inline(ctx, delay_seconds)

    # -- helpers ---------------------------------------------------------

    async def _sleep_inline(
        self, ctx: NodeContext, delay_seconds: float
    ) -> NodeResult:
        logger.debug(
            "delayNode.sleeping",
            extra={"step_id": ctx.step_id, "seconds": delay_seconds},
        )
        _CHUNK = 0.1
        elapsed = 0.0
        while elapsed < delay_seconds:
            if ctx.cancel_check():
                return NodeResult(
                    status="skipped",
                    output={"reason": "cancelled", "elapsed_seconds": elapsed},
                )
            chunk = min(_CHUNK, delay_seconds - elapsed)
            await asyncio.sleep(chunk)
            elapsed += chunk

        return NodeResult(
            status="completed",
            output={"delayed_seconds": delay_seconds},
        )

    async def _schedule_durable(
        self, ctx: NodeContext, delay_seconds: float
    ) -> NodeResult:
        if ctx.db_session is None:
            # No DB → fall back to inline sleep so existing in-memory tests
            # don't break. This is a Phase-2 safety net; production paths
            # always pass a session.
            logger.warning(
                "delayNode.no_db_session_falling_back_to_inline",
                extra={"step_id": ctx.step_id, "seconds": delay_seconds},
            )
            return await self._sleep_inline(ctx, delay_seconds)

        config = ctx.config
        run_id = config.get("run_id") or ctx.node_data.get("run_id")
        # Keep run_id type-safe: tests sometimes pass strings, the
        # dispatcher passes UUIDs. timer_service accepts either via
        # the SQLAlchemy Uuid column type, but we leave coercion to
        # the caller / model layer.

        fire_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        timer = await schedule_timer(
            ctx.db_session,
            run_id=run_id,
            step_id=ctx.step_id,
            fire_at=fire_at,
            purpose="delay_node",
            payload={
                "step_id": ctx.step_id,
                "next_step": config.get("next_step"),
                "delay_seconds": delay_seconds,
            },
        )

        logger.debug(
            "delayNode.timer_scheduled",
            extra={
                "step_id": ctx.step_id,
                "timer_id": str(timer.id),
                "fire_at": fire_at.isoformat(),
                "seconds": delay_seconds,
            },
        )

        return NodeResult(
            status="paused",
            output={
                "timer_id": str(timer.id),
                "fire_at": fire_at.isoformat(),
                "delay_seconds": delay_seconds,
            },
            paused_reason="durable_delay",
        )
