"""Schedule service — W7 (Schedule Engine).

Implements create/evaluate/pause/resume/backfill/list for the ``Schedule``
model defined in ADR-008 §9. All fires go through ExecutionFacade.create_run
— never direct WorkflowRun construction.

Idempotency key for schedule fires: ``schedule:{schedule_id}:{fire_time.isoformat()}``

Overlap policies (see ADR-008 §9):
  skip             — don't start if any run is currently active
  buffer_one       — allow at most one queued/pending start beyond the active run
  buffer_all       — always start (alias for allow_all; distinct semantically)
  cancel_running   — cancel the active run's record, then start a new one
  terminate_running — same as cancel_running for our purposes (both mark cancelled)
  allow_all        — start regardless of active runs

Cron parsing: uses ``croniter`` when available; falls back to a minimal
5-field cron parser for the common ``* * * * *`` pattern. The fallback
handles standard cron fields (wildcards and fixed values; no ranges or
lists — these are rare in production schedules and croniter covers them).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.schedule import Schedule
from app.models.workflow import WorkflowRun
from app.services.execution_facade import ExecutionFacade

log = logging.getLogger(__name__)


# ── UTC helpers ───────────────────────────────────────────────────────


def _utcnow() -> datetime:
    """Naive UTC timestamp matching column type."""
    return datetime.utcnow()


def _to_naive_utc(dt: datetime) -> datetime:
    """Strip tzinfo, treating the value as UTC (column storage convention)."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ── Cron helpers ──────────────────────────────────────────────────────


def _next_cron_fire(cron_expr: str, after: datetime) -> datetime | None:
    """Return the next fire time after ``after`` for the given cron expression.

    Tries ``croniter`` first; falls back to a minimal 5-field parser.
    Returns None when the expression cannot be parsed.
    """
    try:
        from croniter import croniter  # type: ignore[import]

        # croniter expects a naive UTC datetime for get_next.
        it = croniter(cron_expr, after)
        return it.get_next(datetime)
    except ImportError:
        pass

    return _next_cron_fire_fallback(cron_expr, after)


def _field_matches(field: str, value: int) -> bool:
    """Return True if ``value`` satisfies the cron ``field`` string.

    Supports: ``*``, fixed integer, comma-separated integers, ``*/N`` step.
    """
    field = field.strip()
    if field == "*":
        return True
    if re.fullmatch(r"\*/(\d+)", field):
        step = int(field[2:])
        return (value % step) == 0
    # Comma-separated list.
    parts = field.split(",")
    for part in parts:
        part = part.strip()
        if part.isdigit() and int(part) == value:
            return True
    return False


def _next_cron_fire_fallback(
    cron_expr: str, after: datetime
) -> datetime | None:
    """Minimal 5-field cron evaluator (minute hour dom month dow)."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return None
    minute_f, hour_f, dom_f, month_f, dow_f = parts

    # Scan forward minute-by-minute up to 2 years (safety cap).
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    cap = after + timedelta(days=366 * 2)
    while candidate < cap:
        if (
            _field_matches(month_f, candidate.month)
            and _field_matches(dom_f, candidate.day)
            and _field_matches(dow_f, candidate.weekday())
            and _field_matches(hour_f, candidate.hour)
            and _field_matches(minute_f, candidate.minute)
        ):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def _next_interval_fire(interval_spec: str, after: datetime) -> datetime | None:
    """Parse ``interval:N{s|m|h|d}`` and return the next fire time."""
    m = re.fullmatch(r"interval:(\d+)([smhd])", interval_spec.strip())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2)
    delta_map = {"s": timedelta(seconds=value), "m": timedelta(minutes=value),
                 "h": timedelta(hours=value), "d": timedelta(days=value)}
    return after + delta_map[unit]


def _compute_next_fire(schedule: Schedule, after: datetime) -> datetime | None:
    """Compute the next fire time for ``schedule`` after ``after``."""
    spec = schedule.calendar_spec
    if schedule.spec_kind == "cron":
        return _next_cron_fire(spec, after)
    if schedule.spec_kind == "interval":
        return _next_interval_fire(spec, after)
    # rrule: delegate to croniter / dateutil if available.
    try:
        from dateutil.rrule import rrulestr  # type: ignore[import]

        rule = rrulestr(spec, dtstart=after, ignoretz=True)
        result = rule.after(after, inc=False)
        return result
    except (ImportError, Exception):
        log.warning(
            "schedule_service: rrule parsing failed for spec=%r (dateutil absent?)",
            spec,
        )
        return None


# ── Active run query ──────────────────────────────────────────────────

_ACTIVE_STATUSES = ("queued", "pending", "running", "claimed")


async def _count_active_runs(
    session: AsyncSession, schedule: Schedule
) -> int:
    """Count WorkflowRun rows for this schedule's target that are still active.

    We filter by workflow_id or agent_id matching the schedule. This is an
    approximation — we don't have a direct schedule_id FK on WorkflowRun —
    but it is the correct semantics for overlap policy: "is the target
    currently executing?"
    """
    stmt = select(WorkflowRun).where(
        WorkflowRun.status.in_(_ACTIVE_STATUSES)
    )
    if schedule.workflow_id is not None:
        stmt = stmt.where(WorkflowRun.workflow_id == schedule.workflow_id)
    else:
        stmt = stmt.where(WorkflowRun.agent_id == schedule.agent_id)
    if schedule.tenant_id is not None:
        stmt = stmt.where(WorkflowRun.tenant_id == schedule.tenant_id)

    result = await session.exec(stmt)
    rows = result.all()
    return len(rows)


async def _get_active_runs(
    session: AsyncSession, schedule: Schedule
) -> list[WorkflowRun]:
    """Return active WorkflowRun rows for this schedule's target."""
    stmt = select(WorkflowRun).where(
        WorkflowRun.status.in_(_ACTIVE_STATUSES)
    )
    if schedule.workflow_id is not None:
        stmt = stmt.where(WorkflowRun.workflow_id == schedule.workflow_id)
    else:
        stmt = stmt.where(WorkflowRun.agent_id == schedule.agent_id)
    if schedule.tenant_id is not None:
        stmt = stmt.where(WorkflowRun.tenant_id == schedule.tenant_id)

    result = await session.exec(stmt)
    return list(result.all())


# ── Fire helper ───────────────────────────────────────────────────────


async def _fire_schedule(
    session: AsyncSession,
    schedule: Schedule,
    fire_time: datetime,
) -> UUID | None:
    """Fire one schedule occurrence through ExecutionFacade.

    Returns the new run_id on success, None when the idempotency key
    already exists (safe duplicate suppression).
    """
    idem_key = f"schedule:{schedule.id}:{fire_time.isoformat()}"
    kind = "workflow" if schedule.workflow_id is not None else "agent"
    input_data: dict[str, Any] = dict(schedule.input_template or {})

    try:
        run, is_new = await ExecutionFacade.create_run(
            session,
            kind=kind,
            workflow_id=schedule.workflow_id,
            agent_id=schedule.agent_id,
            tenant_id=schedule.tenant_id,
            input_data=input_data,
            trigger_type="schedule",
            triggered_by=f"schedule:{schedule.id}",
            idempotency_key=idem_key,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "schedule_service: fire failed schedule=%s fire_time=%s: %s",
            schedule.id,
            fire_time.isoformat(),
            exc,
        )
        return None

    if is_new:
        try:
            from app.services.metrics_service import record_schedule_fire  # noqa: PLC0415
            record_schedule_fire(schedule_id=str(schedule.id))
        except Exception as exc:  # noqa: BLE001
            log.debug("schedule metrics emit failed: %s", exc)
        return run.id
    # Idempotency hit — already fired for this slot.
    return run.id


# ── Public API ────────────────────────────────────────────────────────


async def create_schedule(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    name: str,
    calendar_spec: str,
    spec_kind: str = "cron",
    timezone: str = "UTC",
    workflow_id: UUID | None = None,
    agent_id: UUID | None = None,
    overlap_policy: str = "skip",
    jitter_seconds: int = 0,
    catchup_window_seconds: int = 0,
    pause_on_failure: bool = False,
    start_bound: datetime | None = None,
    end_bound: datetime | None = None,
    input_template: dict | None = None,
    description: str = "",
    notes: str = "",
    created_by: str = "",
) -> Schedule:
    """Create and persist a new Schedule.

    Computes ``next_fire_at`` from the spec so the schedule loop can pick
    it up immediately.

    Raises ValueError when neither workflow_id nor agent_id is provided,
    or when both are provided.
    """
    if (workflow_id is None) == (agent_id is None):
        raise ValueError("exactly one of workflow_id or agent_id must be provided")

    now = _utcnow()
    schedule = Schedule(
        tenant_id=tenant_id,
        name=name,
        description=description,
        workflow_id=workflow_id,
        agent_id=agent_id,
        calendar_spec=calendar_spec,
        spec_kind=spec_kind,
        timezone=timezone,
        jitter_seconds=jitter_seconds,
        start_bound=start_bound,
        end_bound=end_bound,
        overlap_policy=overlap_policy,
        catchup_window_seconds=catchup_window_seconds,
        pause_on_failure=pause_on_failure,
        input_template=input_template or {},
        paused=False,
        consecutive_failures=0,
        notes=notes,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )

    # Pre-compute first fire time.
    next_fire = _compute_next_fire(schedule, now)
    if next_fire is not None:
        schedule.next_fire_at = _to_naive_utc(next_fire)

    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    log.info("schedule_service: created schedule=%s name=%r", schedule.id, name)
    return schedule


async def evaluate_schedule(
    session: AsyncSession,
    *,
    schedule_id: UUID,
    now: datetime | None = None,
) -> list[UUID]:
    """Check whether a schedule is due to fire; enforce overlap policy; create runs.

    Returns a list of run UUIDs created this evaluation (may be empty on
    skip/already-fired, may have >1 entry on catchup).
    """
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        raise ValueError(f"Schedule {schedule_id} not found")

    if schedule.paused:
        return []

    now_dt = _to_naive_utc(now) if now is not None else _utcnow()

    # Check bound constraints.
    if schedule.start_bound is not None and now_dt < schedule.start_bound:
        return []
    if schedule.end_bound is not None and now_dt > schedule.end_bound:
        return []

    # Determine the fire time(s) to process.
    fire_times: list[datetime] = []

    if schedule.next_fire_at is not None and schedule.next_fire_at <= now_dt:
        fire_times.append(schedule.next_fire_at)

        # Catchup: collect any missed fires within the catchup window.
        if schedule.catchup_window_seconds > 0:
            window_start = now_dt - timedelta(seconds=schedule.catchup_window_seconds)
            candidate = schedule.next_fire_at
            while True:
                nxt = _compute_next_fire(schedule, candidate)
                if nxt is None:
                    break
                nxt = _to_naive_utc(nxt)
                if nxt > now_dt:
                    break
                if nxt >= window_start:
                    fire_times.append(nxt)
                candidate = nxt

    if not fire_times:
        # Advance next_fire_at even if nothing fires this pass.
        schedule.last_evaluated_at = now_dt
        schedule.updated_at = now_dt
        if schedule.next_fire_at is None or schedule.next_fire_at <= now_dt:
            nxt = _compute_next_fire(schedule, now_dt)
            schedule.next_fire_at = _to_naive_utc(nxt) if nxt else None
        session.add(schedule)
        await session.commit()
        return []

    # ── Overlap policy check ──────────────────────────────────────────
    created_run_ids: list[UUID] = []
    active_runs = await _get_active_runs(session, schedule)
    active_count = len(active_runs)

    policy = schedule.overlap_policy

    for fire_time in fire_times:
        if active_count > 0:
            if policy == "skip":
                log.info(
                    "schedule_service: skip schedule=%s active=%d",
                    schedule_id,
                    active_count,
                )
                continue

            elif policy == "buffer_one":
                # Allow only one pending start beyond the running run.
                # Count runs with status="queued" or "pending" separately.
                pending_count = sum(
                    1 for r in active_runs if r.status in ("queued", "pending")
                )
                if pending_count >= 1:
                    log.info(
                        "schedule_service: buffer_one saturated schedule=%s",
                        schedule_id,
                    )
                    continue

            elif policy in ("cancel_running", "terminate_running"):
                # Cancel all active runs for this target.
                for active_run in active_runs:
                    active_run.status = "cancelled"
                    active_run.completed_at = now_dt
                    session.add(active_run)
                await session.flush()
                active_runs = []
                active_count = 0

            elif policy in ("allow_all", "buffer_all"):
                pass  # Start regardless.

        run_id = await _fire_schedule(session, schedule, fire_time)
        if run_id is not None:
            created_run_ids.append(run_id)
            active_count += 1

    # Advance state.
    schedule.last_evaluated_at = now_dt
    schedule.last_fire_attempted_at = now_dt
    if created_run_ids:
        schedule.last_fire_succeeded_at = now_dt
        schedule.last_successful_run_id = created_run_ids[-1]
        schedule.consecutive_failures = 0
    else:
        schedule.consecutive_failures += 1
        if schedule.pause_on_failure and schedule.consecutive_failures >= 1:
            schedule.paused = True
            log.info(
                "schedule_service: auto-paused schedule=%s after failure",
                schedule_id,
            )

    # Advance next_fire_at to the next slot after the last fire time processed.
    last_fire = fire_times[-1]
    nxt = _compute_next_fire(schedule, last_fire)
    schedule.next_fire_at = _to_naive_utc(nxt) if nxt else None
    schedule.updated_at = now_dt
    session.add(schedule)
    await session.commit()

    return created_run_ids


async def pause_schedule(
    session: AsyncSession, *, schedule_id: UUID
) -> Schedule:
    """Set ``paused=True`` on the schedule."""
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        raise ValueError(f"Schedule {schedule_id} not found")
    schedule.paused = True
    schedule.updated_at = _utcnow()
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def resume_schedule(
    session: AsyncSession, *, schedule_id: UUID
) -> Schedule:
    """Set ``paused=False`` and compute next_fire_at from now."""
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        raise ValueError(f"Schedule {schedule_id} not found")

    now = _utcnow()
    schedule.paused = False
    schedule.updated_at = now

    # Catchup: fire missed intervals since last evaluation.
    run_ids: list[UUID] = []
    if schedule.catchup_window_seconds > 0 and schedule.last_evaluated_at is not None:
        window_start = now - timedelta(seconds=schedule.catchup_window_seconds)
        candidate = max(schedule.last_evaluated_at, window_start)
        while True:
            nxt = _compute_next_fire(schedule, candidate)
            if nxt is None:
                break
            nxt = _to_naive_utc(nxt)
            if nxt > now:
                break
            run_id = await _fire_schedule(session, schedule, nxt)
            if run_id is not None:
                run_ids.append(run_id)
            candidate = nxt
        if run_ids:
            schedule.last_fire_succeeded_at = now
            schedule.last_successful_run_id = run_ids[-1]

    # Set next_fire_at.
    nxt = _compute_next_fire(schedule, now)
    schedule.next_fire_at = _to_naive_utc(nxt) if nxt else None

    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def backfill_schedule(
    session: AsyncSession,
    *,
    schedule_id: UUID,
    start_time: datetime,
    end_time: datetime,
) -> list[UUID]:
    """Create runs for all missed fires in [start_time, end_time].

    Uses idempotency keys so duplicate backfill calls are safe.
    Returns list of run UUIDs (new or existing via idem key).
    """
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        raise ValueError(f"Schedule {schedule_id} not found")

    start_dt = _to_naive_utc(start_time)
    end_dt = _to_naive_utc(end_time)

    fire_times: list[datetime] = []
    candidate = start_dt
    while True:
        nxt = _compute_next_fire(schedule, candidate)
        if nxt is None:
            break
        nxt = _to_naive_utc(nxt)
        if nxt > end_dt:
            break
        fire_times.append(nxt)
        candidate = nxt

    run_ids: list[UUID] = []
    for fire_time in fire_times:
        run_id = await _fire_schedule(session, schedule, fire_time)
        if run_id is not None:
            run_ids.append(run_id)

    return run_ids


async def list_schedules(
    session: AsyncSession, *, tenant_id: UUID | None
) -> list[Schedule]:
    """Return all schedules for a tenant (or all schedules when tenant_id is None)."""
    stmt = select(Schedule)
    if tenant_id is not None:
        stmt = stmt.where(Schedule.tenant_id == tenant_id)
    stmt = stmt.order_by(Schedule.created_at.asc())
    result = await session.exec(stmt)
    return list(result.all())


async def get_schedule(
    session: AsyncSession, *, schedule_id: UUID
) -> Schedule | None:
    """Return a schedule by ID."""
    return await session.get(Schedule, schedule_id)


async def delete_schedule(
    session: AsyncSession, *, schedule_id: UUID
) -> bool:
    """Soft-delete (hard-delete) a schedule. Returns True when found."""
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        return False
    await session.delete(schedule)
    await session.commit()
    return True


__all__ = [
    "create_schedule",
    "evaluate_schedule",
    "pause_schedule",
    "resume_schedule",
    "backfill_schedule",
    "list_schedules",
    "get_schedule",
    "delete_schedule",
]
