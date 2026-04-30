"""Background dispatch runtime: tracked tasks + test-mode inline await.

Replaces raw `asyncio.create_task(dispatch_run(run.id))` on the REST execution
routes with a tracked pattern that: (a) keeps task references so the GC does
not drop them, (b) logs unhandled exceptions on done AND persists a terminal
``failed`` state on the WorkflowRun row when the run_id is known, (c) optionally
awaits inline when ARCHON_DISPATCH_INLINE=1 so the canary slice proves the
same dispatcher path the worker uses in production.

P0 hardening (plan a6a915dc):
    Tracked background dispatch failure used to be log-only — the run row
    stayed in ``status='queued'`` forever. We now persist a terminal
    ``status='failed'`` + ``run.failed`` event whenever ``schedule_dispatch``
    is given a ``run_id`` and the coroutine raises. Inline mode persists
    synchronously; background mode schedules the persist as another tracked
    task so ``schedule_dispatch`` itself stays cheap on the hot path.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable
from datetime import datetime
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)
_TRACKED: set[asyncio.Task[Any]] = set()


def is_inline_mode() -> bool:
    """True when the REST layer should AWAIT dispatch (test/CI). Off in prod."""
    return os.getenv("ARCHON_DISPATCH_INLINE", "").lower() in {"1", "true", "yes"}


async def _persist_failed_run(run_id: UUID, exc: BaseException) -> None:
    """Mark the WorkflowRun row as failed when a dispatch coroutine raises.

    Best-effort: any DB error is logged but never re-raised — we are already
    on an exception path and propagating would just mask the original failure.

    Idempotent: if the run is already terminal (completed/failed/cancelled),
    this is a no-op so we don't overwrite a real outcome with the late-arriving
    background failure (e.g. a cancel that races with a teardown error).
    """
    try:
        # Late imports — keeps module import-time cost low and avoids
        # cycling through app.database when this module loads.
        from app.database import async_session_factory  # noqa: PLC0415
        from app.models.workflow import WorkflowRun  # noqa: PLC0415

        async with async_session_factory() as session:
            run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
            if run is None:
                log.warning(
                    "background_dispatch_failed_run_not_found",
                    extra={"run_id": str(run_id)},
                )
                return
            if run.status in {"completed", "failed", "cancelled"}:
                # Don't clobber a real terminal state.
                log.debug(
                    "background_dispatch_failed_run_already_terminal: "
                    "run_id=%s status=%s",
                    run_id,
                    run.status,
                )
                return

            run.status = "failed"
            run.completed_at = run.completed_at or datetime.utcnow()
            run.error = (
                run.error
                or f"background_dispatch_failed: {type(exc).__name__}: "
                f"{str(exc)[:512]}"
            )[:1024]
            run.error_code = run.error_code or "background_dispatch_failed"
            session.add(run)
            await session.commit()

            # Emit the run.failed event in a separate try-block so a chain
            # error doesn't leave the run in a half-finalised state.
            try:
                from app.services.run_dispatcher import (  # noqa: PLC0415
                    _async_append_event,
                )

                await _async_append_event(
                    session,
                    run.id,
                    "run.failed",
                    payload={
                        "reason": "background_dispatch_failed",
                        "exception": type(exc).__name__,
                        "message": str(exc)[:512],
                    },
                    tenant_id=run.tenant_id,
                )
                await session.commit()
            except Exception as ee:  # noqa: BLE001
                log.error(
                    "background_dispatch_event_emit_failed",
                    exc_info=(type(ee), ee, ee.__traceback__),
                )
    except Exception:  # noqa: BLE001
        log.exception("background_dispatch_failed_state_persist_error")


def _on_done(task: asyncio.Task[Any]) -> None:
    """Done-callback for tracked dispatch tasks.

    Behaviour:
      - Always discard the task from the tracking set so GC can reclaim it.
      - On asyncio.CancelledError: silent (cooperative cancel is normal).
      - On any other exception: log AND, when the task carries a ``run_id``
        attribute, schedule ``_persist_failed_run`` to mark the row failed.

    The persist coroutine is fire-and-forget (added to ``_TRACKED`` so the
    GC cannot drop it). Errors inside the persist are swallowed by
    ``_persist_failed_run`` itself; we never re-enter ``_on_done`` with a
    second exception path.
    """
    _TRACKED.discard(task)
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is None:
        return

    log.error(
        "background_dispatch_failed",
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    run_id = getattr(task, "run_id", None)
    if run_id is None:
        return

    try:
        # We're called inside the event loop's done-callback machinery —
        # asyncio.create_task is safe here. Track the persist task so it
        # isn't garbage-collected before it commits.
        persist_task = asyncio.create_task(
            _persist_failed_run(run_id, exc),
            name=f"persist-failed-{run_id}",
        )
        _TRACKED.add(persist_task)
        persist_task.add_done_callback(_TRACKED.discard)
    except RuntimeError:
        # No running loop (extremely rare — only if the loop is shutting
        # down). The original failure is already logged; nothing more to do.
        log.debug(
            "background_dispatch_persist_no_running_loop run_id=%s", run_id
        )


async def schedule_dispatch(
    coro: Awaitable[Any],
    *,
    run_id: UUID | None = None,
) -> None:
    """Run `coro` either inline (await) or as a tracked background task.

    Inline mode is for tests + CI: the slice REST canary needs dispatch to
    complete before the response is returned so the durable run is observable
    immediately. Production mode (ARCHON_DISPATCH_INLINE unset) tracks the
    task and routes failures through ``_on_done`` so the WorkflowRun row is
    finalised even when the caller has already returned.

    Args:
        coro:    The dispatch coroutine — typically ``dispatch_run(run.id)``.
        run_id:  The owning WorkflowRun.id. When provided, dispatch failures
                 (in either mode) persist a terminal ``failed`` state on the
                 row and emit a ``run.failed`` event. When omitted, failures
                 are still logged but the row state is not touched (preserves
                 the legacy behaviour for callers that pass non-WorkflowRun
                 coroutines).
    """
    if is_inline_mode():
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            log.exception("inline_dispatch_failed")
            if run_id is not None:
                await _persist_failed_run(run_id, exc)
        return

    task = asyncio.create_task(coro)  # noqa: RUF006 — tracked via _TRACKED
    if run_id is not None:
        # Stash on the task so _on_done can recover it without inspecting
        # the coroutine frame (fragile across Python versions).
        task.run_id = run_id  # type: ignore[attr-defined]
    _TRACKED.add(task)
    task.add_done_callback(_on_done)


def tracked_task_count() -> int:
    return len(_TRACKED)


async def drain_tracked_tasks(timeout: float = 5.0) -> int:
    """Wait for all currently-tracked dispatch + persist tasks to settle.

    Test-only helper: an event loop that closes while ``_persist_failed_run``
    is mid-write loses the ``run.failed`` event because the second commit
    is cancelled. This helper lets a test (or a clean-shutdown path) ensure
    every tracked task has reached a terminal state before the loop tears
    down.

    Returns the number of tasks that were drained. Errors inside any task
    are intentionally swallowed (they were already logged via ``_on_done``
    or the inline path).
    """
    if not _TRACKED:
        return 0
    pending = list(_TRACKED)
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        log.warning(
            "drain_tracked_tasks_timeout count=%d timeout=%s",
            len(pending),
            timeout,
        )
    return len(pending)
