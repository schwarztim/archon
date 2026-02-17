"""Connector CRUD endpoints and Enterprise Connector Hub routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import require_auth
from app.middleware.rbac import require_permission
from app.models import Connector
from app.models.connector import (
    ConnectorConfig,
    ConnectorInstance,
    ConnectionTestResult,
    ConnectorType,
    OAuthCredential,
    OAuthFlowStart,
    ActionResult,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services import ConnectorService

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["connectors"])


# ── Request / response schemas ──────────────────────────────────────


class ConnectorCreate(BaseModel):
    """Payload for creating a connector."""

    name: str
    type: str
    config: dict[str, Any]
    status: str = "inactive"
    owner_id: UUID = UUID("00000000-0000-0000-0000-000000000001")


class ConnectorUpdate(BaseModel):
    """Payload for updating a connector (partial)."""

    name: str | None = None
    type: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None


class OAuthStartRequest(BaseModel):
    """Payload for starting an OAuth flow."""

    redirect_uri: str


class OAuthCallbackRequest(BaseModel):
    """Payload for completing an OAuth callback."""

    code: str
    state: str


class ExecuteActionRequest(BaseModel):
    """Payload for executing a connector action."""

    action: str
    params: dict[str, Any] = PField(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Legacy CRUD routes (existing) ───────────────────────────────────


@router.get("/")
async def list_connectors(
    owner_id: UUID | None = Query(default=None),
    connector_type: str | None = Query(default=None, alias="type"),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List connectors with pagination and optional filters."""
    connectors, total = await ConnectorService.list(
        session,
        owner_id=owner_id,
        connector_type=connector_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [c.model_dump(mode="json") for c in connectors],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.post("/", status_code=201)
async def create_connector(
    body: ConnectorCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new connector."""
    span_ctx = _tracer.start_as_current_span("create_connector") if _tracer else None
    try:
        if span_ctx:
            span_ctx.__enter__()
        connector = Connector(**body.model_dump())
        created = await ConnectorService.create(session, connector)
        return {
            "data": created.model_dump(mode="json"),
            "meta": _meta(),
        }
    finally:
        if span_ctx:
            span_ctx.__exit__(None, None, None)


@router.get("/{connector_id}")
async def get_connector(
    connector_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single connector by ID."""
    connector = await ConnectorService.get(session, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {
        "data": connector.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.put("/{connector_id}")
async def update_connector(
    connector_id: UUID,
    body: ConnectorUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an existing connector."""
    data = body.model_dump(exclude_unset=True)
    connector = await ConnectorService.update(session, connector_id, data)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {
        "data": connector.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a connector."""
    deleted = await ConnectorService.delete(session, connector_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Connector not found")


# ── Enterprise Connector Hub routes ─────────────────────────────────

enterprise = APIRouter(prefix="/api/v1/connectors", tags=["Enterprise Connectors"])


@enterprise.get("/types")
async def list_connector_types(
    user: AuthenticatedUser = Depends(require_permission("connectors", "read")),
) -> dict[str, Any]:
    """List available connector types from the platform catalog."""
    types = await ConnectorService.list_available_connector_types()
    return {
        "data": [t.model_dump(mode="json") for t in types],
        "meta": _meta(),
    }


@enterprise.post("", status_code=status.HTTP_201_CREATED)
async def register_connector(
    body: ConnectorConfig,
    user: AuthenticatedUser = Depends(require_permission("connectors", "create")),
) -> dict[str, Any]:
    """Register a new enterprise connector for the tenant."""
    instance = await ConnectorService.register_connector(
        tenant_id=user.tenant_id,
        user=user,
        config=body,
    )
    return {
        "data": instance.model_dump(mode="json"),
        "meta": _meta(),
    }


@enterprise.get("")
async def list_enterprise_connectors(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_permission("connectors", "read")),
) -> dict[str, Any]:
    """List enterprise connectors for the authenticated tenant."""
    all_conns = await ConnectorService.list_connectors(user.tenant_id)
    total = len(all_conns)
    page = all_conns[offset : offset + limit]
    return {
        "data": [c.model_dump(mode="json") for c in page],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@enterprise.get("/{connector_id}")
async def get_enterprise_connector(
    connector_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("connectors", "read")),
) -> dict[str, Any]:
    """Get an enterprise connector by ID, scoped to tenant."""
    try:
        instance = await ConnectorService.get_connector(user.tenant_id, connector_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {
        "data": instance.model_dump(mode="json"),
        "meta": _meta(),
    }


@enterprise.post("/{connector_id}/oauth/start")
async def start_oauth_flow(
    connector_id: UUID,
    body: OAuthStartRequest,
    user: AuthenticatedUser = Depends(require_permission("connectors", "create")),
) -> dict[str, Any]:
    """Initiate OAuth 2.0 authorization code flow for a connector."""
    try:
        flow = await ConnectorService.start_oauth_flow(
            tenant_id=user.tenant_id,
            user=user,
            connector_id=connector_id,
            redirect_uri=body.redirect_uri,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "data": flow.model_dump(mode="json"),
        "meta": _meta(),
    }


@enterprise.post("/oauth/callback")
async def oauth_callback(
    body: OAuthCallbackRequest,
    user: AuthenticatedUser = Depends(require_auth),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Complete OAuth callback: exchange code for tokens, store in Vault."""
    try:
        credential = await ConnectorService.complete_oauth_flow(
            tenant_id=user.tenant_id,
            code=body.code,
            state=body.state,
            secrets_mgr=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "data": credential.model_dump(mode="json"),
        "meta": _meta(),
    }


@enterprise.post("/{connector_id}/test")
async def test_connection(
    connector_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("connectors", "read")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Test a connector's health by verifying Vault credentials."""
    try:
        result = await ConnectorService.test_connection(
            tenant_id=user.tenant_id,
            connector_id=connector_id,
            secrets_mgr=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


@enterprise.post("/{connector_id}/execute")
async def execute_action(
    connector_id: UUID,
    body: ExecuteActionRequest,
    user: AuthenticatedUser = Depends(require_permission("connectors", "execute")),
) -> dict[str, Any]:
    """Execute a CRUD action through a connector."""
    try:
        result = await ConnectorService.execute_action(
            tenant_id=user.tenant_id,
            user=user,
            connector_id=connector_id,
            action=body.action,
            params=body.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


@enterprise.post("/{connector_id}/refresh")
async def refresh_credentials(
    connector_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("connectors", "update")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Refresh OAuth credentials for a connector via Vault."""
    try:
        success = await ConnectorService.refresh_credentials(
            tenant_id=user.tenant_id,
            connector_id=connector_id,
            secrets_mgr=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "data": {"refreshed": success},
        "meta": _meta(),
    }


@enterprise.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connector(
    connector_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("connectors", "delete")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> None:
    """Revoke connector OAuth tokens, remove from Vault, and delete."""
    try:
        await ConnectorService.revoke_connector(
            tenant_id=user.tenant_id,
            user=user,
            connector_id=connector_id,
            secrets_mgr=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
