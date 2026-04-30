"""Agent CRUD endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import get_current_user
from app.interfaces.models.enterprise import AuthenticatedUser
from app.models import Agent
from app.schemas.agent_schemas import (
    AgentCreate,
    AgentUpdate,
    ExecuteAgentRequest,
)
from app.services import agent_service
from app.services.dispatch_runtime import schedule_dispatch
from app.services.execution_facade import ExecutionFacade
from app.services.idempotency_service import IdempotencyConflict
from app.services.run_dispatcher import dispatch_run

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

router = APIRouter(prefix="/agents", tags=["agents"])


# ── Helpers ──────────────────────────────────────────────────────────

def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Routes ───────────────────────────────────────────────────────────

@router.get("/")
async def list_agents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List agents with pagination."""
    agents, total = await agent_service.list_agents(session, limit=limit, offset=offset)
    return {
        "data": [a.model_dump(mode="json") for a in agents],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.post("/", status_code=201)
async def create_agent(
    body: AgentCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new agent."""
    span_ctx = _tracer.start_as_current_span("create_agent") if _tracer else None
    try:
        if span_ctx:
            span_ctx.__enter__()
        data = body.model_dump(mode="json")
        # Use default owner_id if none provided
        if data.get("owner_id") is None:
            data["owner_id"] = UUID("00000000-0000-0000-0000-000000000001")
        else:
            data["owner_id"] = UUID(data["owner_id"])
        agent = Agent(**data)
        created = await agent_service.create_agent(session, agent)
        return {
            "data": created.model_dump(mode="json"),
            "meta": _meta(),
        }
    finally:
        if span_ctx:
            span_ctx.__exit__(None, None, None)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single agent by ID."""
    agent = await agent_service.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "data": agent.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.put("/{agent_id}")
async def update_agent(
    agent_id: UUID,
    body: AgentUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an existing agent."""
    data = body.model_dump(exclude_unset=True, mode="json")
    agent = await agent_service.update_agent(session, agent_id, data)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "data": agent.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete an agent."""
    deleted = await agent_service.delete_agent(session, agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    return Response(status_code=204)


@router.post("/{agent_id}/execute")
async def execute_agent(
    agent_id: UUID,
    body: ExecuteAgentRequest,
    response: Response,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create and run an execution for a given agent (canonical path).

    Per ADR-001: persists a WorkflowRun with kind="agent" via the
    ExecutionFacade. The dispatcher receives a real WorkflowRun.id —
    closing Conflict 9 (Execution.id was previously handed to dispatch_run
    and silently no-oped because the row never existed in workflow_runs).

    Returns 201 + ``execution_id`` (alias for ``run_id``) on new runs;
    200 + ``execution_id`` on idempotent replay; 409 on idempotency
    conflict.
    """
    tenant_id = (
        UUID(user.tenant_id)
        if user and user.tenant_id
        else UUID("00000000-0000-0000-0000-000000000000")
    )

    try:
        run, is_new = await ExecutionFacade.create_run(
            session,
            kind="agent",
            agent_id=agent_id,
            tenant_id=tenant_id,
            input_data=body.input or {},
            triggered_by=(user.email if user else "") or "",
            trigger_type="manual",
            idempotency_key=x_idempotency_key,
        )
    except IdempotencyConflict as exc:
        response.status_code = 409
        return {
            "error": {
                "code": "idempotency_conflict",
                "message": "Idempotency key already used with different input.",
                "key": exc.key,
                "existing_run_id": str(exc.existing_run_id),
            },
            "meta": _meta(),
        }
    except ValueError as exc:
        # Agent missing or other invariant — surface as 404.
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if is_new:
        # Hand the dispatcher a WorkflowRun.id (NOT an Execution.id) — this
        # is the structural fix for Conflict 9. schedule_dispatch awaits
        # inline under ARCHON_DISPATCH_INLINE=1 (test/CI) and otherwise
        # schedules a tracked background task with done-callback logging.
        # run_id lets the runtime persist a terminal failed state on the
        # row if the background coroutine raises (P0 hardening).
        await schedule_dispatch(dispatch_run(run.id), run_id=run.id)
        response.status_code = 201
    else:
        response.status_code = 200

    return {
        "data": {
            "execution_id": str(run.id),
            "run_id": str(run.id),
            "kind": run.kind,
            "status": run.status,
        },
        "meta": _meta(replay=not is_new),
    }
