"""API routes for MCP interactive components, sessions, and interactions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.mcp import MCPService
from starlette.responses import Response

router = APIRouter(prefix="/mcp", tags=["mcp"])


# ── Request / response schemas ──────────────────────────────────────


class ComponentCreate(BaseModel):
    """Payload for creating an MCP component."""

    session_id: UUID
    component_type: str  # form | chart | table | text | code | image
    props: dict[str, Any] = PField(default_factory=dict)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class ComponentUpdate(BaseModel):
    """Payload for partial-updating an MCP component."""

    props: dict[str, Any] | None = None
    state: str | None = None
    extra_metadata: dict[str, Any] | None = None


class SessionCreate(BaseModel):
    """Payload for creating an MCP session."""

    agent_id: UUID | None = None
    user_id: UUID | None = None
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class InteractionCreate(BaseModel):
    """Payload for recording a user interaction."""

    session_id: UUID
    component_id: UUID
    event_type: str
    payload: dict[str, Any] = PField(default_factory=dict)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Session Endpoints ───────────────────────────────────────────────


@router.post("/sessions", status_code=201)
async def create_session(
    body: SessionCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new MCP interactive session."""
    mcp_session = await MCPService.create_session(
        session,
        agent_id=body.agent_id,
        user_id=body.user_id,
        extra_metadata=body.extra_metadata,
    )
    return {"data": mcp_session.model_dump(mode="json"), "meta": _meta()}


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    agent_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List MCP sessions with pagination."""
    sessions, total = await MCPService.list_sessions(
        session,
        agent_id=agent_id,
        user_id=user_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [s.model_dump(mode="json") for s in sessions],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/sessions/{session_id}")
async def get_mcp_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get an MCP session by ID."""
    mcp_session = await MCPService.get_session(session, session_id)
    if mcp_session is None:
        raise HTTPException(status_code=404, detail="MCP session not found")
    return {"data": mcp_session.model_dump(mode="json"), "meta": _meta()}


@router.post("/sessions/{session_id}/close")
async def close_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Close an active MCP session."""
    mcp_session = await MCPService.close_session(session, session_id)
    if mcp_session is None:
        raise HTTPException(status_code=404, detail="MCP session not found")
    return {"data": mcp_session.model_dump(mode="json"), "meta": _meta()}


# ── Component Endpoints ────────────────────────────────────────────


@router.post("/components", status_code=201)
async def create_component(
    body: ComponentCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new interactive component."""
    try:
        component = await MCPService.create_component(
            session,
            session_id=body.session_id,
            component_type=body.component_type,
            props=body.props,
            extra_metadata=body.extra_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": component.model_dump(mode="json"), "meta": _meta()}


@router.get("/components")
async def list_components(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session_id: UUID | None = Query(default=None),
    component_type: str | None = Query(default=None),
    state: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List MCP components with pagination."""
    components, total = await MCPService.list_components(
        session,
        session_id=session_id,
        component_type=component_type,
        state=state,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [c.model_dump(mode="json") for c in components],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/components/{component_id}")
async def get_component(
    component_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get an MCP component by ID."""
    component = await MCPService.get_component(session, component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return {"data": component.model_dump(mode="json"), "meta": _meta()}


@router.put("/components/{component_id}")
async def update_component(
    component_id: UUID,
    body: ComponentUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an MCP component."""
    data = body.model_dump(exclude_unset=True)
    component = await MCPService.update_component(session, component_id, data)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return {"data": component.model_dump(mode="json"), "meta": _meta()}


@router.delete("/components/{component_id}", status_code=204, response_class=Response)
async def delete_component(
    component_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete an MCP component."""
    deleted = await MCPService.delete_component(session, component_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Component not found")
    return Response(status_code=204)


@router.get("/components/{component_id}/render")
async def render_component(
    component_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Render a component into a WebSocket-ready message payload."""
    try:
        rendered = await MCPService.render_component(session, component_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": rendered, "meta": _meta()}


# ── Interaction Endpoints ───────────────────────────────────────────


@router.post("/interactions", status_code=201)
async def create_interaction(
    body: InteractionCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record a user interaction on a component."""
    try:
        interaction = await MCPService.handle_interaction(
            session,
            session_id=body.session_id,
            component_id=body.component_id,
            event_type=body.event_type,
            payload=body.payload,
            extra_metadata=body.extra_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": interaction.model_dump(mode="json"), "meta": _meta()}


@router.get("/interactions")
async def list_interactions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session_id: UUID | None = Query(default=None),
    component_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List interactions with pagination."""
    interactions, total = await MCPService.list_interactions(
        session,
        session_id=session_id,
        component_id=component_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [i.model_dump(mode="json") for i in interactions],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }
