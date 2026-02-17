"""API routes for the Archon MCP Security Guardian."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models.mcp_security import (
    MCPToolAuthorization,
    MCPToolDefinition,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.audit_log_service import AuditLogService
from app.services.mcp_security import MCPSecurityGuardian
from app.services.mcp_security_service import MCPSecurityService

router = APIRouter(prefix="/mcp-security", tags=["mcp-security"])


# ── Request / response schemas ──────────────────────────────────────


class AuthorizationCreate(BaseModel):
    """Payload for creating a tool authorization policy."""

    tool_name: str
    server_name: str
    agent_id: UUID | None = None
    user_id: UUID | None = None
    department_id: UUID | None = None
    action: str = "allow"
    risk_level: str = "low"
    is_active: bool = True
    parameter_constraints: dict[str, Any] = PField(default_factory=dict)
    allowed_patterns: dict[str, str] = PField(default_factory=dict)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class AuthorizationUpdate(BaseModel):
    """Payload for partial-updating a tool authorization policy."""

    tool_name: str | None = None
    server_name: str | None = None
    action: str | None = None
    risk_level: str | None = None
    is_active: bool | None = None
    parameter_constraints: dict[str, Any] | None = None
    allowed_patterns: dict[str, str] | None = None
    extra_metadata: dict[str, Any] | None = None


class AuthorizeToolRequest(BaseModel):
    """Payload for checking tool authorization."""

    tool_name: str
    server_name: str
    agent_id: UUID | None = None
    user_id: UUID | None = None
    parameters: dict[str, Any] | None = None


class SandboxCreateRequest(BaseModel):
    """Payload for creating an ephemeral sandbox session."""

    tool_name: str
    server_name: str
    agent_id: UUID | None = None
    user_id: UUID | None = None
    input_data: dict[str, Any] | None = None
    resource_limits: dict[str, Any] | None = None
    network_policy: dict[str, Any] | None = None
    timeout_seconds: int = PField(default=30, ge=1, le=300)


class SandboxCompleteRequest(BaseModel):
    """Payload for completing a sandbox session."""

    output_data: dict[str, Any] | None = None
    exit_code: int = 0
    error_message: str | None = None


class ChangeDetectionRequest(BaseModel):
    """Payload for detecting tool definition changes."""

    tool_name: str
    server_name: str
    current_definition: dict[str, Any]
    version: str = "latest"


class ValidateResponseRequest(BaseModel):
    """Payload for validating an MCP tool response."""

    tool_name: str
    server_name: str
    response_text: str
    sandbox_session_id: UUID | None = None
    max_response_bytes: int = PField(default=1_048_576, ge=1)


class PinVersionRequest(BaseModel):
    """Payload for pinning/unpinning a tool version."""

    pin: bool = True


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Authorization Endpoints ─────────────────────────────────────────


@router.post("/authorize")
async def authorize_tool(
    body: AuthorizeToolRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Check whether a tool call is authorized."""
    decision = await MCPSecurityGuardian.authorize_tool(
        session,
        tool_name=body.tool_name,
        server_name=body.server_name,
        agent_id=body.agent_id,
        user_id=body.user_id,
        parameters=body.parameters,
    )
    return {"data": decision.to_dict(), "meta": _meta()}


@router.get("/authorizations")
async def list_authorizations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tool_name: str | None = Query(default=None),
    server_name: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List tool authorization policies with pagination."""
    auths, total = await MCPSecurityGuardian.list_authorizations(
        session,
        tool_name=tool_name,
        server_name=server_name,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [a.model_dump(mode="json") for a in auths],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/authorizations", status_code=201)
async def create_authorization(
    body: AuthorizationCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new tool authorization policy."""
    auth = MCPToolAuthorization(**body.model_dump())
    created = await MCPSecurityGuardian.create_authorization(session, auth)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/authorizations/{auth_id}")
async def get_authorization(
    auth_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a tool authorization policy by ID."""
    auth = await MCPSecurityGuardian.get_authorization(session, auth_id)
    if auth is None:
        raise HTTPException(status_code=404, detail="Authorization not found")
    return {"data": auth.model_dump(mode="json"), "meta": _meta()}


@router.put("/authorizations/{auth_id}")
async def update_authorization(
    auth_id: UUID,
    body: AuthorizationUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a tool authorization policy."""
    data = body.model_dump(exclude_unset=True)
    auth = await MCPSecurityGuardian.update_authorization(session, auth_id, data)
    if auth is None:
        raise HTTPException(status_code=404, detail="Authorization not found")
    return {"data": auth.model_dump(mode="json"), "meta": _meta()}


@router.delete("/authorizations/{auth_id}", status_code=204)
async def delete_authorization(
    auth_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a tool authorization policy."""
    deleted = await MCPSecurityGuardian.delete_authorization(session, auth_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Authorization not found")


# ── Sandbox Endpoints ───────────────────────────────────────────────


@router.post("/sandboxes", status_code=201)
async def create_sandbox(
    body: SandboxCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create an ephemeral sandbox session for an MCP tool call."""
    sandbox = await MCPSecurityGuardian.create_sandbox(
        session,
        tool_name=body.tool_name,
        server_name=body.server_name,
        agent_id=body.agent_id,
        user_id=body.user_id,
        input_data=body.input_data,
        resource_limits=body.resource_limits,
        network_policy=body.network_policy,
        timeout_seconds=body.timeout_seconds,
    )
    return {"data": sandbox.model_dump(mode="json"), "meta": _meta()}


@router.get("/sandboxes")
async def list_sandboxes(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    tool_name: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List sandbox sessions with pagination."""
    sandboxes, total = await MCPSecurityGuardian.list_sandboxes(
        session, status=status, tool_name=tool_name, limit=limit, offset=offset,
    )
    return {
        "data": [s.model_dump(mode="json") for s in sandboxes],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/sandboxes/{sandbox_id}")
async def get_sandbox(
    sandbox_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a sandbox session by ID."""
    sandbox = await MCPSecurityGuardian.get_sandbox(session, sandbox_id)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox session not found")
    return {"data": sandbox.model_dump(mode="json"), "meta": _meta()}


@router.post("/sandboxes/{sandbox_id}/complete")
async def complete_sandbox(
    sandbox_id: UUID,
    body: SandboxCompleteRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Mark a sandbox session as completed and destroyed."""
    sandbox = await MCPSecurityGuardian.complete_sandbox(
        session,
        sandbox_id,
        output_data=body.output_data,
        exit_code=body.exit_code,
        error_message=body.error_message,
    )
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox session not found")
    return {"data": sandbox.model_dump(mode="json"), "meta": _meta()}


# ── Change Detection Endpoints ──────────────────────────────────────


@router.post("/changes/detect")
async def detect_changes(
    body: ChangeDetectionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Detect changes in an MCP tool definition."""
    result = await MCPSecurityGuardian.detect_changes(
        session,
        tool_name=body.tool_name,
        server_name=body.server_name,
        current_definition=body.current_definition,
        version=body.version,
    )
    return {"data": result, "meta": _meta()}


@router.get("/tool-versions")
async def list_tool_versions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tool_name: str | None = Query(default=None),
    server_name: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List tool versions with pagination."""
    versions, total = await MCPSecurityGuardian.list_tool_versions(
        session,
        tool_name=tool_name,
        server_name=server_name,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [v.model_dump(mode="json") for v in versions],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/tool-versions/{version_id}/pin")
async def pin_tool_version(
    version_id: UUID,
    body: PinVersionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Pin or unpin a tool version."""
    version = await MCPSecurityGuardian.pin_version(
        session, version_id, pin=body.pin,
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Tool version not found")
    return {"data": version.model_dump(mode="json"), "meta": _meta()}


# ── Response Validation Endpoints ───────────────────────────────────


@router.post("/validate-response")
async def validate_response(
    body: ValidateResponseRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Validate an MCP tool response for injection and anomalies."""
    result = await MCPSecurityGuardian.validate_response(
        session,
        tool_name=body.tool_name,
        server_name=body.server_name,
        response_text=body.response_text,
        sandbox_session_id=body.sandbox_session_id,
        max_response_bytes=body.max_response_bytes,
    )
    return {"data": result.to_dict(), "meta": _meta()}


# ── Security Events Endpoints ───────────────────────────────────────


@router.get("/events")
async def list_events(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    tool_name: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List security events with pagination."""
    events, total = await MCPSecurityGuardian.list_events(
        session,
        event_type=event_type,
        severity=severity,
        tool_name=tool_name,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in events],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/events/{event_id}")
async def get_event(
    event_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a security event by ID."""
    event = await MCPSecurityGuardian.get_event(session, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Security event not found")
    return {"data": event.model_dump(mode="json"), "meta": _meta()}


# ── Enterprise OAuth-Scoped MCP Endpoints ───────────────────────────

# V1 API router for enterprise MCP security endpoints
v1_router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-security-v1"])


class AuthorizeToolCallRequest(BaseModel):
    """Request to authorize an OAuth-scoped tool call."""

    tool_id: str
    scopes: list[str] = PField(default_factory=list)


class ExecuteToolRequest(BaseModel):
    """Request to execute a tool in a sandbox."""

    tool_id: str
    params: dict[str, Any] = PField(default_factory=dict)


class ConsentRequest(BaseModel):
    """Request to manage scope consent."""

    tool_id: str
    action: str = PField(description="grant or revoke")
    scopes: list[str] = PField(default_factory=list)


class ValidateToolResponseRequest(BaseModel):
    """Request to validate a tool response."""

    tool_id: str
    response: dict[str, Any] = PField(default_factory=dict)


class TrackVersionRequest(BaseModel):
    """Request to track a new tool version."""

    definition: MCPToolDefinition


@v1_router.post("/authorize")
async def authorize_tool_call_v1(
    body: AuthorizeToolCallRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Authorize an OAuth-scoped tool call."""
    if not check_permission(user, "mcp", "execute"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await MCPSecurityService.authorize_tool_call(
        user.tenant_id, user, body.tool_id, body.scopes,
    )
    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="mcp.tool.authorize",
        resource_type="mcp_tool",
        resource_id=UUID(int=0),
        details={"tool_id": body.tool_id, "authorized": result.authorized, "tenant_id": user.tenant_id},
    )
    return {"data": result.model_dump(), "meta": _meta()}


@v1_router.post("/execute")
async def execute_tool_v1(
    body: ExecuteToolRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Execute a tool in a sandboxed environment."""
    if not check_permission(user, "mcp", "execute"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await MCPSecurityService.execute_tool_sandboxed(
        user.tenant_id, user, body.tool_id, body.params,
    )
    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="mcp.tool.execute",
        resource_type="mcp_tool",
        resource_id=UUID(int=0),
        details={"tool_id": body.tool_id, "sandbox_id": result.sandbox_id, "tenant_id": user.tenant_id},
    )
    return {"data": result.model_dump(), "meta": _meta()}


@v1_router.post("/tools", status_code=201)
async def register_tool_v1(
    body: MCPToolDefinition,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register an MCP tool with required scopes and schema."""
    if not check_permission(user, "mcp", "create"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    tool = await MCPSecurityService.register_tool(user.tenant_id, user, body)
    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="mcp.tool.register",
        resource_type="mcp_tool",
        resource_id=UUID(int=0),
        details={"tool_id": tool.id, "tool_name": tool.name, "tenant_id": user.tenant_id},
    )
    return {"data": tool.model_dump(), "meta": _meta()}


@v1_router.post("/consent")
async def manage_consent_v1(
    body: ConsentRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Grant or revoke user scope consent for a tool."""
    if not check_permission(user, "mcp", "execute"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await MCPSecurityService.manage_consent(
        user.tenant_id, user, body.tool_id, body.action, body.scopes,
    )
    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action=f"mcp.consent.{body.action}",
        resource_type="mcp_tool",
        resource_id=UUID(int=0),
        details={"tool_id": body.tool_id, "action": body.action, "tenant_id": user.tenant_id},
    )
    return {"data": result.model_dump(), "meta": _meta()}


@v1_router.post("/validate")
async def validate_response_v1(
    body: ValidateToolResponseRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Validate a tool response with schema check and DLP scan."""
    if not check_permission(user, "mcp", "read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await MCPSecurityService.validate_tool_response(
        user.tenant_id, body.tool_id, body.response,
    )
    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="mcp.response.validate",
        resource_type="mcp_tool",
        resource_id=UUID(int=0),
        details={"tool_id": body.tool_id, "valid": result.valid, "tenant_id": user.tenant_id},
    )
    return {"data": result.model_dump(), "meta": _meta()}


@v1_router.get("/tools/{tool_id}/score")
async def get_security_score_v1(
    tool_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Get the security score for a tool."""
    if not check_permission(user, "mcp", "read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    score = await MCPSecurityService.compute_security_score(user.tenant_id, tool_id)
    return {"data": score.model_dump(), "meta": _meta()}


@v1_router.get("/matrix")
async def get_auth_matrix_v1(
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Get the authorization matrix for the tenant."""
    if not check_permission(user, "mcp", "read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    matrix = await MCPSecurityService.get_authorization_matrix(user.tenant_id)
    return {"data": matrix.model_dump(), "meta": _meta()}


@v1_router.post("/tools/{tool_id}/kill")
async def emergency_kill_v1(
    tool_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Emergency kill switch — immediately disable a tool."""
    if not check_permission(user, "mcp", "admin"):
        raise HTTPException(status_code=403, detail="Admin permission required")
    result = await MCPSecurityService.emergency_kill_switch(user.tenant_id, user, tool_id)
    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="mcp.tool.kill",
        resource_type="mcp_tool",
        resource_id=UUID(int=0),
        details={"tool_id": tool_id, "killed": result.get("killed", False), "tenant_id": user.tenant_id},
    )
    return {"data": result, "meta": _meta()}


@v1_router.post("/tools/{tool_id}/version")
async def track_version_v1(
    tool_id: str,
    body: TrackVersionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Track a new tool version with compatibility check."""
    if not check_permission(user, "mcp", "update"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    diff = await MCPSecurityService.track_tool_version(user.tenant_id, tool_id, body.definition)
    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="mcp.tool.version",
        resource_type="mcp_tool",
        resource_id=UUID(int=0),
        details={
            "tool_id": tool_id,
            "new_version": diff.new_version,
            "breaking": diff.breaking_changes,
            "tenant_id": user.tenant_id,
        },
    )
    return {"data": diff.model_dump(), "meta": _meta()}
