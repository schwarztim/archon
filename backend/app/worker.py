"""Archon background worker for async tasks.

Phase 1 + Phase 6 implementation.

Responsibilities (all driven from the WorkflowRun durable substrate):
  - **Heartbeat loop** (10s): refresh ``worker_heartbeats.last_heartbeat_at``
    so the registry can tell live workers from corpses.
  - **Drain loop** (5s): scan for ``status IN ('queued','pending')`` rows
    with no live lease, dispatch them via the dispatcher (which holds the
    actual ``claim_run`` primitive). Concurrency is capped by an asyncio
    Semaphore at ``ARCHON_MAX_CONCURRENT_RUNS``.
  - **Reclaim loop** (30s): call the dispatcher's
    ``reclaim_expired_runs`` to return runs whose lease expired (worker
    crashed mid-run) to the queue. Logs a metric of how many were
    reclaimed.
  - Legacy slow loop (300s): scheduled scans, rotation checks, budget
    alerts, scheduled workflows, improvement analysis. Kept for
    backwards compatibility with existing operator workflows — the
    durable run logic is the new substance.

Concurrency safety: actual lease claiming is the dispatcher's job. The
drain loop only ENQUEUES candidates. Two workers seeing the same row
both call ``dispatch_run``; only one wins ``claim_run`` (when W1.3 lands
that primitive), the other is a no-op.

Shutdown: SIGINT/SIGTERM set ``_shutdown``. ``run_worker`` awaits all
in-flight dispatch tasks (with a timeout) before returning. Heartbeat
row is deleted on graceful shutdown.

Checkpointing default is ``postgres``. In production this is required
and failures are fatal. Set ``LANGGRAPH_CHECKPOINTING=memory`` only in
dev or test environments where durability is not needed (see ADR-005).

Run via: ``python3 -m app.worker``
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
import time
import uuid
from datetime import datetime, timezone

from app.database import async_session_factory
from app.logging_config import get_logger, setup_logging
from app.services.worker_registry import WorkerRegistry

logger = get_logger(__name__)

# ── Tunables (env overrides) ────────────────────────────────────────────

#: Pulled per-loop. Cached defaults are used when the env var is unset.
_RUN_BATCH_SIZE = int(os.environ.get("ARCHON_RUN_BATCH_SIZE", "10"))
_MAX_CONCURRENT_RUNS = int(os.environ.get("ARCHON_MAX_CONCURRENT_RUNS", "50"))
_DRAIN_INTERVAL = 5  # seconds between drain ticks
_HEARTBEAT_INTERVAL = 10  # seconds between heartbeat refreshes
_RECLAIM_INTERVAL = 30  # seconds between expired-lease reclaim sweeps
_RECLAIM_GRACE_SECONDS = 10  # see reclaim_expired_runs(grace=...)
_SHUTDOWN_GRACE_SECONDS = 30  # how long to wait for in-flight dispatches
_TIMER_FIRE_INTERVAL = 5  # seconds between timer-fire ticks
_TIMER_FIRE_BATCH = int(os.environ.get("ARCHON_TIMER_FIRE_BATCH", "100"))

# ── Module-level state (process-wide singletons) ────────────────────────

_shutdown: asyncio.Event | None = None
_inflight: set[asyncio.Task] = set()
_dispatch_semaphore: asyncio.Semaphore | None = None


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _generate_worker_id() -> str:
    """Build a stable-ish worker id: hostname-pid-shortuuid."""
    return f"{_hostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


# ── Slow loop helpers (preserved verbatim from the original worker) ────


async def _run_scheduled_scans() -> None:
    """Check for scheduled security scans that are due and execute them."""
    logger.debug("scheduled_scan_tick")
    try:
        from app.database import async_session_factory
        from app.models.sentinelscan import DiscoveryScan
        from sqlmodel import select

        async with async_session_factory() as session:
            now = datetime.now(tz=timezone.utc)
            stmt = select(DiscoveryScan).where(
                DiscoveryScan.status == "pending",
                DiscoveryScan.created_at <= now,
            )
            result = await session.exec(stmt)
            scans = list(result.all())

            for scan in scans:
                logger.info(
                    "scheduled_scan_starting",
                    scan_id=str(scan.id),
                    scan_type=scan.scan_type,
                )
                scan.status = "running"
                scan.started_at = now
                session.add(scan)

            if scans:
                await session.commit()
                logger.info("scheduled_scans_dispatched", count=len(scans))
    except Exception:
        logger.exception("scheduled_scan_error")


async def _run_rotation_checks() -> None:
    """Check for secrets/credentials approaching or past their rotation date."""
    logger.debug("rotation_check_tick")
    try:
        from app.database import async_session_factory
        from app.models.secrets import SecretRegistration
        from sqlmodel import select

        async with async_session_factory() as session:
            now = datetime.now(tz=timezone.utc)
            stmt = select(SecretRegistration).where(
                SecretRegistration.expires_at.isnot(None),  # type: ignore[union-attr]
            )
            result = await session.exec(stmt)
            registrations = list(result.all())

            for reg in registrations:
                if reg.expires_at is None:
                    continue
                expires = (
                    reg.expires_at
                    if reg.expires_at.tzinfo
                    else reg.expires_at.replace(tzinfo=timezone.utc)
                )
                days_until_expiry = (expires - now).days

                if days_until_expiry < 0:
                    logger.warning(
                        "secret_expired",
                        path=reg.path,
                        secret_type=reg.secret_type,
                        expired_days_ago=abs(days_until_expiry),
                    )
                elif days_until_expiry <= reg.notify_before_days:
                    logger.warning(
                        "secret_rotation_due",
                        path=reg.path,
                        secret_type=reg.secret_type,
                        days_until_expiry=days_until_expiry,
                        auto_rotate=reg.auto_rotate,
                    )
    except Exception:
        logger.exception("rotation_check_error")


async def _run_budget_alerts() -> None:
    """Evaluate budgets and create alert records when thresholds are breached."""
    logger.debug("budget_alert_tick")
    try:
        from app.database import async_session_factory
        from app.models.cost import Budget, CostAlert
        from sqlmodel import select

        async with async_session_factory() as session:
            stmt = select(Budget).where(Budget.is_active == True)  # noqa: E712
            result = await session.exec(stmt)
            budgets = list(result.all())

            alerts_created = 0
            for budget in budgets:
                if budget.limit_amount <= 0:
                    continue

                usage_pct = (budget.spent_amount / budget.limit_amount) * 100.0

                for threshold in sorted(budget.alert_thresholds, reverse=True):
                    if usage_pct >= threshold:
                        existing_stmt = select(CostAlert).where(
                            CostAlert.budget_id == budget.id,
                            CostAlert.threshold_pct == threshold,
                            CostAlert.is_acknowledged == False,  # noqa: E712
                        )
                        existing = await session.exec(existing_stmt)
                        if existing.first() is not None:
                            break

                        severity = (
                            "critical"
                            if threshold >= 100
                            else "warning"
                            if threshold >= 75
                            else "info"
                        )
                        alert = CostAlert(
                            budget_id=budget.id,
                            alert_type="threshold",
                            severity=severity,
                            threshold_pct=threshold,
                            current_spend=budget.spent_amount,
                            budget_limit=budget.limit_amount,
                            message=(
                                f"Budget '{budget.name}' has reached {usage_pct:.1f}% "
                                f"(${budget.spent_amount:.2f} / ${budget.limit_amount:.2f})"
                            ),
                        )
                        session.add(alert)
                        alerts_created += 1
                        logger.warning(
                            "budget_threshold_breached",
                            budget_id=str(budget.id),
                            budget_name=budget.name,
                            threshold_pct=threshold,
                            usage_pct=round(usage_pct, 1),
                            severity=severity,
                        )
                        break

            if alerts_created:
                await session.commit()
                logger.info("budget_alerts_created", count=alerts_created)
    except Exception:
        logger.exception("budget_alert_error")


async def _check_scheduled_workflows() -> None:
    """Check for scheduled workflows that are due and create WorkflowRun records."""
    logger.debug("scheduled_workflow_tick")
    try:
        from croniter import croniter

        from app.database import async_session_factory
        from app.models.workflow import Workflow, WorkflowRun, WorkflowSchedule
        from sqlmodel import select

        async with async_session_factory() as session:
            stmt = (
                select(WorkflowSchedule, Workflow)
                .join(Workflow, WorkflowSchedule.workflow_id == Workflow.id)
                .where(
                    WorkflowSchedule.enabled == True,  # noqa: E712
                    Workflow.is_active == True,  # noqa: E712
                )
            )
            result = await session.exec(stmt)
            rows = list(result.all())

            datetime.now(tz=timezone.utc)
            now_naive = datetime.utcnow()

            runs_created = 0
            for schedule, workflow in rows:
                try:
                    if schedule.last_run_at is not None:
                        last_run = schedule.last_run_at
                        if last_run.tzinfo is not None:
                            last_run = last_run.replace(tzinfo=None)
                    else:
                        cron_iter = croniter(schedule.cron, now_naive)
                        last_run = cron_iter.get_prev(datetime)

                    cron_iter = croniter(schedule.cron, last_run)
                    next_run = cron_iter.get_next(datetime)

                    if next_run <= now_naive:
                        run = WorkflowRun(
                            workflow_id=workflow.id,
                            tenant_id=workflow.tenant_id,
                            status="pending",
                            trigger_type="schedule",
                            triggered_by="scheduler",
                        )
                        session.add(run)

                        cron_iter2 = croniter(schedule.cron, next_run)
                        following_next = cron_iter2.get_next(datetime)

                        schedule.last_run_at = now_naive
                        schedule.next_run_at = following_next
                        schedule.updated_at = now_naive
                        session.add(schedule)

                        runs_created += 1
                        logger.info(
                            "scheduled_workflow_triggered",
                            workflow_id=str(workflow.id),
                            workflow_name=workflow.name,
                            cron=schedule.cron,
                            next_run_at=following_next.isoformat(),
                        )
                    else:
                        if schedule.next_run_at is None:
                            schedule.next_run_at = next_run
                            schedule.updated_at = now_naive
                            session.add(schedule)

                except Exception:
                    logger.exception(
                        "scheduled_workflow_check_error",
                        workflow_id=str(workflow.id),
                        cron=schedule.cron,
                    )

            if runs_created:
                await session.commit()
                logger.info("scheduled_workflow_runs_created", count=runs_created)
            elif any(s.next_run_at is None for s, _ in rows):
                await session.commit()

    except Exception:
        logger.exception("scheduled_workflow_error")


_last_improvement_run: datetime | None = None


async def _run_improvement_analysis() -> None:
    """Run the improvement engine analysis cycle on the configured interval."""
    logger.debug("improvement_analysis_tick")
    try:
        from app.config import settings

        if not settings.IMPROVEMENT_ENGINE_ENABLED:
            return

        global _last_improvement_run
        now = datetime.now(tz=timezone.utc)

        if _last_improvement_run is not None:
            elapsed_hours = (now - _last_improvement_run).total_seconds() / 3600
            if elapsed_hours < settings.GAP_ANALYSIS_INTERVAL_HOURS:
                return

        from app.database import async_session_factory
        from app.services.improvement_engine import ImprovementEngineService

        async with async_session_factory() as session:
            summary = await ImprovementEngineService.run_analysis_cycle(session)
            _last_improvement_run = now
            logger.info("improvement_analysis_tick_complete", **summary)

    except Exception:
        logger.exception("improvement_analysis_error")


# ── Dispatcher import bridge (graceful degradation while W1.3 lands) ───


def _resolve_dispatch_run():
    """Return the dispatcher's ``dispatch_run`` callable.

    W1.3 will eventually expose ``dispatch_run(run_id, worker_id=...)``
    plus ``claim_run`` and ``reclaim_expired_runs`` primitives. Until
    then, we fall back to the legacy ``dispatch_run(run_id)`` and the
    worker passes ``worker_id`` only when the dispatcher accepts it.
    """
    from app.services.run_dispatcher import dispatch_run

    return dispatch_run


def _resolve_reclaim_expired_runs():
    """Return ``reclaim_expired_runs`` if W1.3 has shipped it; else None.

    Tries ``run_lifecycle`` first (W1.3's owned location), then
    ``run_dispatcher`` for backwards compatibility. A return value of
    ``None`` causes the reclaim loop to no-op cleanly.
    """
    try:
        from app.services.run_lifecycle import reclaim_expired_runs

        return reclaim_expired_runs
    except ImportError:
        pass
    try:
        from app.services.run_dispatcher import reclaim_expired_runs

        return reclaim_expired_runs
    except ImportError:
        return None


async def _call_dispatch_run(run_id, worker_id: str) -> None:
    """Invoke ``dispatch_run`` with ``worker_id`` if the signature accepts it.

    Older dispatchers ignore the kwarg; newer ones use it for
    ``claim_run``. We probe with ``inspect.signature`` once per call
    rather than caching, because the reload story for a hot-swapped
    dispatcher module is messy and probing is cheap.
    """
    import inspect

    dispatch_run = _resolve_dispatch_run()
    sig = inspect.signature(dispatch_run)
    if "worker_id" in sig.parameters:
        await dispatch_run(run_id, worker_id=worker_id)
    else:
        await dispatch_run(run_id)


# ── Main loops ─────────────────────────────────────────────────────────


async def _heartbeat_loop(worker_id: str, shutdown: asyncio.Event) -> None:
    """Refresh the worker heartbeat row on a fixed interval."""
    while not shutdown.is_set():
        try:
            async with async_session_factory() as session:
                refreshed = await WorkerRegistry.heartbeat(
                    session, worker_id=worker_id
                )
                if not refreshed:
                    # Row vanished (pruned, or DB reset) — re-register.
                    await WorkerRegistry.register(
                        session,
                        worker_id=worker_id,
                        hostname=_hostname(),
                        pid=os.getpid(),
                        capabilities={},
                    )
        except Exception:
            logger.exception("worker_heartbeat_error", worker_id=worker_id)

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=_HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def _invoke_reclaim(reclaim, worker_id: str) -> int:
    """Call ``reclaim_expired_runs`` with the right signature.

    W1.3 lands ``reclaim_expired_runs(session, *, lease_grace_seconds=10)``
    in ``run_lifecycle``. Earlier prototypes used a session-less
    ``reclaim_expired_runs(*, grace_seconds=...)`` shape. We probe via
    ``inspect.signature`` and call whichever fits.
    """
    import inspect

    sig = inspect.signature(reclaim)
    params = sig.parameters

    # Decide on the lease-grace kwarg name. Prefer lease_grace_seconds
    # (W1.3 canonical), fall back to grace_seconds, fall back to none.
    if "lease_grace_seconds" in params:
        grace_kwargs = {"lease_grace_seconds": _RECLAIM_GRACE_SECONDS}
    elif "grace_seconds" in params:
        grace_kwargs = {"grace_seconds": _RECLAIM_GRACE_SECONDS}
    else:
        grace_kwargs = {}

    # Decide on session passing. If the first positional parameter is
    # ``session``, we open a fresh AsyncSession; otherwise call
    # session-less.
    positional = [
        p for p in params.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    needs_session = bool(positional) and positional[0].name == "session"

    if needs_session:
        async with async_session_factory() as session:
            count = await reclaim(session, **grace_kwargs)
    else:
        count = await reclaim(**grace_kwargs)

    if isinstance(count, int):
        return count
    try:
        return len(count)  # type: ignore[arg-type]
    except TypeError:
        return 0


async def _reclaim_loop(worker_id: str, shutdown: asyncio.Event) -> None:
    """Periodically return expired-lease runs to the queue.

    Calls ``reclaim_expired_runs`` (from run_lifecycle / run_dispatcher)
    when available; no-ops cleanly otherwise. The dispatcher / lifecycle
    module is the single source of truth for what "expired" means.
    """
    while not shutdown.is_set():
        try:
            reclaim = _resolve_reclaim_expired_runs()
            if reclaim is not None:
                count = await _invoke_reclaim(reclaim, worker_id)
                if count:
                    logger.info(
                        "worker_reclaim_tick",
                        worker_id=worker_id,
                        reclaimed=count,
                    )
        except Exception:
            logger.exception("worker_reclaim_error", worker_id=worker_id)

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=_RECLAIM_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def _drain_loop(
    worker_id: str,
    semaphore: asyncio.Semaphore,
    shutdown: asyncio.Event,
) -> None:
    """Pull queued runs off the table and dispatch them.

    Algorithm (per tick):
      1. SELECT id FROM workflow_runs
         WHERE status IN ('queued','pending')
           AND (lease_expires_at IS NULL OR lease_expires_at < now())
         ORDER BY queued_at NULLS LAST, created_at
         LIMIT _RUN_BATCH_SIZE.
      2. For each row, acquire the semaphore (caps in-flight count) and
         dispatch via ``dispatch_run(run_id, worker_id=...)`` as a task.
      3. Track the task in ``_inflight``; remove on completion.

    Concurrency safety: the actual atomic claim happens inside
    ``dispatch_run`` (via the dispatcher's ``claim_run`` primitive when
    W1.3 lands it). Two workers seeing the same row both call
    ``dispatch_run``; the loser's call is a no-op — see the dispatcher's
    early-return on ``status != "pending"``.
    """
    if shutdown.is_set():
        return

    try:
        from sqlalchemy import text

        async with async_session_factory() as session:
            # NULLS LAST handling: SQLite treats NULL as LOWEST, so an explicit
            # CASE keeps queued_at-null rows (legacy data) at the back.
            now_naive = datetime.utcnow().isoformat(sep=" ")
            result = await session.exec(  # type: ignore[call-overload]
                text(
                    "SELECT id FROM workflow_runs "
                    "WHERE status IN ('queued','pending') "
                    "AND (lease_expires_at IS NULL "
                    "     OR lease_expires_at < :now) "
                    "ORDER BY "
                    "  CASE WHEN queued_at IS NULL THEN 1 ELSE 0 END, "
                    "  queued_at, created_at "
                    f"LIMIT {_RUN_BATCH_SIZE}"
                ).bindparams(now=now_naive)
            )
            candidate_ids = [row[0] for row in result]

        if not candidate_ids:
            return

        logger.debug("worker_drain_candidates", count=len(candidate_ids))

        from uuid import UUID as _UUID

        for run_id in candidate_ids:
            if shutdown.is_set():
                break
            run_uuid = _UUID(str(run_id)) if not isinstance(run_id, _UUID) else run_id
            task = asyncio.create_task(
                _dispatch_with_semaphore(run_uuid, worker_id, semaphore),
                name=f"dispatch-{run_uuid}",
            )
            _inflight.add(task)
            task.add_done_callback(_inflight.discard)

    except Exception:
        logger.exception("worker_drain_error", worker_id=worker_id)


async def _dispatch_with_semaphore(
    run_id,
    worker_id: str,
    semaphore: asyncio.Semaphore,
) -> None:
    """Acquire the semaphore, then dispatch.

    The semaphore caps the *in-flight* count. The drain loop creates
    tasks freely; the bottleneck is on entry to ``dispatch_run``.

    Phase 6 — concurrency quota: before invoking ``dispatch_run`` we
    consult the quota service. A throttled tenant leaves its run in
    ``queued`` status so the next drain tick (or another worker) picks
    it up after a slot frees. The dispatcher itself ALSO performs a
    pre-claim quota check; this drain-side check just avoids an
    unnecessary ``claim_run`` round trip when we already know the
    tenant is at cap.
    """
    async with semaphore:
        try:
            if not await _quota_drain_allows(run_id):
                # Throttled — leave queued for the next iteration.
                return
            await _call_dispatch_run(run_id, worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "worker_dispatch_error",
                run_id=str(run_id),
                worker_id=worker_id,
            )


async def _quota_drain_allows(run_id) -> bool:
    """Return True iff the run's tenant has headroom for a fresh dispatch.

    Resolves the run's tenant_id and workflow_id, then calls
    ``quota_service.reserve_slot``. On any error we fail OPEN so a
    quota substrate hiccup never blocks legitimate work — the
    dispatcher's own quota gate is the authoritative guard.
    """
    try:
        from app.models.workflow import WorkflowRun
        from app.services.quota_service import reserve_slot

        async with async_session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is None:
                return True  # let the dispatcher log the missing-id case
            allowed = await reserve_slot(
                session,
                tenant_id=run.tenant_id,
                workflow_id=run.workflow_id,
                run_id=run.id,
            )
            if not allowed:
                logger.info(
                    "worker_quota_throttle",
                    run_id=str(run.id),
                    tenant_id=str(run.tenant_id) if run.tenant_id else None,
                    workflow_id=(
                        str(run.workflow_id) if run.workflow_id else None
                    ),
                )
            return allowed
    except Exception:
        logger.exception("worker_quota_check_error", run_id=str(run_id))
        return True


# ── Timer fire loop (W2.4) ──────────────────────────────────────────────


async def _timer_fire_tick(worker_id: str) -> int:
    """One tick of the timer-fire loop.

    Algorithm:
      1. Drain any due timers via ``timer_service.fire_pending_timers``.
      2. For every fired timer that targets a run, flip that run from
         ``paused`` → ``queued`` so the drain loop re-picks it up.
      3. Emit a ``run.resumed`` event in the chain to record the
         transition.

    Returns the number of runs successfully resumed. Errors are logged
    but never raised — the worker loop must keep ticking even when
    individual transitions fail.
    """
    from sqlalchemy import update

    resumed = 0

    try:
        from app.services.timer_service import fire_pending_timers
        from app.services.run_dispatcher import _async_append_event
        from app.models.workflow import WorkflowRun
    except ImportError:
        # Timer service / dispatcher not yet present. No-op cleanly.
        return 0

    async with async_session_factory() as session:
        try:
            fired = await fire_pending_timers(
                session, batch_size=_TIMER_FIRE_BATCH
            )
        except Exception:
            logger.exception("worker_timer_fire_error", worker_id=worker_id)
            return 0

    for timer in fired:
        if timer.run_id is None:
            continue
        try:
            async with async_session_factory() as flip_session:
                # CAS flip: only resume if the run is still paused. If
                # another consumer (route handler, manual resume)
                # already flipped it, this update returns rowcount=0.
                stmt = (
                    update(WorkflowRun)
                    .where(WorkflowRun.id == timer.run_id)
                    .where(WorkflowRun.status == "paused")
                    .values(
                        status="queued",
                        resumed_at=datetime.utcnow(),
                        lease_owner=None,
                        lease_expires_at=None,
                    )
                )
                result = await flip_session.execute(stmt)
                rowcount = result.rowcount or 0
                if rowcount == 1:
                    run = await flip_session.get(WorkflowRun, timer.run_id)
                    if run is not None:
                        await _async_append_event(
                            flip_session,
                            run.id,
                            "run.resumed",
                            payload={
                                "reason": "timer_fired",
                                "timer_id": str(timer.id),
                                "purpose": timer.purpose,
                                "fire_at": (
                                    timer.fire_at.isoformat()
                                    if timer.fire_at
                                    else None
                                ),
                            },
                            tenant_id=run.tenant_id,
                            step_id=timer.step_id,
                        )
                await flip_session.commit()
                if rowcount == 1:
                    resumed += 1
                    logger.info(
                        "worker_timer_resumed_run",
                        worker_id=worker_id,
                        run_id=str(timer.run_id),
                        timer_id=str(timer.id),
                        purpose=timer.purpose,
                    )
        except Exception:
            logger.exception(
                "worker_timer_resume_error",
                worker_id=worker_id,
                run_id=str(timer.run_id),
                timer_id=str(timer.id),
            )

    return resumed


async def _timer_fire_loop(worker_id: str, shutdown: asyncio.Event) -> None:
    """Periodically drain due timers and resume their paused runs.

    Coexists with the drain loop: we flip status from paused → queued,
    drain claims queued. The two loops never contend because their
    target statuses are disjoint.
    """
    while not shutdown.is_set():
        try:
            count = await _timer_fire_tick(worker_id)
            if count:
                logger.info(
                    "worker_timer_tick",
                    worker_id=worker_id,
                    resumed=count,
                )
        except Exception:
            logger.exception("worker_timer_loop_error", worker_id=worker_id)

        try:
            await asyncio.wait_for(
                shutdown.wait(), timeout=_TIMER_FIRE_INTERVAL
            )
        except asyncio.TimeoutError:
            pass


# ── Public entry point ────────────────────────────────────────────────


async def run_worker(
    *,
    worker_id: str | None = None,
    max_concurrent: int = 50,
) -> None:
    """Main worker loop. Heartbeats, drains pending runs, reclaims expired.

    Args:
        worker_id: Stable identifier for this process. Auto-generated
            (``hostname-pid-shortuuid``) when omitted.
        max_concurrent: Cap on simultaneous in-flight dispatches.

    Returns when ``_shutdown`` is set (SIGINT/SIGTERM or a programmatic
    ``request_shutdown()`` call). Awaits in-flight dispatches up to
    ``_SHUTDOWN_GRACE_SECONDS`` before returning. Heartbeat row is
    deleted on graceful shutdown.
    """
    global _shutdown, _dispatch_semaphore

    _shutdown = asyncio.Event()
    _dispatch_semaphore = asyncio.Semaphore(max_concurrent)

    if worker_id is None:
        worker_id = _generate_worker_id()

    logger.info(
        "worker_starting",
        worker_id=worker_id,
        pid=os.getpid(),
        hostname=_hostname(),
        max_concurrent=max_concurrent,
    )

    # Register signal handlers — best effort. On platforms / loops that
    # don't support add_signal_handler (e.g. running inside pytest's
    # synchronous loop fixture), we silently skip; the caller can still
    # set _shutdown manually.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal_default, sig)
        except (NotImplementedError, RuntimeError):
            pass

    # Initial registration. If this fails, surface the error — a worker
    # that can't register can't be reasoned about.
    async with async_session_factory() as session:
        await WorkerRegistry.register(
            session,
            worker_id=worker_id,
            hostname=_hostname(),
            pid=os.getpid(),
            capabilities={},
        )

    # Slow loop preserved from the legacy worker.
    async def _slow_loop() -> None:
        scan_interval = 300
        while not _shutdown.is_set():
            try:
                await _run_scheduled_scans()
                await _run_rotation_checks()
                await _run_budget_alerts()
                await _check_scheduled_workflows()
                await _run_improvement_analysis()
            except Exception:
                logger.exception("worker_slow_tick_error")

            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=scan_interval)
            except asyncio.TimeoutError:
                pass

    async def _drain_tick_loop() -> None:
        while not _shutdown.is_set():
            await _drain_loop(worker_id, _dispatch_semaphore, _shutdown)
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=_DRAIN_INTERVAL)
            except asyncio.TimeoutError:
                pass

    try:
        await asyncio.gather(
            _heartbeat_loop(worker_id, _shutdown),
            _reclaim_loop(worker_id, _shutdown),
            _drain_tick_loop(),
            _timer_fire_loop(worker_id, _shutdown),
            _slow_loop(),
        )
    finally:
        await _shutdown_cleanup(worker_id)


async def _shutdown_cleanup(worker_id: str) -> None:
    """Wait for in-flight dispatches and deregister the worker.

    Bounded by ``_SHUTDOWN_GRACE_SECONDS``. Tasks still running after
    the grace are cancelled (ungraceful — but bounded). The heartbeat
    row is always deleted, even if dispatch cleanup throws.
    """
    pending = list(_inflight)
    if pending:
        logger.info(
            "worker_awaiting_inflight",
            worker_id=worker_id,
            count=len(pending),
            timeout=_SHUTDOWN_GRACE_SECONDS,
        )
        try:
            done, still_running = await asyncio.wait(
                pending, timeout=_SHUTDOWN_GRACE_SECONDS
            )
            if still_running:
                logger.warning(
                    "worker_inflight_timeout_cancel",
                    worker_id=worker_id,
                    cancelled=len(still_running),
                )
                for t in still_running:
                    t.cancel()
                # Best-effort gather to surface CancelledError cleanup.
                await asyncio.gather(*still_running, return_exceptions=True)
        except Exception:
            logger.exception("worker_shutdown_inflight_error", worker_id=worker_id)

    try:
        async with async_session_factory() as session:
            await WorkerRegistry.deregister(session, worker_id=worker_id)
    except Exception:
        logger.exception("worker_deregister_error", worker_id=worker_id)

    logger.info("worker_stopped", worker_id=worker_id)


def _handle_signal_default(sig: signal.Signals) -> None:
    """SIGINT / SIGTERM handler — set the shutdown event."""
    if _shutdown is None:
        # Signal arrived before run_worker created the event — best
        # effort, store nothing. The kernel will retry.
        return
    logger.info("worker_signal_received", signal=sig.name)
    _shutdown.set()


def request_shutdown() -> None:
    """Programmatic shutdown trigger — used by tests and by main()."""
    if _shutdown is not None:
        _shutdown.set()


# ── Entry point ────────────────────────────────────────────────────────


async def main() -> None:
    """Configure logging and run the worker until shutdown."""
    setup_logging(log_level="INFO")
    logger.info("worker_started", time=datetime.now(tz=timezone.utc).isoformat())
    await run_worker(max_concurrent=_MAX_CONCURRENT_RUNS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)


# ── Backwards-compat re-exports ────────────────────────────────────────
#
# The legacy worker exposed ``_drain_pending_runs`` and
# ``_dispatch_already_running`` for tests and operators. The new flow
# routes drain through ``_drain_loop`` and lets the dispatcher own the
# state machine — ``_dispatch_already_running`` is dead code (Conflict 2).
# ``_drain_pending_runs`` is preserved as a thin shim for any caller
# (mostly older tests) that imports it directly.


async def _drain_pending_runs() -> None:  # pragma: no cover — legacy shim
    """DEPRECATED: prefer ``_drain_loop``. Kept for legacy callers."""
    if _dispatch_semaphore is None or _shutdown is None:
        # Worker isn't running — synthesise the bare minimum and run
        # one drain tick to keep imports working.
        sem = asyncio.Semaphore(_MAX_CONCURRENT_RUNS)
        ev = asyncio.Event()
        await _drain_loop("legacy-shim", sem, ev)
    else:
        await _drain_loop("legacy-shim", _dispatch_semaphore, _shutdown)
