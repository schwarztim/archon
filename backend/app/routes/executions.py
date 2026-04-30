"""Execution endpoints — unified by ExecutionFacade (ADR-001/004/006).

Three public endpoints:
  POST /executions             — create + dispatch a new run.
                                 Accepts both legacy {agent_id, input_data}
                                 and canonical {workflow_id, input_data}.
  GET  /executions/{id}        — read; legacy projection by default,
                                 canonical shape via ?canonical=true.
  POST /executions/{id}/cancel — record cancel intent; dispatcher honors it.

Plus list / replay / delete endpoints retained from the legacy surface
during the ADR-006 deprecation window.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.database import get_session
from app.middleware.auth import get_current_user
from app.interfaces.models.enterprise import AuthenticatedUser
from app.models import Execution
from app.models.workflow import WorkflowRun
from app.services import execution_service
from app.services.dispatch_runtime import schedule_dispatch
from app.services.execution_facade import ExecutionFacade
from app.services.execution_service import ExecutionService
from app.services.idempotency_service import IdempotencyConflict
from app.services.run_dispatcher import dispatch_run

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

router = APIRouter(tags=["executions"])


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# ── Request schemas ──────────────────────────────────────────────────


class ExecutionCreate(BaseModel):
    """Payload to create an execution (legacy /execute endpoint)."""

    agent_id: UUID
    input_data: dict[str, Any]


class ExecutionInput(BaseModel):
    """Simplified payload for the run-agent convenience endpoint."""

    input_data: dict[str, Any]


class ExecutionRunRequest(BaseModel):
    """Unified payload for POST /executions.

    Accepts EITHER ``workflow_id`` OR ``agent_id`` (XOR enforced by the
    facade). ``idempotency_key`` may travel via this field or via the
    ``X-Idempotency-Key`` header — the header wins per ADR-004.
    """

    workflow_id: UUID | None = None
    agent_id: UUID | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    config_overrides: dict[str, Any] | None = None
    idempotency_key: str | None = None
    triggered_by: str | None = None
    trigger_type: str | None = None


class ExecutionReplayRequest(BaseModel):
    """Payload for POST /executions/{id}/replay."""

    input_override: dict[str, Any] | None = None
    config_overrides: dict[str, Any] | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _resolve_tenant_id(user: AuthenticatedUser | None) -> UUID:
    """Resolve tenant UUID from an authenticated user, with dev-mode fallback.

    Tolerates ``user=None`` (test environments where the auth dependency
    is overridden to a no-op).
    """
    if user is not None and user.tenant_id:
        return UUID(user.tenant_id)
    return UUID("00000000-0000-0000-0000-000000000000")


def _resolve_idempotency_key(
    *,
    header_value: str | None,
    body_value: str | None,
) -> str | None:
    """Per ADR-004: header wins over body when both are supplied."""
    if header_value is not None and header_value != "":
        return header_value
    return body_value


def _run_response_payload(
    run: WorkflowRun,
    *,
    is_new: bool,
) -> dict[str, Any]:
    """Build the standard create/replay response envelope.

    Includes legacy ``execution_id`` alias so existing clients reading
    that key continue to work during the ADR-006 transition window.
    """
    legacy = ExecutionFacade.project_to_legacy_execution_shape(run)
    legacy["execution_id"] = legacy["id"]  # alias for legacy clients
    return {
        "data": legacy,
        "meta": _meta(replay=not is_new),
    }


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/executions")
async def create_and_run_execution(
    body: ExecutionRunRequest,
    request: Request,
    response: Response,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a WorkflowRun (workflow- or agent-driven) and dispatch.

    On idempotency hit returns 200 with the original run; otherwise 201
    with the freshly created run. Dispatch happens in a background task
    so the response returns immediately after durable persistence.
    """
    tenant_id = _resolve_tenant_id(user)

    has_workflow = body.workflow_id is not None
    has_agent = body.agent_id is not None
    if has_workflow == has_agent:
        raise HTTPException(
            status_code=422,
            detail=(
                "Exactly one of workflow_id or agent_id must be provided. "
                "Got both or neither."
            ),
        )

    kind = "workflow" if has_workflow else "agent"
    idempotency_key = _resolve_idempotency_key(
        header_value=x_idempotency_key,
        body_value=body.idempotency_key,
    )

    try:
        run, is_new = await ExecutionFacade.create_run(
            session,
            kind=kind,
            workflow_id=body.workflow_id,
            agent_id=body.agent_id,
            tenant_id=tenant_id,
            input_data=body.input_data or {},
            triggered_by=body.triggered_by or (user.email if user else "") or "",
            trigger_type=body.trigger_type or "manual",
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflict as exc:
        return _idempotency_conflict_response(
            response,
            key=exc.key,
            existing_run_id=exc.existing_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if is_new:
        # Dispatch async. The dispatcher rebinds the run via its own
        # session — passing the WorkflowRun.id is the contract per ADR-001.
        # schedule_dispatch awaits inline when ARCHON_DISPATCH_INLINE=1
        # (test/CI) and otherwise schedules a tracked background task with
        # done-callback logging. Replaces raw asyncio.create_task to fix
        # GC drops + lost exceptions. The run_id kwarg lets the runtime
        # persist a terminal failed state on the row when the background
        # coroutine raises (P0 hardening, plan a6a915dc).
        await schedule_dispatch(dispatch_run(run.id), run_id=run.id)
        response.status_code = 201
    else:
        response.status_code = 200

    return _run_response_payload(run, is_new=is_new)


def _idempotency_conflict_response(
    response: Response,
    *,
    key: str,
    existing_run_id: UUID,
) -> dict[str, Any]:
    """Build the 409 envelope per ADR-004 §Behaviour."""
    response.status_code = 409
    return {
        "error": {
            "code": "idempotency_conflict",
            "message": (
                "Idempotency key already used with different input."
            ),
            "key": key,
            "existing_run_id": str(existing_run_id),
        },
        "meta": _meta(),
    }


@router.post("/execute", status_code=201)
async def create_execution(
    body: ExecutionCreate,
    response: Response,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Legacy /execute endpoint — agent-only, routes through the facade."""
    span_ctx = _tracer.start_as_current_span("create_execution") if _tracer else None
    try:
        if span_ctx:
            span_ctx.__enter__()

        tenant_id = _resolve_tenant_id(user)
        try:
            run, is_new = await ExecutionFacade.create_run(
                session,
                kind="agent",
                agent_id=body.agent_id,
                tenant_id=tenant_id,
                input_data=body.input_data or {},
                triggered_by=(user.email if user else "") or "",
                trigger_type="manual",
                idempotency_key=x_idempotency_key,
            )
        except IdempotencyConflict as exc:
            return _idempotency_conflict_response(
                response,
                key=exc.key,
                existing_run_id=exc.existing_run_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if is_new:
            # See schedule_dispatch comment on POST /executions: inline-await
            # in test/CI, tracked task in production. run_id surfaces the
            # row id so failed background dispatches finalise the row.
            await schedule_dispatch(dispatch_run(run.id), run_id=run.id)
            response.status_code = 201
        else:
            response.status_code = 200

        return _run_response_payload(run, is_new=is_new)
    finally:
        if span_ctx:
            span_ctx.__exit__(None, None, None)


@router.get("/executions")
async def list_executions(
    agent_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List executions with optional agent_id and status filters.

    Currently lists from the legacy ``executions`` table only; ADR-006
    stages a UNION list at N+1 — out of scope for Phase 1.
    """
    executions, total = await execution_service.list_executions(
        session, agent_id=agent_id, status=status, limit=limit, offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in executions],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: UUID,
    canonical: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single run by ID — workflow_runs first, executions fallback.

    Default response is the legacy Execution shape so existing clients
    continue to work. Pass ``?canonical=true`` to receive the WorkflowRun
    JSON shape verbatim.
    """
    resolved = await ExecutionFacade.get(session, execution_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if isinstance(resolved, WorkflowRun):
        if canonical:
            data = resolved.model_dump(mode="json")
        else:
            data = ExecutionFacade.project_to_legacy_execution_shape(resolved)
            # Hydrate steps and agent_name lazily for richer response.
            from app.models import Agent
            from app.models.workflow import WorkflowRunStep
            from sqlmodel import select as _select

            step_stmt = _select(WorkflowRunStep).where(
                WorkflowRunStep.run_id == resolved.id
            )
            step_result = await session.exec(step_stmt)
            steps = list(step_result.all())
            data["steps"] = [s.model_dump(mode="json") for s in steps]
            data["metrics_summary"] = {
                "total_steps": len(steps),
                "completed_steps": len(
                    [s for s in steps if s.status == "completed"]
                ),
                "failed_steps": len(
                    [s for s in steps if s.status == "failed"]
                ),
            }
            if resolved.agent_id is not None:
                agent_stmt = _select(Agent).where(Agent.id == resolved.agent_id)
                agent_result = await session.exec(agent_stmt)
                agent = agent_result.first()
                data["agent_name"] = agent.name if agent else "Unknown"
        return {
            "data": data,
            "meta": _meta(source="workflow_runs"),
        }

    # Legacy Execution row.
    execution = resolved  # type: Execution

    from app.models import Agent
    from sqlmodel import select as _select

    agent_stmt = _select(Agent).where(Agent.id == execution.agent_id)
    agent_result = await session.exec(agent_stmt)
    agent = agent_result.first()

    data = execution.model_dump(mode="json")
    data["agent_name"] = agent.name if agent else "Unknown"
    data["metrics_summary"] = {
        "total_steps": len(execution.steps) if execution.steps else 0,
        "completed_steps": len(
            [s for s in (execution.steps or []) if s.get("status") == "completed"]
        ),
        "failed_steps": len(
            [s for s in (execution.steps or []) if s.get("status") == "failed"]
        ),
    }
    return {
        "data": data,
        "meta": _meta(source="executions"),
    }


@router.post("/executions/{execution_id}/replay", status_code=201)
async def replay_execution(
    execution_id: UUID,
    body: ExecutionReplayRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Re-run an execution with same or modified input."""
    tenant_id = _resolve_tenant_id(user)
    parsed_body = body or ExecutionReplayRequest()
    try:
        execution = await ExecutionService.replay_execution(
            session,
            execution_id,
            tenant_id=tenant_id,
            user=user,
            input_override=parsed_body.input_override,
            config_overrides=parsed_body.config_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "data": execution.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: UUID,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Record cancel intent on a run.

    For WorkflowRun rows: stamps ``cancel_requested_at`` and emits a
    ``run.cancelled`` event (per ADR-002). The dispatcher / worker is
    responsible for honoring the intent — this endpoint is durably
    accepted only.

    For legacy Execution rows: row mutation only; no event log.
    """
    resolved = await ExecutionFacade.get(session, execution_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if isinstance(resolved, WorkflowRun):
        run = resolved
        if run.status in ("completed", "failed", "cancelled"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel run in '{run.status}' state",
            )
        run.cancel_requested_at = _utcnow()
        # Mark cancellation intent in status when the run hasn't started
        # processing yet; otherwise leave dispatcher to honor it.
        if run.status in ("pending", "queued"):
            run.status = "cancelled"
            run.completed_at = _utcnow()
        session.add(run)

        # Emit run.cancelled event (ADR-002 §run lifecycle).
        from app.services.execution_facade import _async_append_event

        try:
            await _async_append_event(
                session,
                run.id,
                "run.cancelled",
                payload={
                    "cancel_requested_at": run.cancel_requested_at.isoformat(),
                    "actor": (user.email if user else "") or "",
                },
                tenant_id=run.tenant_id,
            )
        except ValueError:
            # Event-type mismatch is unrecoverable but should not mask
            # the cancel intent — log via dispatcher next pass.
            pass

        await session.commit()
        await session.refresh(run)
        response.status_code = 202
        return {
            "data": ExecutionFacade.project_to_legacy_execution_shape(run),
            "meta": _meta(source="workflow_runs", cancel_intent=True),
        }

    # Legacy Execution path.
    execution = resolved  # type: Execution
    if execution.status not in ("pending", "running", "queued"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel execution in '{execution.status}' state",
        )
    execution.status = "cancelled"
    execution.updated_at = _utcnow()
    session.add(execution)
    await session.commit()
    await session.refresh(execution)
    return {
        "data": execution.model_dump(mode="json"),
        "meta": _meta(source="executions"),
    }


@router.delete("/executions/{execution_id}", status_code=204, response_class=Response)
async def delete_execution(
    execution_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    """Delete an execution record."""
    resolved = await ExecutionFacade.get(session, execution_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    await session.delete(resolved)
    await session.commit()
    return Response(status_code=204)
