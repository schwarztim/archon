"""Archon background worker for async tasks.

Handles scheduled scans, secret rotation checks, and budget alerts.
Run via: python3 -m app.worker
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone

from app.logging_config import get_logger, setup_logging

logger = get_logger(__name__)

_shutdown = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    """Set shutdown event on SIGINT/SIGTERM."""
    logger.info("worker_signal_received", signal=sig.name)
    _shutdown.set()


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
            # Find secrets where next_rotation_at or expires_at is in the past or within notify window
            stmt = select(SecretRegistration).where(
                SecretRegistration.expires_at.isnot(None),  # type: ignore[union-attr]
            )
            result = await session.exec(stmt)
            registrations = list(result.all())

            for reg in registrations:
                if reg.expires_at is None:
                    continue
                # Make comparison timezone-aware
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

                # Check each threshold in descending order
                for threshold in sorted(budget.alert_thresholds, reverse=True):
                    if usage_pct >= threshold:
                        # Check if an alert for this threshold already exists (unacknowledged)
                        existing_stmt = select(CostAlert).where(
                            CostAlert.budget_id == budget.id,
                            CostAlert.threshold_pct == threshold,
                            CostAlert.is_acknowledged == False,  # noqa: E712
                        )
                        existing = await session.exec(existing_stmt)
                        if existing.first() is not None:
                            break  # Already alerted at this threshold

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
                        break  # Only create alert for highest breached threshold

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
            # Query all enabled schedules joined with their workflow
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
            # Naive UTC for storage (models use TIMESTAMP WITHOUT TIME ZONE)
            now_naive = datetime.utcnow()

            runs_created = 0
            for schedule, workflow in rows:
                try:
                    # Determine the reference point: last_run_at or a point before now
                    if schedule.last_run_at is not None:
                        last_run = schedule.last_run_at
                        # Ensure naive UTC for croniter
                        if last_run.tzinfo is not None:
                            last_run = last_run.replace(tzinfo=None)
                    else:
                        # First run: use one interval before now so we fire immediately
                        cron_iter = croniter(schedule.cron, now_naive)
                        last_run = cron_iter.get_prev(datetime)

                    cron_iter = croniter(schedule.cron, last_run)
                    next_run = cron_iter.get_next(datetime)  # naive UTC

                    if next_run <= now_naive:
                        # Workflow is due — create a run record
                        run = WorkflowRun(
                            workflow_id=workflow.id,
                            tenant_id=workflow.tenant_id,
                            status="pending",
                            trigger_type="schedule",
                            triggered_by="scheduler",
                        )
                        session.add(run)

                        # Advance to the following next_run for storage
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
                        # Not due yet — update next_run_at if stale
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
    """Run the improvement engine analysis cycle on the configured interval.

    Uses GAP_ANALYSIS_INTERVAL_HOURS from settings to throttle runs.
    Skips if the engine is disabled or the interval has not elapsed.
    """
    logger.debug("improvement_analysis_tick")
    try:
        from app.config import settings

        if not settings.IMPROVEMENT_ENGINE_ENABLED:
            return

        global _last_improvement_run
        now = datetime.now(tz=timezone.utc)

        # Check if enough time has passed since the last run
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


async def main() -> None:
    """Run the worker event loop until shutdown signal."""
    setup_logging(log_level="INFO")
    logger.info("worker_started", time=datetime.now(tz=timezone.utc).isoformat())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    scan_interval = 300  # seconds

    while not _shutdown.is_set():
        try:
            await _run_scheduled_scans()
            await _run_rotation_checks()
            await _run_budget_alerts()
            await _check_scheduled_workflows()
            await _run_improvement_analysis()
        except Exception:
            logger.exception("worker_tick_error")

        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=scan_interval)
        except asyncio.TimeoutError:
            pass

    logger.info("worker_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
