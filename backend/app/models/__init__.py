"""SQLModel database models for Archon."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class User(SQLModel, table=True):
    """Registered platform user."""

    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str
    role: str = Field(default="developer")
    tenant_id: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Agent(SQLModel, table=True):
    """AI agent definition stored in the platform."""

    __tablename__ = "agents"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    description: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    definition: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="draft")
    owner_id: UUID = Field(foreign_key="users.id")
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    steps: list[dict] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    tools: list[dict] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    llm_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    rag_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    mcp_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    security_policy: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    input_schema: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    output_schema: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    graph_definition: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    group_id: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Execution(SQLModel, table=True):
    """Record of an agent execution run."""

    __tablename__ = "executions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id")
    status: str = Field(default="queued")
    input_data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    output_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    steps: list[dict] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    metrics: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AgentVersion(SQLModel, table=True):
    """Immutable snapshot of an agent definition at a point in time."""

    __tablename__ = "agent_versions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id")
    version: str
    definition: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    change_log: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    created_by: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)


class Model(SQLModel, table=True):
    """Registered LLM provider and configuration."""

    __tablename__ = "models"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    provider: str
    model_id: str
    config: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Connector(SQLModel, table=True):
    """External integration / data source configuration."""

    __tablename__ = "connectors"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    type: str
    config: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="inactive")
    owner_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Template(SQLModel, table=True):
    """Pre-built agent template that users can browse and instantiate."""

    __tablename__ = "templates"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    category: str = Field(index=True)
    definition: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_featured: bool = Field(default=False)
    usage_count: int = Field(default=0)
    author_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AuditLog(SQLModel, table=True):
    """Immutable append-only audit trail for platform actions."""

    __tablename__ = "audit_logs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    actor_id: UUID = Field(foreign_key="users.id")
    action: str
    resource_type: str
    resource_id: UUID
    details: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow)


from app.models.router import ModelRegistryEntry, RoutingRule
from app.models.lifecycle import DeploymentRecord, HealthCheck, LifecycleEvent
from app.models.cost import Budget, CostAlert, ProviderPricing, TokenLedger
from app.models.tenancy import BillingRecord, Tenant, TenantQuota, UsageMeteringRecord
from app.models.governance import AgentRegistryEntry, AuditEntry, CompliancePolicy, ComplianceRecord
from app.models.dlp import DLPDetectedEntity, DLPPolicy, DLPScanResult
from app.models.sentinelscan import DiscoveredService, DiscoveryScan, RiskClassification
from app.models.mcp_security import (
    MCPResponseValidation,
    MCPSandboxSession,
    MCPSecurityEvent,
    MCPToolAuthorization,
    MCPToolVersion,
)
from app.models.a2a import A2AAgentCard, A2AMessage, A2ATask
from app.models.mesh import FederationConfig, MeshMessage, MeshNode, TrustRelationship
from app.models.mcp import MCPComponent, MCPInteraction, MCPSession
from app.models.marketplace import (
    CreatorProfile,
    MarketplaceInstall,
    MarketplaceListing,
    MarketplaceReview,
)
from app.models.edge import EdgeDevice, EdgeModelDeployment, EdgeSyncRecord, FleetConfig
from app.models.docforge import (
    Collection,
    CollectionConfig,
    Document,
    DocumentChunk,
    DocumentPermission,
    DocumentSource,
    SearchHit,
    SearchResult,
)
from app.models.auth import APIKey, SAMLProvider, UserIdentity, UserRole
from app.models.secrets import SecretRegistration
from app.models.tenant_config import TenantConfiguration
from app.models.audit import EnterpriseAuditEvent
from app.models.redteam import (
    AttackCategory,
    ScanSummary,
    SecurityScanConfig,
    SecurityScanResult,
    Severity,
    VulnerabilityFinding,
)
from app.models.settings import FeatureFlag, PlatformSetting, SettingsAPIKey


__all__ = [
    "A2AAgentCard",
    "A2AMessage",
    "A2ATask",
    "APIKey",
    "Agent",
    "AgentVersion",
    "AgentRegistryEntry",
    "AttackCategory",
    "AuditEntry",
    "AuditLog",
    "BillingRecord",
    "CompliancePolicy",
    "ComplianceRecord",
    "Budget",
    "Connector",
    "Collection",
    "CollectionConfig",
    "CostAlert",
    "CreatorProfile",
    "DLPDetectedEntity",
    "DLPPolicy",
    "DLPScanResult",
    "DeploymentRecord",
    "Document",
    "DocumentChunk",
    "DocumentPermission",
    "DocumentSource",
    "EdgeDevice",
    "EdgeModelDeployment",
    "EdgeSyncRecord",
    "DiscoveredService",
    "DiscoveryScan",
    "Execution",
    "EnterpriseAuditEvent",
    "FleetConfig",
    "HealthCheck",
    "LifecycleEvent",
    "FederationConfig",
    "MCPComponent",
    "MCPInteraction",
    "MCPResponseValidation",
    "MCPSandboxSession",
    "MCPSecurityEvent",
    "MCPSession",
    "MCPToolAuthorization",
    "MCPToolVersion",
    "MarketplaceInstall",
    "MarketplaceListing",
    "MarketplaceReview",
    "MeshMessage",
    "MeshNode",
    "Model",
    "ModelRegistryEntry",
    "ProviderPricing",
    "RiskClassification",
    "RoutingRule",
    "ScanSummary",
    "SecurityScanConfig",
    "SecurityScanResult",
    "SearchHit",
    "SearchResult",
    "Severity",
    "SAMLProvider",
    "SecretRegistration",
    "Template",
    "Tenant",
    "TenantConfiguration",
    "TenantQuota",
    "TokenLedger",
    "TrustRelationship",
    "UsageMeteringRecord",
    "User",
    "UserIdentity",
    "UserRole",
    "VulnerabilityFinding",
    "FeatureFlag",
    "PlatformSetting",
    "SettingsAPIKey",
]
