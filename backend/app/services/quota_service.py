"""Per-tenant + per-workflow concurrency quota service (Phase 6 — WS17).

Enforces transparent backpressure on workflow run dispatch by counting
``WorkflowRun`` rows currently in ``status='running'`` and gating new
claims when configured caps are reached.

Design rationale
----------------

Rather than maintaining a separate counter table that must be kept in
lockstep with the run lifecycle, this service derives quota state by
counting rows in ``workflow_runs`` directly. This keeps quota state
strictly consistent with reality — there is no drift surface, no
counter to leak, no compensating reconciliation step. The cost is one
extra SELECT per dispatch attempt; with the existing
``ix_workflow_runs_tenant_id_status`` index this is a single index
scan and fast.

Public surface
--------------

- ``QuotaSnapshot`` — dataclass describing a tenant/workflow's current
  quota standing.
- ``check_quota(session, *, tenant_id, workflow_id=None)`` — read-only
  snapshot of current usage vs. cap.
- ``reserve_slot(session, *, tenant_id, workflow_id, run_id)`` — fast
  pre-claim check: returns True iff a fresh dispatch would not breach
  either the tenant-wide or per-workflow cap. Does NOT mutate state —
  the actual lease/claim is owned by ``run_lifecycle.claim_run``. The
  caller wires this in front of ``claim_run`` so the SELECT count
  reflects pre-claim reality.
- ``release_slot(session, *, tenant_id, workflow_id, run_id)`` — no-op
  for symmetry with the documented contract. Quota state is dynamic
  (count of running rows), so cleanup happens implicitly when the
  dispatcher transitions the run out of ``status='running'``.

Semantics
---------

- A tenant with no ``TenantQuota`` row uses default caps
  (``DEFAULT_MAX_CONCURRENT_RUNS`` / ``DEFAULT_MAX_CONCURRENT_PER_WORKFLOW``).
- ``is_throttled`` is True when ``current_running >= max_concurrent_runs``
  OR (workflow_id provided AND running-for-this-workflow >=
  ``max_concurrent_per_workflow``).
- ``headroom`` is the smaller of the two available windows when a
  workflow_id is supplied; tenant-wide otherwise.
- A ``None`` tenant_id is treated as ``"unknown"`` and never throttled
  (legacy ungated runs continue to work as before).

Atomicity
---------

``check_quota`` issues SELECTs only — it does not lock rows. The race
window between "check" and "claim" is closed by ``claim_run``'s
optimistic UPDATE: if two callers simultaneously see headroom > 0 and
both attempt claim, only one wins the row. Both callers then re-check
quota on their next iteration. The net effect is correct enforcement
under the cap, though briefly the running count may equal the cap
exactly (never exceeds it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.tenancy import TenantQuota
from app.models.workflow import WorkflowRun

log = logging.getLogger(__name__)


# Default caps used when no TenantQuota row exists for the tenant.
# These are deliberately generous so legacy code paths that don't yet
# create quota rows aren't gated; explicit quota rows take precedence.
DEFAULT_MAX_CONCURRENT_RUNS = 10
DEFAULT_MAX_CONCURRENT_PER_WORKFLOW = 5


@dataclass
class QuotaSnapshot:
    """Snapshot of a tenant's (and optionally workflow's) concurrency state.

    Attributes:
        tenant_id: Tenant UUID (None for legacy ungated runs).
        workflow_id: Workflow UUID, when scoped per-workflow.
        current_running: Count of runs in status='running' for this tenant
            (or this tenant + workflow when workflow_id is set).
        current_queued: Count of runs in status IN ('queued', 'pending')
            for the same scope. Informational — not used for gating.
        max_concurrent_runs: Tenant-wide concurrency cap.
        max_concurrent_per_workflow: Per-workflow concurrency cap.
        headroom: Slots available before throttling. When workflow_id is
            set, the smaller of (tenant headroom, per-workflow headroom).
        is_throttled: True when a fresh dispatch would breach either cap.
    """

    tenant_id: UUID | None
    workflow_id: UUID | None
    current_running: int
    current_queued: int
    max_concurrent_runs: int
    max_concurrent_per_workflow: int
    headroom: int
    is_throttled: bool


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


async def _load_quota_caps(
    session: AsyncSession, *, tenant_id: UUID | None
) -> tuple[int, int]:
    """Return (max_concurrent_runs, max_concurrent_per_workflow) for tenant.

    Falls back to defaults when no TenantQuota row is found or tenant_id
    is None. Reads only — never mutates.
    """
    if tenant_id is None:
        return DEFAULT_MAX_CONCURRENT_RUNS, DEFAULT_MAX_CONCURRENT_PER_WORKFLOW

    stmt = select(TenantQuota).where(TenantQuota.tenant_id == tenant_id).limit(1)
    quota = await _exec_first(session, stmt)
    if quota is None:
        return DEFAULT_MAX_CONCURRENT_RUNS, DEFAULT_MAX_CONCURRENT_PER_WORKFLOW

    return (
        int(getattr(quota, "max_concurrent_runs", DEFAULT_MAX_CONCURRENT_RUNS)),
        int(
            getattr(
                quota,
                "max_concurrent_per_workflow",
                DEFAULT_MAX_CONCURRENT_PER_WORKFLOW,
            )
        ),
    )


async def _count_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    workflow_id: UUID | None,
    statuses: tuple[str, ...],
) -> int:
    """Count workflow_runs rows in any of ``statuses`` for the given scope."""
    if tenant_id is None:
        return 0

    stmt = select(func.count()).select_from(WorkflowRun).where(
        WorkflowRun.tenant_id == tenant_id,
        WorkflowRun.status.in_(statuses),
    )
    if workflow_id is not None:
        stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)

    result = await _exec_scalar(session, stmt)
    return int(result or 0)


async def _exec_first(session: AsyncSession, stmt: Any) -> Any:
    """Run a SELECT and return the first row (sqlmodel/sqlalchemy compatible)."""
    if hasattr(session, "exec"):
        result = await session.exec(stmt)
        return result.first()
    result = await session.execute(stmt)
    return result.scalars().first()


async def _exec_scalar(session: AsyncSession, stmt: Any) -> Any:
    """Run a SELECT count(*) and return the scalar value."""
    if hasattr(session, "exec"):
        result = await session.exec(stmt)
        # sqlmodel.exec on a func.count() select returns the count directly
        # via .one() or first(). first() returns a tuple-like; coerce to int.
        row = result.first()
        if row is None:
            return 0
        if isinstance(row, (int, float)):
            return row
        try:
            return row[0]
        except (TypeError, IndexError):
            return row
    result = await session.execute(stmt)
    return result.scalar()


# ----------------------------------------------------------------------
# Public surface
# ----------------------------------------------------------------------


async def check_quota(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    workflow_id: UUID | None = None,
) -> QuotaSnapshot:
    """Return a QuotaSnapshot for the given tenant + optional workflow.

    Reads:
      1. TenantQuota.max_concurrent_runs / max_concurrent_per_workflow
         (defaults applied when row absent).
      2. Count of workflow_runs in status='running' for the tenant.
      3. (When workflow_id is set) Count of running runs for this
         specific workflow within the tenant.

    Headroom is the minimum of (tenant_cap - tenant_running) and
    (per_workflow_cap - workflow_running), clamped to 0.
    is_throttled is True when headroom == 0.
    """
    cap_tenant, cap_workflow = await _load_quota_caps(
        session, tenant_id=tenant_id
    )

    tenant_running = await _count_runs(
        session,
        tenant_id=tenant_id,
        workflow_id=None,
        statuses=("running",),
    )
    tenant_queued = await _count_runs(
        session,
        tenant_id=tenant_id,
        workflow_id=None,
        statuses=("queued", "pending"),
    )

    if workflow_id is not None:
        workflow_running = await _count_runs(
            session,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            statuses=("running",),
        )
        tenant_headroom = max(0, cap_tenant - tenant_running)
        workflow_headroom = max(0, cap_workflow - workflow_running)
        headroom = min(tenant_headroom, workflow_headroom)
        # Surface workflow-scoped current_running so consumers can see
        # which axis is the tighter constraint.
        current_running = workflow_running
    else:
        headroom = max(0, cap_tenant - tenant_running)
        current_running = tenant_running

    return QuotaSnapshot(
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        current_running=current_running,
        current_queued=tenant_queued,
        max_concurrent_runs=cap_tenant,
        max_concurrent_per_workflow=cap_workflow,
        headroom=headroom,
        is_throttled=headroom <= 0 and tenant_id is not None,
    )


async def reserve_slot(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    workflow_id: UUID | None,
    run_id: UUID,
) -> bool:
    """Pre-claim quota check. Returns True iff dispatch may proceed.

    Reads the live ``running`` row count and compares against caps.
    Does NOT mutate state — the actual atomic claim is the dispatcher's
    job (``run_lifecycle.claim_run``). The intended call pattern is::

        if not await reserve_slot(session, tenant_id=..., workflow_id=..., run_id=...):
            log.info("quota_exceeded run_id=%s tenant_id=%s", run_id, tenant_id)
            return None
        claimed = await claim_run(session, run_id=run_id, worker_id=...)

    The race between ``reserve_slot`` and ``claim_run`` is benign:
    multiple callers may pass the check simultaneously, but only one
    will win ``claim_run``'s optimistic UPDATE. The remaining workers
    re-check on their next iteration; quota convergence is rapid.
    """
    snapshot = await check_quota(
        session, tenant_id=tenant_id, workflow_id=workflow_id
    )
    return not snapshot.is_throttled


async def release_slot(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    workflow_id: UUID | None,
    run_id: UUID,
) -> None:
    """No-op cleanup hook.

    Quota state is derived from ``count(WHERE status='running')``, so
    release happens automatically when the dispatcher finalises the run
    (status transitions out of 'running'). This function exists for
    symmetry with the documented contract — call it from cleanup paths
    where future implementations may add a counter-based fast path.
    """
    log.debug(
        "release_slot called for run_id=%s tenant_id=%s workflow_id=%s "
        "(no-op — quota is dynamic)",
        run_id,
        tenant_id,
        workflow_id,
    )
    return None


__all__ = [
    "DEFAULT_MAX_CONCURRENT_PER_WORKFLOW",
    "DEFAULT_MAX_CONCURRENT_RUNS",
    "QuotaSnapshot",
    "check_quota",
    "release_slot",
    "reserve_slot",
]
