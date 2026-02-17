"""Execution endpoints."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Execution
from app.services import execution_service

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


# ── Helpers ──────────────────────────────────────────────────────────

def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Routes ───────────────────────────────────────────────────────────

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
    """Get a single execution by ID."""
    execution = await execution_service.get_execution(session, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return {
        "data": execution.model_dump(mode="json"),
        "meta": _meta(),
    }
