"""SQLModel database models and Pydantic schemas for the Federated Agent Mesh."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# ── SQLModel ORM tables (existing) ─────────────────────────────────


class MeshNode(SQLModel, table=True):
    """A participating organization/node in the federated agent mesh."""

    __tablename__ = "mesh_nodes"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    organization: str = Field(index=True)
    endpoint_url: str
    public_key: str = Field(sa_column=Column(SAText, nullable=False))
    status: str = Field(default="pending", index=True)  # pending | active | suspended | revoked
    capabilities: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    last_seen_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class TrustRelationship(SQLModel, table=True):
    """Mutual trust link between two mesh nodes."""

    __tablename__ = "mesh_trust_relationships"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    requesting_node_id: UUID = Field(index=True, foreign_key="mesh_nodes.id")
    target_node_id: UUID = Field(index=True, foreign_key="mesh_nodes.id")
    status: str = Field(default="pending", index=True)  # pending | active | revoked
    trust_level: str = Field(default="standard")  # standard | elevated | full
    allowed_data_categories: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    established_at: datetime | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MeshMessage(SQLModel, table=True):
    """A message routed through the mesh gateway between nodes."""

    __tablename__ = "mesh_messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_node_id: UUID = Field(index=True, foreign_key="mesh_nodes.id")
    target_node_id: UUID = Field(index=True, foreign_key="mesh_nodes.id")
    message_type: str = Field(default="request")  # request | response | event
    content: str = Field(sa_column=Column(SAText, nullable=False))
    data_category: str | None = Field(default=None, index=True)
    is_encrypted: bool = Field(default=True)
    status: str = Field(default="pending", index=True)  # pending | delivered | failed | blocked
    correlation_id: UUID | None = Field(default=None, index=True)
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    delivered_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class FederationConfig(SQLModel, table=True):
    """Federation agreement and configuration between organizations."""

    __tablename__ = "mesh_federation_configs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    node_id: UUID = Field(index=True, foreign_key="mesh_nodes.id")
    policy_type: str = Field(default="sharing")  # sharing | rate_limit | compliance
    rules: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    is_active: bool = Field(default=True)
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic schemas (enterprise federation) ───────────────────────


class TrustLevel(str, Enum):
    """Trust level between federated organizations."""

    UNTRUSTED = "untrusted"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    FEDERATED = "federated"


class OrgRegistration(BaseModel):
    """Request payload for registering an organization in the mesh."""

    name: str
    domain: str
    public_key: str
    token_endpoint: str = ""
    metadata_url: str = ""
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class MeshOrganization(BaseModel):
    """Representation of a registered mesh organization."""

    id: UUID
    name: str
    domain: str
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    status: str = "active"
    joined_at: datetime


class FederationAgreement(BaseModel):
    """Federation trust agreement between two organizations."""

    id: UUID
    requester_org: UUID
    partner_org: UUID
    terms: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # pending | active | rejected | revoked
    created_at: datetime
    expires_at: datetime | None = None


class SharedAgent(BaseModel):
    """An agent published to the mesh for cross-org consumption."""

    agent_id: UUID
    sharing_policy: str = "private"  # private | shared | public
    data_classification: str = "internal"
    allowed_orgs: list[UUID] = Field(default_factory=list)


class MeshAgent(BaseModel):
    """A discoverable agent exposed by a federated partner."""

    id: UUID
    org_id: UUID
    name: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    data_classification: str = "internal"


class MeshInvocationResult(BaseModel):
    """Result of invoking a remote agent across the mesh."""

    invocation_id: UUID
    agent_id: UUID
    result: dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: int = 0
    dlp_findings: list[dict[str, Any]] = Field(default_factory=list)


class FederatedUser(BaseModel):
    """Identity resolved from a cross-org SAML/OIDC assertion."""

    org_id: UUID
    subject: str
    email: str
    roles_at_source: list[str] = Field(default_factory=list)
    mapped_permissions: list[str] = Field(default_factory=list)


class MeshTopologyNode(BaseModel):
    """A single node in the mesh topology view."""

    id: UUID
    name: str
    status: str


class MeshTopologyEdge(BaseModel):
    """An edge (trust relationship) in the mesh topology."""

    source: UUID
    target: UUID
    trust_level: str


class MeshTopology(BaseModel):
    """Current mesh network topology snapshot."""

    type: str = "hybrid"  # peer-to-peer | hub-spoke | hybrid
    nodes: list[MeshTopologyNode] = Field(default_factory=list)
    edges: list[MeshTopologyEdge] = Field(default_factory=list)
    statistics: dict[str, Any] = Field(default_factory=dict)


class TrustUpdate(BaseModel):
    """Result of a trust-level management operation."""

    partner_id: UUID
    previous_level: TrustLevel
    new_level: TrustLevel
    updated_at: datetime


class DataFlowRecord(BaseModel):
    """Record of cross-org data movement for compliance tracking."""

    flow_id: UUID
    source_org: UUID
    target_org: UUID
    data_classification: str
    timestamp: datetime


class ComplianceReport(BaseModel):
    """Cross-org data flow compliance report for GDPR."""

    partner_id: UUID
    data_flows: list[DataFlowRecord] = Field(default_factory=list)
    gdpr_compliant: bool = True
    dpa_status: str = "not_required"  # not_required | pending | signed | expired


__all__ = [
    "ComplianceReport",
    "DataFlowRecord",
    "FederatedUser",
    "FederationAgreement",
    "FederationConfig",
    "MeshAgent",
    "MeshInvocationResult",
    "MeshMessage",
    "MeshNode",
    "MeshOrganization",
    "MeshTopology",
    "MeshTopologyEdge",
    "MeshTopologyNode",
    "OrgRegistration",
    "SharedAgent",
    "TrustLevel",
    "TrustRelationship",
    "TrustUpdate",
]
