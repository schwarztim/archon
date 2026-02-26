"""API routes for Live Interactive Components — session-bound, RBAC, tenant-scoped."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import require_auth
from app.middleware.rbac import require_permission
from app.models.mcp_interactive import (
    ComponentAction,
    ComponentCategory,
    ComponentConfig,
    ComponentType,
)
from app.secrets.manager import get_secrets_manager
from app.services.mcp_interactive_service import MCPInteractiveService
from starlette.responses import Response

router = APIRouter(tags=["interactive-components"])


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Request Schemas ──────────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    """Payload for creating a component session."""

    component_type: ComponentCategory


class RenderRequest(BaseModel):
    """Payload for rendering a component."""

    session_id: UUID
    component_config: ComponentConfig


class ActionRequest(BaseModel):
    """Payload for handling a component action."""

    session_id: UUID
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ComponentTypeRegisterRequest(BaseModel):
    """Payload for registering a new component type."""

    name: str
    category: ComponentCategory
    component_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")
    default_config: dict[str, Any] = Field(default_factory=dict)
    rbac_requirements: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ── Session Endpoints ────────────────────────────────────────────────


@router.post("/api/v1/components/sessions", status_code=201)
async def create_session(
    body: SessionCreateRequest,
    user: AuthenticatedUser = Depends(require_auth),
    secrets: Any = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Create a new component session bound to the user's auth context."""
    session = await MCPInteractiveService.create_component_session(
        tenant_id=user.tenant_id,
        user=user,
        component_type=body.component_type,
    )
    return {"data": session.model_dump(mode="json"), "meta": _meta()}


@router.get("/api/v1/components/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Get a component session by ID."""
    try:
        session = await MCPInteractiveService.get_session(
            tenant_id=user.tenant_id,
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"data": session.model_dump(mode="json"), "meta": _meta()}


@router.delete("/api/v1/components/sessions/{session_id}", status_code=204, response_class=Response)
async def close_session(
    session_id: UUID,
    user: AuthenticatedUser = Depends(require_auth),
) -> Response:
    """Close and clean up a component session."""
    await MCPInteractiveService.close_session(
        tenant_id=user.tenant_id,
        session_id=session_id,
    )
    return Response(status_code=204)


# ── Render Endpoint ──────────────────────────────────────────────────


@router.post("/api/v1/components/render")
async def render_component(
    body: RenderRequest,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Render a component with RBAC-filtered data."""
    try:
        rendered = await MCPInteractiveService.render_component(
            tenant_id=user.tenant_id,
            user=user,
            session_id=body.session_id,
            component_config=body.component_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"data": rendered.model_dump(mode="json"), "meta": _meta()}


# ── Action Endpoint ──────────────────────────────────────────────────


@router.post("/api/v1/components/action")
async def handle_action(
    body: ActionRequest,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Process a user interaction on a live component."""
    action = ComponentAction(
        session_id=body.session_id,
        action_type=body.action_type,
        payload=body.payload,
    )
    try:
        result = await MCPInteractiveService.handle_component_action(
            tenant_id=user.tenant_id,
            user=user,
            session_id=body.session_id,
            action=action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── Component Type Endpoints ─────────────────────────────────────────


@router.post("/api/v1/components/types", status_code=201)
async def register_component_type(
    body: ComponentTypeRegisterRequest,
    user: AuthenticatedUser = Depends(require_permission("components", "create")),
) -> dict[str, Any]:
    """Register a new component type (admin only)."""
    component_def = ComponentType(
        name=body.name,
        category=body.category,
        component_schema=body.component_schema,
        default_config=body.default_config,
        rbac_requirements=body.rbac_requirements,
    )
    try:
        created = await MCPInteractiveService.register_component_type(
            tenant_id=user.tenant_id,
            user=user,
            component_def=component_def,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/api/v1/components/types")
async def list_component_types(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """List available component types for the tenant."""
    types = await MCPInteractiveService.list_component_types(
        tenant_id=user.tenant_id,
    )
    return {
        "data": [t.model_dump(mode="json") for t in types],
        "meta": _meta(pagination={"total": len(types), "limit": 100, "offset": 0}),
    }
