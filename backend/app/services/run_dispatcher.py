"""Unified workflow run dispatcher.

Owned by WS3 — Durable Execution Squad. Bound by:

- ADR-001  unified ``workflow_runs`` table; the engine MUST execute
            ``definition_snapshot``, never the live ``workflows`` row.
- ADR-002  every run/state/step transition emits a hash-chained event
            via ``event_service.append_event`` in the same transaction.
- ADR-005  durability of the run substrate (checkpointer policy lives
            elsewhere, but this dispatcher must persist step results so
            the checkpointer + event chain are consistent).
- ADR-006  ``executions``-table IDs must NOT silently no-op when passed
            to ``dispatch_run`` (closes Conflict 9).

Public surface
--------------

- ``dispatch_run(run_id, *, worker_id=None)``  REST/worker entry point.
- ``claim_and_dispatch(run_id, worker_id=None)``  internal driver.
- ``execute_claimed_run(session, run)``  in-process executor (no
   claim/lease handling — the caller already owns the row).

Behaviour summary
-----------------

1. Look up the run by ID. If absent from ``workflow_runs`` we log a
   loud error and return ``None`` — the prior implementation silently
   no-op'd on legacy ``Execution.id`` values, which hid Conflict 9 in
   production.
2. Honour ``cancel_requested_at`` set before the claim — moves the row
   to ``status='cancelled'`` and emits ``run.cancelled`` without doing
   any engine work.
3. Atomically claim via ``run_lifecycle.claim_run``. Lost claims return
   ``None`` (idempotent — another worker is already executing).
4. Emit ``run.claimed`` and ``run.started`` events.
5. Build the engine workflow dict from ``definition_snapshot`` (per
   ADR-001), wire an ``on_step_event`` callback that is best-effort
   (tolerates engine implementations that don't invoke the callback),
   and call ``execute_workflow_dag``.
6. Persist every step from ``result["steps"]`` into
   ``workflow_run_steps`` and emit a ``step.*`` event for each step.
7. Finalise the run row: status, output_data, completed_at, duration,
   metrics aggregate (cost + tokens). Emit ``run.completed`` /
   ``run.failed`` / ``run.cancelled``.
8. Any unhandled exception → ``status='failed'`` + ``run.failed``
   event whose payload carries a truncated traceback.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

# Module-level imports so tests can patch these names.
from app.database import async_session_factory  # noqa: E402
from app.middleware import metrics_middleware as _metrics  # noqa: E402
from app.services import event_service, signal_service, timer_service  # noqa: E402
from app.services.retry_policy import RetryPolicy  # noqa: E402
from app.services.run_lifecycle import claim_run  # noqa: E402
from app.services.tracing import span as _trace_span  # noqa: E402
from app.services.workflow_engine import execute_workflow_dag  # noqa: E402

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Artifact extraction shim — delegates to W5.3's artifact_service.
# Runs on every step output to swap large blobs for ``_artifact_ref``
# shims. Falls through to passthrough on any failure so a missing /
# misconfigured artifact substrate never breaks the dispatcher.
# ----------------------------------------------------------------------


async def _maybe_extract_step_output_as_artifact(
    session: AsyncSession,
    *,
    tenant_id: Any,
    run_id: Any,
    step_id: str,
    output_data: Any,
) -> Any:
    """Delegate to ``artifact_service.maybe_persist_output_as_artifact``.

    Returns ``output_data`` unchanged on any error. The dispatcher must
    never fail because the artifact substrate is unavailable.
    """
    if output_data is None:
        return None
    try:
        from app.services.artifact_service import (  # noqa: PLC0415
            maybe_persist_output_as_artifact,
        )

        return await maybe_persist_output_as_artifact(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            step_id=step_id,
            output_data=output_data,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("artifact_extraction_failed: %s", exc)
        return output_data


def _emit_run_terminal_metrics(
    run,  # WorkflowRun
    *,
    duration_ms: int | None,
) -> None:
    """Emit canonical run-terminal metrics. Non-blocking — never raises.

    Bound to: archon_workflow_runs_total, archon_workflow_run_duration_seconds,
    archon_run_cancellations_total (when status == 'cancelled').
    """
    try:
        tenant_id = (
            str(run.tenant_id) if getattr(run, "tenant_id", None) else "unknown"
        )
        kind = getattr(run, "kind", "workflow") or "workflow"
        status = getattr(run, "status", "completed") or "completed"
        _metrics.record_workflow_run(status, tenant_id, kind=kind)
        if duration_ms is not None:
            _metrics.record_workflow_duration(
                duration_ms / 1000.0,
                tenant_id=tenant_id,
                kind=kind,
                status=status,
            )
        if status == "cancelled":
            reason = getattr(run, "error_code", None) or "cancel_requested"
            _metrics.record_run_cancellation(tenant_id=tenant_id, reason=reason)
    except Exception as exc:  # noqa: BLE001 — emission must never raise
        log.debug("_emit_run_terminal_metrics failed: %s", exc)


def _emit_step_metrics(
    run,  # WorkflowRun
    step_payload: dict,
) -> None:
    """Emit per-step metrics from an engine step payload. Non-blocking.

    Bound to: archon_step_duration_seconds, archon_step_retries_total
    (when status='retry').
    """
    try:
        tenant_id = (
            str(run.tenant_id) if getattr(run, "tenant_id", None) else "unknown"
        )
        node_type = (
            step_payload.get("node_type")
            or step_payload.get("type")
            or "unknown"
        )
        status = step_payload.get("status") or "completed"
        duration_ms = step_payload.get("duration_ms") or 0
        _metrics.record_step_duration(
            int(duration_ms) / 1000.0,
            tenant_id=tenant_id,
            node_type=str(node_type),
            status=status,
        )
        if status == "retry":
            _metrics.record_step_retry(
                tenant_id=tenant_id,
                node_type=str(node_type),
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("_emit_step_metrics failed: %s", exc)


def _emit_step_retry(run, *, node_type: str | None) -> None:
    """Explicit retry counter increment from the retry-orchestration path."""
    try:
        tenant_id = (
            str(run.tenant_id) if getattr(run, "tenant_id", None) else "unknown"
        )
        _metrics.record_step_retry(
            tenant_id=tenant_id,
            node_type=str(node_type or "unknown"),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("_emit_step_retry failed: %s", exc)


# Phase 6: per-tenant + per-workflow concurrency quota throttling.
#
# archon_quota_throttled_total{tenant_id, workflow_id} — incremented
# every time the quota gate denies a dispatch claim. Stored locally
# (defaultdict) so the dispatcher does not depend on a metrics-side
# helper that hasn't yet been added; routed through
# ``_metrics.record_quota_throttle`` when that helper exists, so the
# counter integrates with /metrics if/when downstream wiring lands.
from collections import defaultdict as _defaultdict  # noqa: E402

_quota_throttled_counts: dict[tuple[str, str], int] = _defaultdict(int)


def _emit_quota_throttle(*, tenant_id: str, workflow_id: str) -> None:
    """Increment the quota-throttle counter; non-blocking."""
    _quota_throttled_counts[(tenant_id, workflow_id)] += 1
    try:
        recorder = getattr(_metrics, "record_quota_throttle", None)
        if recorder is not None:
            recorder(tenant_id=tenant_id, workflow_id=workflow_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("_emit_quota_throttle metrics middleware emit failed: %s", exc)


def _get_quota_throttled_count(
    *, tenant_id: str | None = None, workflow_id: str | None = None
) -> int:
    """Test helper: read the in-process quota throttle counter.

    Aggregates across labels when ``tenant_id`` / ``workflow_id`` are
    None. The counter is process-local — tests assert against it after
    triggering a throttled dispatch.
    """
    total = 0
    for (t, w), count in _quota_throttled_counts.items():
        if tenant_id is not None and t != tenant_id:
            continue
        if workflow_id is not None and w != workflow_id:
            continue
        total += count
    return total

# Batch size for pending-run drain; override via env. Retained for
# backwards-compat with the worker; not consumed by this module directly.
_BATCH_SIZE = int(os.environ.get("ARCHON_RUN_BATCH_SIZE", "10"))
# Max concurrent in-flight dispatches; override via env.
_MAX_CONCURRENT = int(os.environ.get("ARCHON_MAX_CONCURRENT_RUNS", "50"))


# ----------------------------------------------------------------------
# Async event helper (keeps ADR-002 chain sequential on AsyncSession)
# ----------------------------------------------------------------------


async def _async_append_event(
    session: AsyncSession,
    run_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    *,
    tenant_id: UUID | None = None,
    step_id: str | None = None,
    correlation_id: str | None = None,
    span_id: str | None = None,
) -> None:
    """Append a single hash-chained event using the AsyncSession.

    Mirrors the synchronous ``event_service.append_event`` helper but
    operates on ``AsyncSession``. The hashing logic itself is reused
    from ``event_service`` so the chain is bit-for-bit identical to
    rows written from sync callers.

    The function flushes — the surrounding transaction commits at the
    natural boundary (e.g. after the run row is updated).
    """
    if event_type not in event_service.EVENT_TYPES:
        raise ValueError(
            f"unknown event_type {event_type!r}; must be one of EVENT_TYPES"
        )

    from app.models.workflow import WorkflowRunEvent  # local import — avoid cycles

    prior_stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence.desc())
        .limit(1)
    )
    # Use ``session.exec`` (sqlmodel) when available — it returns a
    # ScalarResult whose ``.first()`` is sync. Fall back to the SQLAlchemy
    # native ``session.execute`` shape (Result -> .scalars().first()).
    if hasattr(session, "exec"):
        prior_result = await session.exec(prior_stmt)
        prior = prior_result.first()
    else:
        prior_result = await session.execute(prior_stmt)
        prior = prior_result.scalars().first()

    if prior is None:
        next_sequence = 0
        prev_hash: str | None = None
    else:
        next_sequence = prior.sequence + 1
        prev_hash = prior.current_hash

    envelope = event_service.build_envelope(
        run_id=run_id,
        sequence=next_sequence,
        event_type=event_type,
        payload=payload,
        step_id=step_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        span_id=span_id,
    )
    current_hash = event_service.compute_hash(prev_hash, envelope)

    event = WorkflowRunEvent(
        run_id=run_id,
        sequence=next_sequence,
        event_type=event_type,
        payload=payload,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        span_id=span_id,
        step_id=step_id,
        prev_hash=prev_hash,
        current_hash=current_hash,
    )
    session.add(event)
    await session.flush()


# ----------------------------------------------------------------------
# Public surface — dispatch_run
# ----------------------------------------------------------------------


async def dispatch_run(
    run_id: UUID,
    *,
    worker_id: str | None = None,
):
    """Public entry point used by REST routes and the worker drain.

    Returns the final ``WorkflowRun`` (refreshed) on success, or
    ``None`` when the run does not exist in ``workflow_runs`` or the
    claim was lost to another worker. Surfaces a clear log line on the
    ``ADR-006`` legacy-ID path so Conflict 9 cannot regress.
    """
    return await claim_and_dispatch(run_id, worker_id=worker_id)


async def claim_and_dispatch(
    run_id: UUID,
    worker_id: str | None = None,
):
    """Claim the run and execute it. Returns the final run state.

    Three-phase lifecycle:
      1. Look up the row — refuse with a loud log on legacy IDs.
      2. Short-circuit terminal/cancel-requested states without claim.
      3. Atomically claim, execute, persist, finalise.
    """
    from app.models.workflow import WorkflowRun  # local — avoids import cycle

    chosen_worker_id = worker_id or f"rest:{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as session:
        run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
        if run is None:
            # Conflict 9: a legacy ``Execution.id`` was passed in. The
            # prior implementation silently returned which masked the
            # underlying schema split. Make the failure observable.
            log.error(
                "dispatch_run: run %s not in workflow_runs (legacy "
                "Execution.id?) — refusing to dispatch",
                run_id,
            )
            return None

        if run.status in ("completed", "failed", "cancelled"):
            log.info(
                "dispatch_run: run %s already terminal status=%s — skipping",
                run_id,
                run.status,
            )
            return run

        # Honour cancellation requested before any execution work.
        if run.cancel_requested_at is not None and run.status in (
            "queued",
            "pending",
        ):
            run.status = "cancelled"
            run.completed_at = datetime.utcnow()
            session.add(run)
            await _async_append_event(
                session,
                run.id,
                "run.cancelled",
                payload={
                    "cancel_requested_at": run.cancel_requested_at.isoformat(),
                    "reason": "cancel_requested_before_claim",
                },
                tenant_id=run.tenant_id,
            )
            await session.commit()
            await session.refresh(run)
            # Phase 5: emit canonical run-terminal + cancellation metrics.
            _emit_run_terminal_metrics(run, duration_ms=run.duration_ms)
            try:
                _metrics.record_run_cancellation(
                    tenant_id=str(run.tenant_id) if run.tenant_id else "unknown",
                    reason="cancel_requested_before_claim",
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("cancel metric emit failed: %s", exc)
            return run

        if run.status not in ("pending", "queued"):
            # status='running' or other transient — another worker may
            # already own this run. We do not contend for it.
            log.info(
                "dispatch_run: run %s in non-claimable status=%s — skipping",
                run_id,
                run.status,
            )
            return run

    # Claim outside the inspection transaction so the UPDATE is atomic
    # and we don't hold a connection while doing engine work.
    async with async_session_factory() as session:
        # Phase 6: per-tenant + per-workflow concurrency quota gate.
        # When the tenant is at its cap we leave the run in queued
        # status so a later drain iteration can retry — this keeps
        # backpressure transparent and isolated per tenant.
        from app.services.quota_service import reserve_slot  # noqa: PLC0415

        try:
            allowed = await reserve_slot(
                session,
                tenant_id=run.tenant_id,
                workflow_id=run.workflow_id,
                run_id=run.id,
            )
        except Exception as exc:  # noqa: BLE001 — quota errors must not block
            log.debug("quota_reserve_check_failed: %s", exc)
            allowed = True

        if not allowed:
            log.info(
                "dispatch_run: quota_exceeded for run %s "
                "(tenant_id=%s, workflow_id=%s) — leaving queued",
                run_id,
                run.tenant_id,
                run.workflow_id,
            )
            try:
                _emit_quota_throttle(
                    tenant_id=str(run.tenant_id) if run.tenant_id else "unknown",
                    workflow_id=(
                        str(run.workflow_id) if run.workflow_id else "none"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("quota throttle metric emit failed: %s", exc)
            return None

        claimed = await claim_run(
            session,
            run_id=run_id,
            worker_id=chosen_worker_id,
        )
        if claimed is None:
            log.info(
                "dispatch_run: claim lost for run %s (worker_id=%s)",
                run_id,
                chosen_worker_id,
            )
            return None

        # Emit run.claimed + run.started in the same session as the claim
        # so the events live in the same chain as the post-execution
        # finaliser.
        await _async_append_event(
            session,
            claimed.id,
            "run.claimed",
            payload={
                "worker_id": chosen_worker_id,
                "attempt": claimed.attempt,
                "claimed_at": (
                    claimed.claimed_at.isoformat()
                    if claimed.claimed_at
                    else None
                ),
            },
            tenant_id=claimed.tenant_id,
        )
        await _async_append_event(
            session,
            claimed.id,
            "run.started",
            payload={
                "started_at": (
                    claimed.started_at.isoformat()
                    if claimed.started_at
                    else None
                ),
                "attempt": claimed.attempt,
            },
            tenant_id=claimed.tenant_id,
        )
        await session.commit()

        # Hand off to the executor with the same session for symmetry.
        await execute_claimed_run(session, claimed, worker_id=chosen_worker_id)
        await session.refresh(claimed)
        return claimed


# ----------------------------------------------------------------------
# Public surface — execute_claimed_run
# ----------------------------------------------------------------------


async def execute_claimed_run(
    session: AsyncSession,
    run,  # WorkflowRun (typed locally to dodge cycles)
    *,
    worker_id: str | None = None,
) -> None:
    """Run the engine, persist step results, finalise the run row.

    Caller has already claimed the run (status='running', lease set).
    On exit, the run is in a terminal status (completed / failed /
    cancelled / paused) with full event chain coverage.

    Integration responsibilities (W2.4):

      * Cancellation is honoured at three points: pre-flight (before
        engine), mid-flight (cancel_check between engine batches), and
        post-engine (re-check after engine returns).
      * Pending signals (cancel, approval, input) are consumed *before*
        invoking the engine so the dispatcher can short-circuit on a
        cancel that arrived while the run was paused.
      * On a step failure that maps to a retryable RetryPolicy, schedule
        a durable Timer for the backoff delay, emit ``step.retry``, flip
        the run to ``status='paused'``, and return — the worker's
        timer-fire loop will re-queue the run when the timer fires.
      * On engine ``status='paused'`` (e.g. human_approval, durable
        delay), persist step rows, emit ``run.paused``, and return.
    """
    from app.models.workflow import WorkflowRunStep  # local — avoids cycle

    chosen_worker_id = worker_id or run.lease_owner or "unknown"
    correlation_id = str(run.id)

    # W5.2 — distributed tracing: open the workflow.run span as the
    # outermost frame for the dispatch lifecycle. Step spans nest under
    # this one. No-op when tracing is disabled.
    async with _trace_span(
        "workflow.run",
        run_id=str(run.id),
        tenant_id=str(run.tenant_id) if run.tenant_id else None,
        kind=run.kind,
        attempt=run.attempt,
        worker_id=chosen_worker_id,
    ):
        await _execute_claimed_run_inner(
            session,
            run,
            worker_id=chosen_worker_id,
            correlation_id=correlation_id,
        )


async def _execute_claimed_run_inner(
    session: AsyncSession,
    run,
    *,
    worker_id: str,
    correlation_id: str,
) -> None:
    """Inner body of ``execute_claimed_run`` — extracted so the span
    context manager wraps the whole lifecycle without rewriting every
    early return."""
    from app.models.workflow import WorkflowRunStep  # local — avoids cycle

    chosen_worker_id = worker_id

    # ── Pre-flight: drain any cancel signal that may have arrived ──
    # (e.g. while the run was paused). Cancel signals override every
    # other transition.
    cancel_signals = await signal_service.consume_pending_signals(
        session,
        run_id=run.id,
        signal_types=["cancel"],
    )
    if cancel_signals:
        # A cancel signal was queued — treat as an explicit cancel
        # request even if cancel_requested_at is unset (legacy path).
        if run.cancel_requested_at is None:
            run.cancel_requested_at = datetime.utcnow()
            session.add(run)
        await session.commit()
        await _finalise_cancelled(session, run)
        return

    # Mid-flight cancellation: the cancel_requested_at field can be set
    # while the run is in status='running'. We re-check before invoking
    # the engine so cancels race in narrowly. The engine itself takes
    # ``cancel_check`` for finer-grained checks during step batches.
    await session.refresh(run)
    if run.cancel_requested_at is not None:
        await _finalise_cancelled(session, run)
        return

    # Build engine input strictly from the snapshot. ADR-001 forbids
    # reading the live workflows row.
    snapshot = run.definition_snapshot or {}
    snapshot_steps: list[dict[str, Any]] = list(snapshot.get("steps") or [])
    workflow_dict: dict[str, Any] = {
        "id": str(run.workflow_id) if run.workflow_id else snapshot.get("id"),
        "name": snapshot.get("name"),
        "steps": snapshot_steps,
        "graph_definition": snapshot.get("graph_definition"),
    }

    # ── WS9: production-mode stub-block gate ───────────────────────
    # Refuse to dispatch a run whose snapshot contains stub-classified
    # nodes when ARCHON_ENV is durable (production / staging). A stub
    # node returns success without doing the work — silently completing
    # such a run is a correctness violation. See node_executors/_stub_block.
    if await _gate_stub_blocked_steps(
        session, run, snapshot_steps, correlation_id=correlation_id
    ):
        return

    # Best-effort step-event callback. If the engine wires it up we
    # benefit from ordered streaming events; if it does not we still
    # persist all steps from result["steps"] below.
    async def _on_step_event(payload: dict[str, Any]) -> None:
        # Engine emits ``step_started``/``step_completed``/``step_failed``;
        # we currently rely on the post-execution iteration for
        # canonical persistence + ADR-002 events. The callback is
        # retained as a hook for future streaming use.
        return None

    def _is_cancelled() -> bool:
        # cancel_check is sync — read the in-memory flag set by the
        # latest refresh. Routes flip cancel_requested_at + commit;
        # we only see updates between batches (refresh below).
        return run.cancel_requested_at is not None

    start_ms = time.perf_counter()
    engine_result: dict[str, Any] | None = None
    error_text: str | None = None
    error_code: str | None = None
    failure_traceback: str | None = None

    try:
        engine_result = await execute_workflow_dag(
            workflow_dict,
            tenant_id=str(run.tenant_id) if run.tenant_id else None,
            on_step_event=_on_step_event,
            db_session=session,
            cancel_check=_is_cancelled,
        )
    except asyncio.CancelledError:
        log.warning("execute_claimed_run: run %s cancelled", run.id)
        await _finalise_cancelled(session, run)
        raise
    except Exception as exc:  # noqa: BLE001 — we deliberately catch all
        error_text = f"{type(exc).__name__}: {exc}"[:500]
        error_code = type(exc).__name__
        failure_traceback = traceback.format_exc()[:4000]
        log.exception("execute_claimed_run: run %s failed", run.id)

    duration_ms = max(0, int((time.perf_counter() - start_ms) * 1000))

    # If cancellation flipped during execution, finalise as cancelled
    # regardless of engine result. This re-check honours cancels that
    # arrived after the engine returned but before we finalised.
    await session.refresh(run)
    if run.cancel_requested_at is not None and run.status not in (
        "completed",
        "failed",
    ):
        await _finalise_cancelled(session, run, duration_ms=duration_ms)
        return

    if engine_result is None:
        # Hard failure path — nothing returned from the engine.
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        run.duration_ms = duration_ms
        run.error_code = error_code or "engine_unhandled_exception"
        run.error = error_text or "engine raised an unhandled exception"
        session.add(run)
        await _async_append_event(
            session,
            run.id,
            "run.failed",
            payload={
                "duration_ms": duration_ms,
                "error": run.error,
                "error_code": run.error_code,
                "traceback": failure_traceback or "",
            },
            tenant_id=run.tenant_id,
            correlation_id=correlation_id,
        )
        await session.commit()
        # Phase 5: emit canonical run-terminal metrics.
        _emit_run_terminal_metrics(run, duration_ms=duration_ms)
        return

    # ── Persist step rows + step-level events from engine output ────
    steps_payload: list[dict[str, Any]] = list(engine_result.get("steps") or [])
    aggregate_token_usage: dict[str, int] = {}
    aggregate_cost: float = 0.0

    # Pre-build a lookup from step_id → snapshot config so we can find
    # the RetryPolicy declared for each failing step.
    snapshot_by_step: dict[str, dict[str, Any]] = {}
    for snap_step in snapshot_steps:
        sid = str(snap_step.get("step_id") or snap_step.get("name") or "")
        if sid:
            snapshot_by_step[sid] = snap_step

    # Track first failed step so we can decide if a retry should fire.
    first_failed_payload: dict[str, Any] | None = None

    for step_payload in steps_payload:
        step_id_raw = step_payload.get("step_id") or ""
        step_status = step_payload.get("status") or "completed"
        started_at_raw = step_payload.get("started_at")
        completed_at_raw = step_payload.get("completed_at")
        token_usage = step_payload.get("token_usage") or {}
        cost_usd = step_payload.get("cost_usd")

        # W5.2 — workflow.step span nests under the workflow.run span.
        # Recorded before the row insert so failure paths still emit
        # a span for ops triage.
        async with _trace_span(
            "workflow.step",
            run_id=str(run.id),
            tenant_id=str(run.tenant_id) if run.tenant_id else None,
            step_id=str(step_id_raw),
            node_type=step_payload.get("node_type") or step_payload.get("type"),
            status=step_status,
            worker_id=chosen_worker_id,
        ):
            pass  # span body is empty — execution already happened upstream

        # Aggregate cost / tokens for the run-level metrics field.
        if isinstance(token_usage, dict):
            for key, value in token_usage.items():
                if isinstance(value, (int, float)):
                    aggregate_token_usage[key] = (
                        aggregate_token_usage.get(key, 0) + int(value)
                    )
        if isinstance(cost_usd, (int, float)):
            aggregate_cost += float(cost_usd)

        # W5.3 — extract large outputs into the artifact substrate.
        # The helper is a no-op below the threshold, so the small-output
        # path stays fast. The helper imports the artifact service lazily
        # and tolerates a missing artifacts table (legacy schemas) by
        # returning the original output unchanged.
        persisted_output = await _maybe_extract_step_output_as_artifact(
            session,
            tenant_id=run.tenant_id,
            run_id=run.id,
            step_id=str(step_id_raw),
            output_data=step_payload.get("output_data"),
        )

        step_row = WorkflowRunStep(
            run_id=run.id,
            step_id=str(step_id_raw),
            name=step_payload.get("name") or str(step_id_raw),
            status=step_status,
            started_at=_parse_iso(started_at_raw),
            completed_at=_parse_iso(completed_at_raw),
            duration_ms=int(step_payload.get("duration_ms") or 0),
            input_data=_safe_dict(step_payload.get("input_data")),
            output_data=persisted_output,
            error=step_payload.get("error"),
            attempt=run.attempt,
            token_usage=_safe_dict(token_usage),
            cost_usd=float(cost_usd) if isinstance(cost_usd, (int, float)) else None,
            worker_id=chosen_worker_id,
            error_code=(
                step_payload.get("error_code")
                or (
                    type(step_payload.get("error")).__name__
                    if step_payload.get("error")
                    and step_status == "failed"
                    else None
                )
            ),
        )
        session.add(step_row)
        await session.flush()

        # ADR-002 step.* event — emitted in the same transaction as the
        # step row so a chain consumer never sees the row without the
        # corresponding event.
        step_event_type = _step_status_to_event(step_status)
        await _async_append_event(
            session,
            run.id,
            step_event_type,
            payload={
                "step_id": str(step_id_raw),
                "name": step_payload.get("name"),
                "status": step_status,
                "duration_ms": int(step_payload.get("duration_ms") or 0),
                "output_data": step_payload.get("output_data"),
                "error": step_payload.get("error"),
            },
            tenant_id=run.tenant_id,
            step_id=str(step_id_raw),
            correlation_id=correlation_id,
        )

        if step_status == "failed" and first_failed_payload is None:
            first_failed_payload = step_payload

        # Phase 5: emit per-step metrics (duration histogram + retry counter).
        _emit_step_metrics(run, step_payload)

    # ── Retry decision ─────────────────────────────────────────────
    # If a step failed and its RetryPolicy says we should retry, schedule
    # a Timer with the computed backoff delay, emit step.retry, flip the
    # run to paused, and return early. The worker's timer-fire loop will
    # re-queue the run when the timer fires.
    final_status = engine_result.get("status") or "completed"
    if final_status == "failed" and first_failed_payload is not None:
        retried = await _maybe_schedule_retry(
            session,
            run=run,
            failed_step_payload=first_failed_payload,
            snapshot_by_step=snapshot_by_step,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )
        if retried:
            # _maybe_schedule_retry committed the row+event already.
            return

    # ── Finalise the run row ────────────────────────────────────────
    run.status = final_status
    run.completed_at = datetime.utcnow() if final_status != "paused" else None
    run.duration_ms = duration_ms
    run.output_data = engine_result.get("output") or _aggregate_outputs(
        steps_payload
    )
    run.metrics = {
        "duration_ms": duration_ms,
        "step_count": len(steps_payload),
        "cost_usd": aggregate_cost,
        "token_usage": aggregate_token_usage,
    }

    if final_status == "paused":
        # Pause stamps paused_at instead of completed_at — the worker
        # picks this back up when a signal flips status back to queued.
        if run.paused_at is None:
            run.paused_at = datetime.utcnow()

    session.add(run)

    if final_status == "failed":
        # Surface the first failed step's error on the run row so REST
        # consumers see a meaningful error string without joining steps.
        if not run.error:
            run.error = _first_step_error(steps_payload)
        if not run.error_code and first_failed_payload is not None:
            run.error_code = (
                first_failed_payload.get("error_code")
                or "step_failed"
            )
        session.add(run)
        await _async_append_event(
            session,
            run.id,
            "run.failed",
            payload={
                "duration_ms": duration_ms,
                "error": run.error or _first_step_error(steps_payload),
                "metrics": run.metrics,
            },
            tenant_id=run.tenant_id,
            correlation_id=correlation_id,
        )
    elif final_status == "cancelled":
        await _async_append_event(
            session,
            run.id,
            "run.cancelled",
            payload={
                "duration_ms": duration_ms,
                "metrics": run.metrics,
            },
            tenant_id=run.tenant_id,
            correlation_id=correlation_id,
        )
    elif final_status == "paused":
        # Note: human_approval and other paused-state node executors
        # already emit run.paused via approval_service. We only emit
        # here when the engine reports paused without a prior emission
        # (e.g. delayNode short-circuited to paused without a per-run
        # paused event). The duplicate is harmless but waste — guard
        # against it by checking the most recent event type.
        emitted = await _has_recent_paused_event(session, run.id)
        if not emitted:
            await _async_append_event(
                session,
                run.id,
                "run.paused",
                payload={
                    "duration_ms": duration_ms,
                    "metrics": run.metrics,
                    "reason": _first_paused_reason(steps_payload)
                    or "engine_paused",
                },
                tenant_id=run.tenant_id,
                correlation_id=correlation_id,
            )
    else:  # completed
        await _async_append_event(
            session,
            run.id,
            "run.completed",
            payload={
                "duration_ms": duration_ms,
                "metrics": run.metrics,
            },
            tenant_id=run.tenant_id,
            correlation_id=correlation_id,
        )

    await session.commit()

    # Phase 5: emit canonical run-terminal metrics for completed/failed/
    # paused/cancelled finalisations. The status label distinguishes them.
    _emit_run_terminal_metrics(run, duration_ms=duration_ms)


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


async def _finalise_cancelled(
    session: AsyncSession,
    run,
    *,
    duration_ms: int | None = None,
) -> None:
    """Mark a run cancelled and emit ``run.cancelled``."""
    run.status = "cancelled"
    run.completed_at = datetime.utcnow()
    if duration_ms is not None:
        run.duration_ms = duration_ms
    session.add(run)
    await _async_append_event(
        session,
        run.id,
        "run.cancelled",
        payload={
            "cancel_requested_at": (
                run.cancel_requested_at.isoformat()
                if run.cancel_requested_at
                else None
            ),
            "duration_ms": duration_ms,
        },
        tenant_id=run.tenant_id,
    )
    await session.commit()
    # Phase 5: emit canonical run-terminal + cancellation metrics.
    _emit_run_terminal_metrics(run, duration_ms=duration_ms)


# ----------------------------------------------------------------------
# Retry orchestration
# ----------------------------------------------------------------------


async def _maybe_schedule_retry(
    session: AsyncSession,
    *,
    run,
    failed_step_payload: dict[str, Any],
    snapshot_by_step: dict[str, dict[str, Any]],
    duration_ms: int,
    correlation_id: str,
) -> bool:
    """If the failed step has a retry budget remaining, schedule a Timer.

    Returns ``True`` when a retry was scheduled (caller must NOT finalise
    the run as failed); ``False`` when no retry was scheduled (run should
    finalise as failed normally).

    Decision flow:
      1. Look up the snapshot config for the failed step.
      2. Build a RetryPolicy from the config.
      3. Reconstruct a stand-in exception so should_retry() can apply
         retry_on / no_retry_on rules. The error_code from the engine
         carries the class name; we synthesise a class with that name so
         classification is exact.
      4. If should_retry — schedule a Timer (purpose=retry_attempt) for
         the computed backoff, emit step.retry, flip run to paused.
      5. If not — return False so the caller emits run.failed.
    """
    step_id_raw = str(failed_step_payload.get("step_id") or "")
    snapshot_step = snapshot_by_step.get(step_id_raw, {})
    policy = RetryPolicy.from_step_config(snapshot_step)

    # Default attempt counter: run.attempt starts at 1 after the claim,
    # so the *current* step attempt is run.attempt. Next attempt = +1.
    current_attempt = max(int(run.attempt or 1), 1)
    next_attempt = current_attempt + 1

    # Build a synthetic exception whose class name matches the recorded
    # error_code so RetryPolicy.should_retry's MRO check picks the right
    # bucket. The error_code is best-effort from the engine.
    error_class_name = (
        failed_step_payload.get("error_code")
        or _extract_error_class(failed_step_payload.get("error"))
        or "Exception"
    )

    synthetic_exc = _synthesise_exception(error_class_name)
    if not policy.should_retry(synthetic_exc, current_attempt):
        return False

    delay_seconds = policy.compute_delay(next_attempt)
    fire_at = datetime.utcnow() + timedelta(seconds=delay_seconds)

    timer = await timer_service.schedule_timer(
        session,
        run_id=run.id,
        step_id=step_id_raw,
        fire_at=fire_at,
        purpose="retry_attempt",
        payload={
            "step_id": step_id_raw,
            "attempt": next_attempt,
            "delay_seconds": delay_seconds,
            "error_class": error_class_name,
        },
    )

    # Emit step.retry to record the decision in the chain.
    await _async_append_event(
        session,
        run.id,
        "step.retry",
        payload={
            "step_id": step_id_raw,
            "attempt": next_attempt,
            "delay_seconds": delay_seconds,
            "fire_at": fire_at.isoformat(),
            "timer_id": str(timer.id),
            "error": failed_step_payload.get("error"),
            "error_code": error_class_name,
        },
        tenant_id=run.tenant_id,
        step_id=step_id_raw,
        correlation_id=correlation_id,
    )

    # Flip the run to paused. The worker's timer-fire loop will flip it
    # back to queued when the timer fires.
    run.status = "paused"
    run.paused_at = datetime.utcnow()
    run.duration_ms = duration_ms
    session.add(run)

    await _async_append_event(
        session,
        run.id,
        "run.paused",
        payload={
            "reason": "retry_pending",
            "step_id": step_id_raw,
            "attempt": next_attempt,
            "fire_at": fire_at.isoformat(),
            "timer_id": str(timer.id),
        },
        tenant_id=run.tenant_id,
        step_id=step_id_raw,
        correlation_id=correlation_id,
    )

    await session.commit()
    # Phase 5: emit step retry counter. node_type may not be on the
    # synthetic payload; fall back to the snapshot config.
    _node_type = (
        failed_step_payload.get("node_type")
        or snapshot_step.get("node_type")
        or snapshot_step.get("type")
        or "unknown"
    )
    _emit_step_retry(run, node_type=str(_node_type))
    return True


def _synthesise_exception(class_name: str) -> Exception:
    """Build an exception whose ``__class__.__name__`` equals class_name.

    RetryPolicy.should_retry classifies by class name, walking the MRO.
    A synthetic class created here will appear in the MRO with the
    requested name plus ``Exception`` (its base) — sufficient for the
    name-based classification.
    """
    cls = type(class_name, (Exception,), {})
    return cls(f"synthetic {class_name}")


def _extract_error_class(error_text: Any) -> str | None:
    """Best-effort: pull the class name prefix out of ``ClassName: msg``."""
    if not isinstance(error_text, str):
        return None
    head, sep, _ = error_text.partition(":")
    if sep and head and head.replace("_", "").isalnum():
        return head.strip()
    return None


async def _has_recent_paused_event(session: AsyncSession, run_id: UUID) -> bool:
    """Return True when the most recent run-level event is run.paused."""
    from app.models.workflow import WorkflowRunEvent  # local — avoid cycles

    stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence.desc())
        .limit(1)
    )
    if hasattr(session, "exec"):
        result = await session.exec(stmt)
        latest = result.first()
    else:
        result = await session.execute(stmt)
        latest = result.scalars().first()
    return latest is not None and latest.event_type == "run.paused"


def _first_paused_reason(steps: list[dict[str, Any]]) -> str | None:
    """Return the first step's paused_reason (if any)."""
    for step in steps:
        if step.get("status") == "paused":
            return step.get("paused_reason")
    return None


# ----------------------------------------------------------------------
# Signal-driven resume
# ----------------------------------------------------------------------


async def resume_run_from_signal(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> bool:
    """Flip a paused run back to ``queued`` so the drain loop picks it up.

    Called by route handlers (approval grant/reject, cancel) after a
    signal has been written. Honours ``cancel_requested_at`` — if a
    cancel was injected on a paused run, we finalise as cancelled here
    and return False.

    Returns:
        True   — the run is now ``queued`` and will be picked up.
        False  — the run could not be resumed (terminal, cancelled, or
                 not in paused state). Caller treats False as a no-op.
    """
    from app.models.workflow import WorkflowRun  # local — avoid cycles

    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        return False

    # If the run was cancelled while paused, finalise as cancelled.
    if run.cancel_requested_at is not None and run.status not in (
        "completed",
        "failed",
        "cancelled",
    ):
        await _finalise_cancelled(session, run)
        return False

    if run.status != "paused":
        return False

    # Flip back to queued. Clear the lease so the drain loop's claim
    # call wins immediately. Stamp resumed_at for observability.
    run.status = "queued"
    run.resumed_at = datetime.utcnow()
    run.lease_owner = None
    run.lease_expires_at = None
    session.add(run)

    await _async_append_event(
        session,
        run.id,
        "run.resumed",
        payload={
            "resumed_at": run.resumed_at.isoformat() if run.resumed_at else None,
            "reason": "signal_consumed",
        },
        tenant_id=run.tenant_id,
    )

    await session.commit()
    return True


def _step_status_to_event(status: str) -> str:
    mapping = {
        "completed": "step.completed",
        "failed": "step.failed",
        "skipped": "step.skipped",
        "paused": "step.paused",
        "retry": "step.retry",
    }
    return mapping.get(status, "step.completed")


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        # Python's fromisoformat handles "+00:00"; if string ends with
        # "Z" we normalise it because fromisoformat <3.11 doesn't.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        # SQLModel stores naive UTC in our schema; strip tzinfo so the
        # column comparison stays homogeneous.
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _aggregate_outputs(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a minimal output projection if the engine didn't supply one.

    The result is a thin per-step output map keyed by step_id. UI
    consumers that want richer projections should read ``workflow_run_steps``
    directly — this is just a sensible default.
    """
    out: dict[str, Any] = {}
    for step in steps:
        sid = step.get("step_id")
        if not sid:
            continue
        out[str(sid)] = {
            "status": step.get("status"),
            "output": step.get("output_data"),
        }
    return out


def _first_step_error(steps: list[dict[str, Any]]) -> str | None:
    for step in steps:
        if step.get("status") == "failed" and step.get("error"):
            return str(step["error"])[:500]
    return None


# ----------------------------------------------------------------------
# WS9: production-mode stub-block gate
# ----------------------------------------------------------------------


async def _gate_stub_blocked_steps(
    session: AsyncSession,
    run,  # WorkflowRun
    snapshot_steps: list[dict[str, Any]],
    *,
    correlation_id: str,
) -> bool:
    """Block dispatch when the snapshot contains stub-classified nodes.

    Returns ``True`` when the run was finalised as failed (caller must
    return without invoking the engine); ``False`` when no stub-blocked
    steps were found and dispatch may proceed.

    For each blocked step we emit ``step.failed`` with
    ``error_code='stub_blocked_in_production'`` and persist a
    ``WorkflowRunStep`` row. We then finalise the run as ``status='failed'``
    with ``error_code='stub_blocked'`` and emit ``run.failed`` — matching
    the contract the rest of the dispatcher follows for engine-detected
    failures.
    """
    from app.models.workflow import WorkflowRunStep  # local — avoid cycles
    from app.services.node_executors import (  # noqa: PLC0415
        StubBlockError,
        assert_node_runnable,
    )

    blocked: list[tuple[dict[str, Any], StubBlockError]] = []
    for step in snapshot_steps:
        node_type = step.get("node_type") or step.get("type")
        if not node_type:
            # Legacy agent-only steps have no node_type — handled by the
            # engine's fallback path. Nothing to gate here.
            continue
        try:
            assert_node_runnable(node_type)
        except StubBlockError as exc:
            blocked.append((step, exc))

    if not blocked:
        return False

    now = datetime.utcnow()
    for step_payload, exc in blocked:
        step_id_raw = str(
            step_payload.get("step_id") or step_payload.get("name") or ""
        )
        step_row = WorkflowRunStep(
            run_id=run.id,
            step_id=step_id_raw,
            name=step_payload.get("name") or step_id_raw,
            status="failed",
            started_at=now,
            completed_at=now,
            duration_ms=0,
            input_data={},
            output_data=None,
            error=str(exc),
            attempt=run.attempt,
            error_code="stub_blocked_in_production",
            worker_id=run.lease_owner or "stub-block",
        )
        session.add(step_row)
        await session.flush()

        await _async_append_event(
            session,
            run.id,
            "step.failed",
            payload={
                "step_id": step_id_raw,
                "name": step_payload.get("name"),
                "status": "failed",
                "node_type": exc.node_type,
                "node_status": exc.status.value,
                "archon_env": exc.env,
                "error": str(exc),
                "error_code": "stub_blocked_in_production",
            },
            tenant_id=run.tenant_id,
            step_id=step_id_raw,
            correlation_id=correlation_id,
        )

    # Finalise the run as failed. Use the first blocked step for the
    # run-level error string so REST consumers see a meaningful reason.
    first_step, first_exc = blocked[0]
    run.status = "failed"
    run.completed_at = now
    run.duration_ms = 0
    run.error_code = "stub_blocked"
    run.error = str(first_exc)[:500]
    session.add(run)

    await _async_append_event(
        session,
        run.id,
        "run.failed",
        payload={
            "duration_ms": 0,
            "error": run.error,
            "error_code": "stub_blocked",
            "blocked_steps": [
                {
                    "step_id": str(s.get("step_id") or s.get("name") or ""),
                    "node_type": e.node_type,
                    "node_status": e.status.value,
                }
                for s, e in blocked
            ],
            "archon_env": first_exc.env,
        },
        tenant_id=run.tenant_id,
        correlation_id=correlation_id,
    )

    await session.commit()
    # Phase 5: emit canonical run-terminal metrics for the stub-blocked
    # failure finalisation.
    _emit_run_terminal_metrics(run, duration_ms=0)
    return True


__all__ = [
    "claim_and_dispatch",
    "dispatch_run",
    "execute_claimed_run",
    "resume_run_from_signal",
]
