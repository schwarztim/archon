"""Tests for app.services.dispatch_runtime.

Covers the inline-await mode used by tests/CI and the tracked-task mode used
in production. Verifies done-callback exception logging and inline-mode error
swallowing so the REST handler does not propagate dispatch failures back to
the caller.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager

import pytest

from app.services import dispatch_runtime


@contextmanager
def _set_env(key: str, value: str | None):
    original = os.environ.get(key)
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


@pytest.mark.asyncio
async def test_inline_mode_awaits_coro() -> None:
    """ARCHON_DISPATCH_INLINE=1 → coroutine is awaited; result observable."""
    flag = {"ran": False}

    async def coro() -> None:
        await asyncio.sleep(0)
        flag["ran"] = True

    with _set_env("ARCHON_DISPATCH_INLINE", "1"):
        assert dispatch_runtime.is_inline_mode() is True
        await dispatch_runtime.schedule_dispatch(coro())

    assert flag["ran"] is True, "inline mode must await the coroutine"


@pytest.mark.asyncio
async def test_default_mode_creates_tracked_task() -> None:
    """Without ARCHON_DISPATCH_INLINE → coro scheduled as tracked task."""
    started = asyncio.Event()
    can_finish = asyncio.Event()

    async def coro() -> None:
        started.set()
        await can_finish.wait()

    with _set_env("ARCHON_DISPATCH_INLINE", None):
        assert dispatch_runtime.is_inline_mode() is False
        before = dispatch_runtime.tracked_task_count()
        await dispatch_runtime.schedule_dispatch(coro())
        # Yield once so the task starts.
        await started.wait()
        assert dispatch_runtime.tracked_task_count() >= before + 1
        can_finish.set()
        # Drain by yielding until the task completes.
        for _ in range(50):
            await asyncio.sleep(0)
            if dispatch_runtime.tracked_task_count() <= before:
                break
        assert dispatch_runtime.tracked_task_count() == before


@pytest.mark.asyncio
async def test_done_callback_logs_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Background task exception → logged via on_done callback, not silent."""

    async def boom() -> None:
        raise RuntimeError("scheduled boom")

    with _set_env("ARCHON_DISPATCH_INLINE", None):
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger=dispatch_runtime.log.name):
            await dispatch_runtime.schedule_dispatch(boom())
            # Drain the event loop so the done callback fires.
            for _ in range(50):
                await asyncio.sleep(0)
                if any(
                    "background_dispatch_failed" in rec.message
                    for rec in caplog.records
                ):
                    break

    assert any(
        "background_dispatch_failed" in rec.message for rec in caplog.records
    ), f"expected background_dispatch_failed log, got: {caplog.records!r}"


@pytest.mark.asyncio
async def test_inline_mode_swallows_exception_with_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Inline mode → exception logged but does NOT propagate to caller."""

    async def boom() -> None:
        raise RuntimeError("inline boom")

    with _set_env("ARCHON_DISPATCH_INLINE", "1"):
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger=dispatch_runtime.log.name):
            # Must not raise.
            await dispatch_runtime.schedule_dispatch(boom())

    assert any(
        "inline_dispatch_failed" in rec.message for rec in caplog.records
    ), f"expected inline_dispatch_failed log, got: {caplog.records!r}"
