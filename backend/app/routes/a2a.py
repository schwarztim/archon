"""API routes for A2A (Agent-to-Agent) protocol support."""

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
from app.middleware.rbac import require_permission
from app.models.a2a import (
    A2AAgentCard,
    A2AFederationMessage,
    PartnerRegistration,
    TrustLevelUpdate,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.a2a import A2AClient, A2APublisher
from app.services.a2a_service import A2AService
from starlette.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/a2a", tags=["a2a"])


# ── Request / response schemas ──────────────────────────────────────


class AgentCardCreate(BaseModel):
    """Payload for creating/registering an A2A agent card."""

    name: str
    description: str | None = None
    url: str
    version: str = "1.0.0"
    capabilities: list[str] = PField(default_factory=list)
    skills: list[dict[str, Any]] = PField(default_factory=list)
    auth_schemes: list[str] = PField(default_factory=list)
    agent_id: UUID | None = None
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class AgentCardUpdate(BaseModel):
    """Payload for partial-updating an A2A agent card."""

    name: str | None = None
    description: str | None = None
    url: str | None = None
    version: str | None = None
    capabilities: list[str] | None = None
    skills: list[dict[str, Any]] | None = None
    auth_schemes: list[str] | None = None
    is_active: bool | None = None
    extra_metadata: dict[str, Any] | None = None


class TaskCreate(BaseModel):
    """Payload for creating an outbound A2A task."""

    agent_card_id: UUID
    input_data: dict[str, Any] = PField(default_factory=dict)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class TaskStatusUpdate(BaseModel):
    """Payload for updating task status."""

    status: str
    output_data: dict[str, Any] | None = None
    error: str | None = None


class MessageCreate(BaseModel):
    """Payload for sending a message within an A2A task."""

    role: str
    content: str
    parts: list[dict[str, Any]] = PField(default_factory=list)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class MessageSend(BaseModel):
    """Payload for sending an A2A federation message."""

    agent_id: str
    message: str
    metadata: dict[str, Any] = PField(default_factory=dict)


class InboundMessage(BaseModel):
    """Payload for receiving an A2A federation message (webhook)."""

    message_id: UUID
    sender_agent_id: UUID
    content: str
    metadata: dict[str, Any] = PField(default_factory=dict)
    timestamp: datetime


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Discovery (inbound agent cards) ────────────────────────────────


@router.get("/discover")
async def discover_agents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    capability: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List discovered external A2A agents."""
    cards, total = await A2AClient.discover_agents(
        session, capability=capability, is_active=is_active, limit=limit, offset=offset,
    )
    return {
        "data": [c.model_dump(mode="json") for c in cards],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/discover", status_code=201)
async def register_discovered_agent(
    body: AgentCardCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a discovered external A2A agent card."""
    card = A2AAgentCard(**body.model_dump())
    created = await A2AClient.register_agent_card(session, card)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/discover/{card_id}")
async def get_discovered_agent(
    card_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a discovered agent card by ID."""
    card = await A2AClient.get_agent_card(session, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Agent card not found")
    return {"data": card.model_dump(mode="json"), "meta": _meta()}


# ── Publishing (outbound agent cards) ──────────────────────────────


@router.get("/publish")
async def list_published_cards(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    is_active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List published Archon A2A agent cards."""
    cards, total = await A2APublisher.list_published(
        session, is_active=is_active, limit=limit, offset=offset,
    )
    return {
        "data": [c.model_dump(mode="json") for c in cards],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/publish", status_code=201)
async def publish_card(
    body: AgentCardCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Publish an Archon agent as an A2A service."""
    card = A2AAgentCard(**body.model_dump())
    published = await A2APublisher.publish_card(session, card)
    return {"data": published.model_dump(mode="json"), "meta": _meta()}


@router.get("/publish/{card_id}")
async def get_published_card(
    card_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a published agent card by ID."""
    card = await A2APublisher.get_card(session, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Published card not found")
    return {"data": card.model_dump(mode="json"), "meta": _meta()}


@router.put("/publish/{card_id}")
async def update_published_card(
    card_id: UUID,
    body: AgentCardUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a published agent card."""
    data = body.model_dump(exclude_unset=True)
    card = await A2APublisher.update_card(session, card_id, data)
    if card is None:
        raise HTTPException(status_code=404, detail="Published card not found")
    return {"data": card.model_dump(mode="json"), "meta": _meta()}


@router.delete("/publish/{card_id}", status_code=204, response_class=Response)
async def unpublish_card(
    card_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Unpublish (delete) an A2A agent card."""
    deleted = await A2APublisher.unpublish_card(session, card_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Published card not found")
    return Response(status_code=204)


# ── Tasks ───────────────────────────────────────────────────────────


@router.get("/tasks")
async def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    agent_card_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List A2A tasks with optional filters."""
    tasks, total = await A2AClient.list_tasks(
        session,
        agent_card_id=agent_card_id,
        status=status,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [t.model_dump(mode="json") for t in tasks],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/tasks", status_code=201)
async def create_task(
    body: TaskCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create an outbound A2A task."""
    task = await A2AClient.create_task(
        session,
        agent_card_id=body.agent_card_id,
        input_data=body.input_data,
        extra_metadata=body.extra_metadata,
    )
    return {"data": task.model_dump(mode="json"), "meta": _meta()}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get an A2A task by ID."""
    task = await A2AClient.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="A2A task not found")
    return {"data": task.model_dump(mode="json"), "meta": _meta()}


@router.put("/tasks/{task_id}/status")
async def update_task_status(
    task_id: UUID,
    body: TaskStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update the status of an A2A task."""
    task = await A2AClient.update_task_status(
        session,
        task_id,
        status=body.status,
        output_data=body.output_data,
        error=body.error,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="A2A task not found")
    return {"data": task.model_dump(mode="json"), "meta": _meta()}


# ── Messages ────────────────────────────────────────────────────────


@router.get("/tasks/{task_id}/messages")
async def list_messages(
    task_id: UUID,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List messages for an A2A task."""
    messages, total = await A2AClient.list_messages(
        session, task_id=task_id, limit=limit, offset=offset,
    )
    return {
        "data": [m.model_dump(mode="json") for m in messages],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/tasks/{task_id}/messages", status_code=201)
async def send_message(
    task_id: UUID,
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Send a message within an A2A task."""
    # Verify task exists
    task = await A2AClient.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="A2A task not found")
    message = await A2AClient.send_message(
        session,
        task_id=task_id,
        role=body.role,
        content=body.content,
        parts=body.parts,
        extra_metadata=body.extra_metadata,
    )
    return {"data": message.model_dump(mode="json"), "meta": _meta()}


# ── Well-Known ──────────────────────────────────────────────────────


@router.get("/well-known/{agent_id}")
async def get_well_known_card(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Serve the A2A agent card for a published Archon agent (well-known endpoint)."""
    card = await A2APublisher.get_well_known_card(session, agent_id)
    if card is None:
        raise HTTPException(status_code=404, detail="No published agent card found")
    return {"data": card.model_dump(mode="json"), "meta": _meta()}


# ── Enterprise Federation Routes ────────────────────────────────────

federation_router = APIRouter(prefix="/a2a", tags=["a2a-federation"])


@federation_router.post("/partners", status_code=status.HTTP_201_CREATED)
async def register_partner(
    body: PartnerRegistration,
    user: AuthenticatedUser = Depends(require_permission("a2a", "create")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Register a new A2A federation partner.

    Exchanges client credentials via Vault and establishes the partnership.
    Requires ``a2a:create`` permission.
    """
    request_id = str(uuid4())
    partner = await A2AService.register_partner(
        user.tenant_id, user, body, secrets,
    )
    return {
        "data": partner.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@federation_router.get("/partners")
async def list_partners(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_permission("a2a", "read")),
) -> dict[str, Any]:
    """List registered A2A federation partners for the tenant.

    Requires ``a2a:read`` permission. Results are scoped to the tenant.
    """
    request_id = str(uuid4())
    # In production: query partners table filtered by user.tenant_id
    return {
        "data": [],
        "meta": _meta(
            request_id=request_id,
            pagination={"total": 0, "limit": limit, "offset": offset},
        ),
    }


@federation_router.post("/partners/{partner_id}/trust")
async def set_trust_level(
    partner_id: UUID,
    body: TrustLevelUpdate,
    user: AuthenticatedUser = Depends(require_permission("a2a", "admin")),
) -> dict[str, Any]:
    """Set the trust level for a federation partner.

    Requires ``a2a:admin`` permission. Trust levels control allowed operations.
    """
    request_id = str(uuid4())
    partner = await A2AService.manage_trust_level(
        user.tenant_id, user, str(partner_id), body.trust_level,
    )
    return {
        "data": partner.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@federation_router.post("/agents/{agent_id}/publish", status_code=status.HTTP_201_CREATED)
async def publish_agent_card(
    agent_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("a2a", "create")),
) -> dict[str, Any]:
    """Publish an Archon agent as an A2A service with a JSON-LD agent card.

    Requires ``a2a:create`` permission.
    """
    request_id = str(uuid4())
    card = await A2AService.publish_agent_card(
        user.tenant_id, user, str(agent_id),
    )
    return {
        "data": card.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@federation_router.get("/partners/{partner_id}/agents")
async def discover_partner_agents(
    partner_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("a2a", "read")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Discover a partner's published A2A agents.

    Requires ``a2a:read`` permission. Acquires a token and queries the partner.
    """
    request_id = str(uuid4())
    cards = await A2AService.discover_agents(
        user.tenant_id, str(partner_id), secrets,
    )
    return {
        "data": [c.model_dump(mode="json") for c in cards],
        "meta": _meta(request_id=request_id),
    }


@federation_router.post("/partners/{partner_id}/message")
async def send_federation_message(
    partner_id: UUID,
    body: MessageSend,
    user: AuthenticatedUser = Depends(require_permission("a2a", "execute")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Send a message to a remote A2A agent with DLP scanning.

    Requires ``a2a:execute`` permission. Content is scanned by the DLP pipeline.
    """
    request_id = str(uuid4())
    response = await A2AService.send_message(
        user.tenant_id, user, str(partner_id), body.agent_id, body.message, secrets,
    )
    return {
        "data": response.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@federation_router.post("/receive")
async def receive_federation_message(
    body: InboundMessage,
    partner_id: str = Query(..., description="Partner ID from webhook header"),
    tenant_id: str = Query(..., description="Target tenant ID"),
) -> dict[str, Any]:
    """Receive an inbound A2A message (webhook endpoint).

    Validates the message and runs DLP scanning on inbound content.
    Authentication is via mTLS client certificate verification.
    """
    request_id = str(uuid4())
    msg = A2AFederationMessage(
        message_id=body.message_id,
        sender_agent_id=body.sender_agent_id,
        content=body.content,
        metadata=body.metadata,
        timestamp=body.timestamp,
    )
    response = await A2AService.receive_message(tenant_id, partner_id, msg)
    return {
        "data": response.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@federation_router.get("/status")
async def get_federation_status(
    user: AuthenticatedUser = Depends(require_permission("a2a", "read")),
) -> dict[str, Any]:
    """Get federation health and statistics for the tenant.

    Requires ``a2a:read`` permission.
    """
    request_id = str(uuid4())
    result = await A2AService.get_federation_status(user.tenant_id)
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }
