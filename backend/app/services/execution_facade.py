"""Canonical execution facade — the single entry point for run creation.

Implements the contracts of:
  - ADR-001 (unified WorkflowRun model, XOR target, definition_snapshot)
  - ADR-002 (hash-chained run.created and run.queued events)
  - ADR-004 (idempotency contract via IdempotencyService)
  - ADR-006 (legacy Execution read-fallback, projection to legacy shape)

Public surface:
  - ExecutionFacade.create_run(...)            — write path (workflow OR agent)
  - ExecutionFacade.get(...)                   — read path (workflow_runs first,
                                                  fallback to legacy executions)
  - ExecutionFacade.project_to_legacy_execution_shape(run)
                                                — JSON-shape projection for
                                                  backward compatibility

The facade owns the transactional boundary for ``create_run``: a successful
return guarantees a durable WorkflowRun row plus the run.created and
run.queued events all committed in a single transaction.

Cross-references:
  - docs/adr/orchestration/ADR-001-agent-vs-workflow-execution.md
  - docs/adr/orchestration/ADR-002-...                (event chain shape)
  - docs/adr/orchestration/ADR-004-idempotency-contract.md
  - docs/adr/orchestration/ADR-006-execution-migration.md
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Union
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Agent, Execution
from app.models.workflow import (
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStep,
)
from app.services import event_service, idempotency_service
from app.services.idempotency_service import IdempotencyConflict

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


def _capture_workflow_snapshot(workflow: Workflow) -> dict[str, Any]:
    """Build the immutable definition_snapshot for a workflow run.

    Per ADR-001 §Snapshot shape — engine-agnostic JSON object.
    """
    return {
        "kind": "workflow",
        "id": str(workflow.id),
        "name": workflow.name,
        "version": None,
        "steps": list(workflow.steps or []),
        "graph_definition": workflow.graph_definition,
        "captured_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _capture_agent_snapshot(agent: Agent) -> dict[str, Any]:
    """Build the immutable definition_snapshot for an agent run."""
    return {
        "kind": "agent",
        "id": str(agent.id),
        "name": agent.name,
        "version": None,
        "steps": list(agent.steps or []) if agent.steps else [],
        "graph_definition": agent.graph_definition,
        "definition": agent.definition,
        "llm_config": agent.llm_config,
        "tools": list(agent.tools or []) if agent.tools else [],
        "captured_at": datetime.now(tz=timezone.utc).isoformat(),
    }


# ── Async event chain helpers ─────────────────────────────────────────
#
# event_service.append_event is synchronous. The route layer uses
# AsyncSession, so we replicate the chain logic asynchronously here. The
# building blocks (build_envelope, compute_hash, EVENT_TYPES) are reused
# unchanged so the chain remains identical regardless of the caller's
# session flavour.


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
) -> WorkflowRunEvent:
    """Async equivalent of event_service.append_event for AsyncSession."""
    if event_type not in event_service.EVENT_TYPES:
        raise ValueError(
            f"unknown event_type {event_type!r}; must be one of EVENT_TYPES"
        )

    # Read the prior event (highest sequence) for this run.
    prior_stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence.desc())
        .limit(1)
    )
    prior_result = await session.exec(prior_stmt)
    prior = prior_result.first()

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
    return event


# ── Facade ─────────────────────────────────────────────────────────────


class ExecutionFacade:
    """Canonical execution lifecycle facade.

    Creates a WorkflowRun for both workflow- and agent-driven runs;
    projects to the legacy Execution shape for backward compatibility.
    """

    @staticmethod
    async def create_run(
        session: AsyncSession,
        *,
        kind: str,
        workflow_id: UUID | None = None,
        agent_id: UUID | None = None,
        tenant_id: UUID | None = None,
        input_data: dict[str, Any] | None = None,
        triggered_by: str = "",
        trigger_type: str = "manual",
        idempotency_key: str | None = None,
    ) -> tuple[WorkflowRun, bool]:
        """Create a durable WorkflowRun and emit hash-chained lifecycle events.

        Returns:
            (run, is_new) — is_new=False when an idempotency hit returned
            an existing run.

        Raises:
            ValueError                 — invalid (kind, workflow_id, agent_id)
                                         combination, or referenced row missing.
            IdempotencyConflict        — same key + different input.

        Per ADR-001 the row carries:
            kind, workflow_id XOR agent_id, definition_snapshot (immutable),
            tenant_id, status="queued", queued_at=now, triggered_by,
            trigger_type, input_data.

        Per ADR-002 two events are appended in the same transaction:
            run.created  → sequence 0
            run.queued   → sequence 1
        """
        # ── 1. Validate XOR target ──────────────────────────────────────
        if kind not in ("workflow", "agent"):
            raise ValueError(
                f"kind must be 'workflow' or 'agent', got {kind!r}"
            )
        has_workflow = workflow_id is not None
        has_agent = agent_id is not None
        if has_workflow == has_agent:
            raise ValueError(
                "exactly one of workflow_id or agent_id must be provided"
            )
        if kind == "workflow" and not has_workflow:
            raise ValueError("kind='workflow' requires workflow_id")
        if kind == "agent" and not has_agent:
            raise ValueError("kind='agent' requires agent_id")

        input_payload: dict[str, Any] = dict(input_data or {})

        # ── 2. Compute the input_hash (always — see ADR-004 'Neutral'). ─
        input_hash = idempotency_service.compute_input_hash(
            kind=kind,
            workflow_id=workflow_id,
            agent_id=agent_id,
            input_data=input_payload,
        )

        # ── 3. Idempotency look-up (replay path). ───────────────────────
        if idempotency_key is not None:
            idempotency_service.validate_key(idempotency_key)
            existing, hit = await idempotency_service.check_and_acquire(
                session,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
            )
            if hit and existing is not None:
                return existing, False

        # ── 4. Capture definition snapshot from the live source row. ────
        if kind == "workflow":
            workflow = await session.get(Workflow, workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            snapshot = _capture_workflow_snapshot(workflow)
        else:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id} not found")
            snapshot = _capture_agent_snapshot(agent)

        # ── 5. Build the WorkflowRun row. ───────────────────────────────
        now = _utcnow()
        run = WorkflowRun(
            workflow_id=workflow_id,
            agent_id=agent_id,
            kind=kind,
            definition_snapshot=snapshot,
            tenant_id=tenant_id,
            status="queued",
            trigger_type=trigger_type,
            input_data=input_payload,
            triggered_by=triggered_by,
            queued_at=now,
            idempotency_key=idempotency_key,
            input_hash=input_hash,
            created_at=now,
        )

        # ── 6. Persist row + events atomically. ─────────────────────────
        try:
            session.add(run)
            await session.flush()  # allocate PK; surface CHECK violations.

            await _async_append_event(
                session,
                run.id,
                "run.created",
                payload={
                    "kind": kind,
                    "workflow_id": (
                        str(workflow_id) if workflow_id else None
                    ),
                    "agent_id": str(agent_id) if agent_id else None,
                    "trigger_type": trigger_type,
                    "triggered_by": triggered_by,
                    "input_hash": input_hash,
                },
                tenant_id=tenant_id,
            )
            await _async_append_event(
                session,
                run.id,
                "run.queued",
                payload={
                    "queued_at": now.isoformat(),
                    "input_hash": input_hash,
                },
                tenant_id=tenant_id,
            )

            await session.commit()
            await session.refresh(run)
            return run, True

        except IntegrityError:
            # ADR-004 race window: another caller won the unique-index race.
            # Rebind to the winning row and decide replay vs conflict.
            await session.rollback()
            if idempotency_key is None:
                raise

            existing, hit = await idempotency_service.check_and_acquire(
                session,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
            )
            if hit and existing is not None:
                return existing, False
            # Should not reach here — a true race resolves to either replay
            # or conflict; if neither, surface the original error.
            raise

    # ──────────────────────────────────────────────────────────────────
    # Read path
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get(
        session: AsyncSession,
        run_id: UUID,
    ) -> Union[WorkflowRun, Execution, None]:
        """Resolve a run by ID — workflow_runs first, executions fallback.

        Per ADR-006 §Lookup order. Returns the typed model instance so
        callers can branch on isinstance(...). Strict isinstance checks
        (not just ``is not None``) so test environments using MagicMock
        sessions fall through to the legacy path cleanly instead of
        masquerading as WorkflowRuns. The legacy fallback delegates to
        ``execution_service.get_execution`` so existing test patches that
        target the module-level function remain effective.
        """
        run = await session.get(WorkflowRun, run_id)
        if isinstance(run, WorkflowRun):
            return run

        # Legacy fallback — preserves test fixtures that patch
        # ``execution_service.get_execution`` and parity with the
        # pre-refactor route signature.
        from app.services import execution_service as _exec_svc

        execution = await _exec_svc.get_execution(session, run_id)
        if isinstance(execution, Execution):
            return execution
        return None

    # ──────────────────────────────────────────────────────────────────
    # Projection
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def project_to_legacy_execution_shape(
        run: WorkflowRun,
    ) -> dict[str, Any]:
        """Project a WorkflowRun to the legacy Execution JSON shape.

        Per ADR-006 §Response projection mapping. Output keys are the
        union of legacy Execution model_dump and the documented projection
        table — clients calling GET /executions/{id} see no diff.

        ``steps``, ``output_data``, and ``metrics`` are best-effort: the
        caller is responsible for hydrating step details if a richer
        response is needed (selectinload pattern per the ADR).
        """
        # Snapshot may carry a roll-up under 'last_output' (informative).
        snapshot: dict[str, Any] = run.definition_snapshot or {}
        last_output = (
            snapshot.get("last_output") if isinstance(snapshot, dict) else None
        )

        # Latest of created_at / started_at / completed_at — mimic
        # Execution.updated_at (which we don't carry on WorkflowRun).
        timestamps: list[datetime] = [run.created_at]
        if run.started_at is not None:
            timestamps.append(run.started_at)
        if run.completed_at is not None:
            timestamps.append(run.completed_at)
        updated_at = max(timestamps)

        metrics = run.metrics or {}
        if not metrics and run.duration_ms is not None:
            metrics = {
                "total_duration_ms": run.duration_ms,
                "total_tokens": 0,
                "total_cost": 0.0,
            }

        return {
            "id": str(run.id),
            "agent_id": str(run.agent_id) if run.agent_id else None,
            "status": run.status,
            "input_data": run.input_data or {},
            "output_data": run.output_data if run.output_data is not None else last_output,
            "error": run.error,
            "steps": [],  # caller may hydrate from workflow_run_steps
            "metrics": metrics,
            "started_at": (
                run.started_at.isoformat() if run.started_at else None
            ),
            "completed_at": (
                run.completed_at.isoformat() if run.completed_at else None
            ),
            "created_at": run.created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
            # New canonical fields exposed for clients that opt in via
            # ?canonical=true — see routes/executions.py.
            "run_id": str(run.id),
            "kind": run.kind,
            "workflow_id": str(run.workflow_id) if run.workflow_id else None,
        }


__all__ = [
    "ExecutionFacade",
]
