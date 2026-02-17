"""Agent CRUD endpoints."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Agent, Execution
from app.schemas.agent_schemas import (
    AgentCreate,
    AgentUpdate,
    ExecuteAgentRequest,
)
from app.services import agent_service, execution_service

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
) -> None:
    """Delete an agent."""
    deleted = await agent_service.delete_agent(session, agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")


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


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


def _simulate_execution(execution: Execution) -> None:
    """Populate *execution* with mock completed-run data (in-place)."""
    now = _utcnow()
    duration_ms = random.randint(120, 2500)
    execution.status = "running"
    execution.started_at = now
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


@router.post("/{agent_id}/execute", status_code=201)
async def execute_agent(
    agent_id: UUID,
    body: ExecuteAgentRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create and run an execution for a given agent.

    Accepts ``{"input": {...}, "config_overrides": {...}}``, creates an
    Execution record, stubs the processing, and returns the execution_id.
    """
    # Verify the agent exists
    agent = await agent_service.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    execution = Execution(agent_id=agent_id, input_data=body.input)
    _simulate_execution(execution)
    created = await execution_service.create_execution(session, execution)
    return {
        "data": {"execution_id": str(created.id)},
        "meta": _meta(),
    }
