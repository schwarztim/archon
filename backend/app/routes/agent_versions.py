"""AgentVersion endpoints (immutable snapshots — create & read only)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AgentVersion
from app.services import AgentVersionService

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

router = APIRouter(prefix="/agent-versions", tags=["agent-versions"])


# ── Request / response schemas ──────────────────────────────────────


class AgentVersionCreate(BaseModel):
    """Payload for creating an agent version snapshot."""

    agent_id: UUID
    version: str
    definition: dict[str, Any]
    change_log: str | None = None
    created_by: UUID = UUID("00000000-0000-0000-0000-000000000001")


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
async def list_agent_versions(
    agent_id: UUID = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List versions for a given agent with pagination."""
    versions, total = await AgentVersionService.list_by_agent(
        session, agent_id=agent_id, limit=limit, offset=offset,
    )
    return {
        "data": [v.model_dump(mode="json") for v in versions],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.post("/", status_code=201)
async def create_agent_version(
    body: AgentVersionCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new immutable agent version snapshot."""
    span_ctx = _tracer.start_as_current_span("create_agent_version") if _tracer else None
    try:
        if span_ctx:
            span_ctx.__enter__()
        version = AgentVersion(**body.model_dump())
        created = await AgentVersionService.create(session, version)
        return {
            "data": created.model_dump(mode="json"),
            "meta": _meta(),
        }
    finally:
        if span_ctx:
            span_ctx.__exit__(None, None, None)


@router.get("/latest")
async def get_latest_agent_version(
    agent_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the latest version for a given agent."""
    version = await AgentVersionService.get_latest(session, agent_id)
    if version is None:
        raise HTTPException(status_code=404, detail="No versions found for agent")
    return {
        "data": version.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/{version_id}")
async def get_agent_version(
    version_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single agent version by ID."""
    version = await AgentVersionService.get(session, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Agent version not found")
    return {
        "data": version.model_dump(mode="json"),
        "meta": _meta(),
    }
