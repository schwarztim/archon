"""Agent CRUD endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Agent
from app.services import agent_service

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

router = APIRouter(prefix="/agents", tags=["agents"])


# ── Request / response schemas ──────────────────────────────────────

class AgentCreate(BaseModel):
    """Payload for creating an agent."""

    name: str
    description: str | None = None
    definition: dict[str, Any]
    status: str = "draft"
    owner_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    tags: list[str] = PField(default_factory=list)
    steps: list[dict] | None = None
    tools: list[dict] | None = None
    llm_config: dict | None = None
    rag_config: dict | None = None
    mcp_config: dict | None = None
    security_policy: dict | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    graph_definition: dict | None = None
    group_id: str | None = None


class AgentUpdate(BaseModel):
    """Payload for updating an agent (partial)."""

    name: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None
    status: str | None = None
    tags: list[str] | None = None
    steps: list[dict] | None = None
    tools: list[dict] | None = None
    llm_config: dict | None = None
    rag_config: dict | None = None
    mcp_config: dict | None = None
    security_policy: dict | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    graph_definition: dict | None = None
    group_id: str | None = None


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
        agent = Agent(**body.model_dump())
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
    data = body.model_dump(exclude_unset=True)
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
