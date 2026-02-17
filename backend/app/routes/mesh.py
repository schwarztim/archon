"""API routes for the Federated Agent Mesh gateway."""

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
from app.models.mesh import (
    OrgRegistration,
    TrustLevel,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.mesh import MeshGateway
from app.services.mesh_service import MeshService

router = APIRouter(prefix="/mesh", tags=["mesh"])


# ── Request / response schemas ──────────────────────────────────────


class NodeCreate(BaseModel):
    """Payload for registering a mesh node."""

    name: str
    organization: str
    endpoint_url: str
    public_key: str
    capabilities: list[str] = PField(default_factory=list)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class TrustCreate(BaseModel):
    """Payload for establishing trust between nodes."""

    requesting_node_id: UUID
    target_node_id: UUID
    trust_level: str = "standard"
    allowed_data_categories: list[str] = PField(default_factory=list)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class MessageCreate(BaseModel):
    """Payload for sending a message through the mesh."""

    source_node_id: UUID
    target_node_id: UUID
    content: str
    message_type: str = "request"
    data_category: str | None = None
    correlation_id: UUID | None = None
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class FederationCreate(BaseModel):
    """Payload for creating a federation agreement."""

    partner_org_id: UUID
    terms: dict[str, Any] = PField(default_factory=dict)


class AgentShareRequest(BaseModel):
    """Payload for sharing an agent to the mesh."""

    visibility: str = "private"
    data_classification: str = "internal"
    allowed_orgs: list[UUID] = PField(default_factory=list)


class RemoteInvokeRequest(BaseModel):
    """Payload for invoking a remote mesh agent."""

    mesh_agent_id: UUID
    input_data: dict[str, Any] = PField(default_factory=dict)


class TrustLevelUpdate(BaseModel):
    """Payload for updating a partner trust level."""

    partner_id: UUID
    level: TrustLevel


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Node endpoints ──────────────────────────────────────────────────


@router.post("/nodes", status_code=201)
async def register_node(
    body: NodeCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a new organization node in the mesh."""
    node = await MeshGateway.register_node(
        session,
        name=body.name,
        organization=body.organization,
        endpoint_url=body.endpoint_url,
        public_key=body.public_key,
        capabilities=body.capabilities,
        extra_metadata=body.extra_metadata,
    )
    return {"data": node.model_dump(mode="json"), "meta": _meta()}


@router.get("/nodes")
async def list_peers(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    organization: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List mesh peer nodes with optional filters."""
    nodes, total = await MeshGateway.list_peers(
        session, status=status, organization=organization, limit=limit, offset=offset,
    )
    return {
        "data": [n.model_dump(mode="json") for n in nodes],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/nodes/{node_id}")
async def get_node(
    node_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a mesh node by ID."""
    node = await MeshGateway.get_node(session, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Mesh node not found")
    return {"data": node.model_dump(mode="json"), "meta": _meta()}


# ── Trust endpoints ─────────────────────────────────────────────────


@router.post("/trust", status_code=201)
async def establish_trust(
    body: TrustCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Establish a trust relationship between two mesh nodes."""
    try:
        trust = await MeshGateway.establish_trust(
            session,
            requesting_node_id=body.requesting_node_id,
            target_node_id=body.target_node_id,
            trust_level=body.trust_level,
            allowed_data_categories=body.allowed_data_categories,
            extra_metadata=body.extra_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": trust.model_dump(mode="json"), "meta": _meta()}


@router.get("/trust")
async def list_trust_relationships(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    node_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List trust relationships with optional filters."""
    relationships, total = await MeshGateway.list_trust_relationships(
        session, node_id=node_id, status=status, limit=limit, offset=offset,
    )
    return {
        "data": [r.model_dump(mode="json") for r in relationships],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/trust/{trust_id}")
async def get_trust(
    trust_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a trust relationship by ID."""
    trust = await MeshGateway.get_trust(session, trust_id)
    if trust is None:
        raise HTTPException(status_code=404, detail="Trust relationship not found")
    return {"data": trust.model_dump(mode="json"), "meta": _meta()}


@router.delete("/trust/{trust_id}", status_code=200)
async def revoke_trust(
    trust_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Revoke (kill-switch) a trust relationship immediately."""
    trust = await MeshGateway.revoke_trust(session, trust_id)
    if trust is None:
        raise HTTPException(status_code=404, detail="Trust relationship not found")
    return {"data": trust.model_dump(mode="json"), "meta": _meta()}


# ── Message endpoints ───────────────────────────────────────────────


@router.post("/messages", status_code=201)
async def send_message(
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Send a message through the mesh gateway."""
    try:
        message = await MeshGateway.send_message(
            session,
            source_node_id=body.source_node_id,
            target_node_id=body.target_node_id,
            content=body.content,
            message_type=body.message_type,
            data_category=body.data_category,
            correlation_id=body.correlation_id,
            extra_metadata=body.extra_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"data": message.model_dump(mode="json"), "meta": _meta()}


@router.get("/messages")
async def list_messages(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    node_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    data_category: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List mesh messages with optional filters."""
    messages, total = await MeshGateway.list_messages(
        session, node_id=node_id, status=status, data_category=data_category,
        limit=limit, offset=offset,
    )
    return {
        "data": [m.model_dump(mode="json") for m in messages],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/messages/{message_id}")
async def get_message(
    message_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a mesh message by ID."""
    message = await MeshGateway.get_message(session, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Mesh message not found")
    return {"data": message.model_dump(mode="json"), "meta": _meta()}


# ── Enterprise Federation Endpoints ─────────────────────────────────


@router.post("/organizations", status_code=201)
async def register_organization(
    body: OrgRegistration,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Register an organization in the federated mesh."""
    svc = MeshService(secrets_manager=secrets)
    org = await svc.register_organization(user.tenant_id, user, body, session)
    return {"data": org.model_dump(mode="json"), "meta": _meta()}


@router.post("/federations", status_code=201)
async def create_federation(
    body: FederationCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Create a federation agreement with a partner organization."""
    svc = MeshService(secrets_manager=secrets)
    try:
        agreement = await svc.create_federation_agreement(
            user.tenant_id, user, body.partner_org_id, body.terms, session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": agreement.model_dump(mode="json"), "meta": _meta()}


@router.post("/federations/{agreement_id}/accept", status_code=200)
async def accept_federation(
    agreement_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Accept a pending federation agreement."""
    svc = MeshService(secrets_manager=secrets)
    try:
        agreement = await svc.accept_federation(user.tenant_id, user, agreement_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": agreement.model_dump(mode="json"), "meta": _meta()}


@router.post("/agents/{agent_id}/share", status_code=201)
async def share_agent(
    agent_id: UUID,
    body: AgentShareRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Share an agent to the federated mesh."""
    svc = MeshService(secrets_manager=secrets)
    shared = await svc.share_agent(
        user.tenant_id, user, agent_id,
        {"visibility": body.visibility, "data_classification": body.data_classification, "allowed_orgs": [str(o) for o in body.allowed_orgs]},
        session,
    )
    return {"data": shared.model_dump(mode="json"), "meta": _meta()}


@router.get("/discover")
async def discover_mesh_agents(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Discover agents shared by federated partners."""
    svc = MeshService(secrets_manager=secrets)
    agents = await svc.discover_mesh_agents(user.tenant_id, user, session)
    return {"data": [a.model_dump(mode="json") for a in agents], "meta": _meta()}


@router.post("/invoke", status_code=200)
async def invoke_remote_agent(
    body: RemoteInvokeRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Invoke a remote agent across organizational boundaries."""
    svc = MeshService(secrets_manager=secrets)
    result = await svc.invoke_remote_agent(
        user.tenant_id, user, body.mesh_agent_id, body.input_data, session,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/topology")
async def get_mesh_topology(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Get the current mesh network topology."""
    svc = MeshService(secrets_manager=secrets)
    topology = await svc.get_mesh_topology(user.tenant_id, session)
    return {"data": topology.model_dump(mode="json"), "meta": _meta()}


@router.get("/compliance/{partner_id}")
async def get_compliance_report(
    partner_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Get a GDPR compliance report for a federated partner."""
    check_permission(user, "mesh", "read")
    svc = MeshService(secrets_manager=secrets)
    report = await svc.get_compliance_report(user.tenant_id, partner_id, session)
    return {"data": report.model_dump(mode="json"), "meta": _meta()}
