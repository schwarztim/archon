"""Execution endpoints."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import get_current_user
from app.interfaces.models.enterprise import AuthenticatedUser
from app.models import Execution
from app.services import execution_service
from app.services.execution_service import ExecutionService

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

router = APIRouter(tags=["executions"])


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# ── Mock execution helpers ───────────────────────────────────────────

_MOCK_STEPS: list[dict[str, Any]] = [
    {"name": "input", "status": "completed"},
    {"name": "llm_call", "status": "completed", "tokens": 150},
    {"name": "output", "status": "completed"},
]

_MOCK_OUTPUT: dict[str, Any] = {
    "response": "Agent execution completed successfully",
    "steps": _MOCK_STEPS,
}


def _simulate_execution(execution: Execution) -> None:
    """Populate *execution* with mock completed-run data (in-place)."""
    now = _utcnow()
    duration_ms = random.randint(120, 2500)
    execution.status = "running"
    execution.started_at = now
    # Immediately mark completed (no real runtime)
    execution.output_data = _MOCK_OUTPUT
    execution.status = "completed"
    execution.completed_at = now
    execution.steps = _MOCK_STEPS
    execution.metrics = {
        "duration_ms": duration_ms,
        "total_tokens": 150,
        "estimated_cost": round(150 * 0.00003, 6),
    }
    execution.updated_at = now


# ── Request schemas ──────────────────────────────────────────────────

class ExecutionCreate(BaseModel):
    """Payload to create an execution."""

    agent_id: UUID
    input_data: dict[str, Any]


class ExecutionInput(BaseModel):
    """Simplified payload for the run-agent convenience endpoint."""

    input_data: dict[str, Any]


class ExecutionRunRequest(BaseModel):
    """Payload for POST /executions — create and run an agent execution."""

    agent_id: UUID
    input_data: dict[str, Any] = Field(default_factory=dict)
    config_overrides: dict[str, Any] | None = None


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


# ── Routes ───────────────────────────────────────────────────────────

@router.post("/executions", status_code=201)
async def create_and_run_execution(
    body: ExecutionRunRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create and run an agent execution with per-step trace data."""
    tenant_id = UUID(user.tenant_id) if user.tenant_id else UUID("00000000-0000-0000-0000-000000000000")
    try:
        execution = await ExecutionService.run_execution(
            session,
            body.agent_id,
            body.input_data,
            tenant_id=tenant_id,
            user=user,
            config_overrides=body.config_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "data": execution.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/execute", status_code=201)
async def create_execution(
    body: ExecutionCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Queue a new agent execution and simulate completion."""
    span_ctx = _tracer.start_as_current_span("create_execution") if _tracer else None
    try:
        if span_ctx:
            span_ctx.__enter__()
        execution = Execution(**body.model_dump())
        _simulate_execution(execution)
        created = await execution_service.create_execution(session, execution)
        return {
            "data": created.model_dump(mode="json"),
            "meta": _meta(),
        }
    finally:
        if span_ctx:
            span_ctx.__exit__(None, None, None)


@router.post("/agents/{agent_id}/execute", status_code=201)
async def execute_agent(
    agent_id: UUID,
    body: ExecutionInput,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """User-friendly endpoint: create & run an execution for a given agent."""
    execution = Execution(agent_id=agent_id, input_data=body.input_data)
    _simulate_execution(execution)
    created = await execution_service.create_execution(session, execution)
    return {
        "data": created.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/executions")
async def list_executions(
    agent_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List executions with optional agent_id and status filters."""
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
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single execution by ID with expanded detail."""
    execution = await execution_service.get_execution(session, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    # Enrich with agent name
    from app.models import Agent
    from sqlmodel import select
    agent_stmt = select(Agent).where(Agent.id == execution.agent_id)
    agent_result = await session.exec(agent_stmt)
    agent = agent_result.first()

    data = execution.model_dump(mode="json")
    data["agent_name"] = agent.name if agent else "Unknown"
    data["metrics_summary"] = {
        "total_steps": len(execution.steps) if execution.steps else 0,
        "completed_steps": len([s for s in (execution.steps or []) if s.get("status") == "completed"]),
        "failed_steps": len([s for s in (execution.steps or []) if s.get("status") == "failed"]),
    }
    return {
        "data": data,
        "meta": _meta(),
    }


@router.post("/executions/{execution_id}/replay", status_code=201)
async def replay_execution(
    execution_id: UUID,
    body: ExecutionReplayRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Re-run an execution with same or modified input."""
    tenant_id = UUID(user.tenant_id) if user.tenant_id else UUID("00000000-0000-0000-0000-000000000000")
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
