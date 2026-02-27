"""SQLModel database models for Archon."""

from __future__ import annotations

from datetime import datetime
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
    description: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    definition: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="draft")
    owner_id: UUID = Field(foreign_key="users.id")
    tenant_id: str | None = Field(default=None, index=True)
    tags: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    steps: list[dict] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    tools: list[dict] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    llm_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    rag_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    mcp_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    security_policy: dict | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    input_schema: dict | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    output_schema: dict | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    graph_definition: dict | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
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
    output_data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    steps: list[dict] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    metrics: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
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
    change_log: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
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
    description: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    category: str = Field(index=True)
    definition: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    tags: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    is_featured: bool = Field(default=False)
    usage_count: int = Field(default=0)
    author_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AuditLog(SQLModel, table=True):
    """Immutable append-only audit trail with tamper-evident hash chain.

    Consolidated from audit_logs, enterprise_audit_events, and
    governance_audit_entries into a single authoritative table.
    """

    __tablename__ = "audit_logs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Tenant isolation (set by TenantMiddleware before this is written)
    tenant_id: str = Field(default="default", index=True)

    # Correlation tracking (set per-request by AuditMiddleware)
    correlation_id: str = Field(default="", index=True)

    # Actor — nullable for unauthenticated / system calls
    actor_id: UUID | None = Field(default=None, index=True)

    # Action semantics
    action: str
    resource_type: str | None = Field(default=None, index=True)
    resource_id: str | None = Field(default=None, index=True)

    # HTTP context
    status_code: int | None = Field(default=None)
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )

    # Rich detail payload (backwards-compatible)
    details: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # Tamper-evident SHA-256 hash chain
    hash: str = Field(default="", index=True)
    prev_hash: str = Field(default="genesis")

    created_at: datetime = Field(default_factory=_utcnow)


from app.models.router import (  # noqa: E402
    ModelRegistryEntry,
    ProviderHealthHistory,
    RoutingRule,
    VisualRoutingRuleDB,
    FallbackChainConfigDB,
)
from app.models.lifecycle import DeploymentRecord, HealthCheck, LifecycleEvent  # noqa: E402
from app.models.cost import (  # noqa: E402
    Budget,
    CostAlert,
    DepartmentBudget,
    ProviderPricing,
    TokenLedger,
)
from app.models.tenancy import BillingRecord, Tenant, TenantQuota, UsageMeteringRecord  # noqa: E402
from app.models.governance import (  # noqa: E402
    AgentRegistryEntry,
    AuditEntry,
    CompliancePolicy,
    ComplianceRecord,
)
from app.models.dlp import DLPDetectedEntity, DLPPolicy, DLPScanResult  # noqa: E402
from app.models.sentinelscan import (  # noqa: E402
    DiscoveredService,
    DiscoveryScan,
    RiskClassification,
    SentinelFinding,
    SentinelScanHistory,
)
from app.models.mcp_security import (  # noqa: E402
    MCPResponseValidation,
    MCPSandboxSession,
    MCPSecurityEvent,
    MCPToolAuthorization,
    MCPToolVersion,
)
from app.models.a2a import A2AAgentCard, A2AMessage, A2ATask  # noqa: E402
from app.models.mesh import FederationConfig, MeshMessage, MeshNode, TrustRelationship  # noqa: E402
from app.models.mcp import MCPComponent, MCPInteraction, MCPSession  # noqa: E402
from app.models.marketplace import (  # noqa: E402
    CreatorProfile,
    MarketplaceInstall,
    MarketplaceListing,
    MarketplaceReview,
)
from app.models.edge import EdgeDevice, EdgeModelDeployment, EdgeSyncRecord, FleetConfig  # noqa: E402
from app.models.docforge import (  # noqa: E402
    Collection,
    CollectionConfig,
    Document,
    DocumentChunk,
    DocumentPermission,
    DocumentSource,
    SearchHit,
    SearchResult,
)
from app.models.auth import APIKey, SAMLProvider, UserIdentity, UserRole  # noqa: E402
from app.models.secrets import SecretRegistration  # noqa: E402
from app.models.tenant_config import TenantConfiguration  # noqa: E402
from app.models.audit import EnterpriseAuditEvent  # noqa: E402
from app.models.redteam import (  # noqa: E402
    AttackCategory,
    ScanSummary,
    SecurityScanConfig,
    SecurityScanResult,
    Severity,
    VulnerabilityFinding,
)
from app.models.settings import FeatureFlag, PlatformSetting, SettingsAPIKey  # noqa: E402
from app.models.workflow import Workflow, WorkflowRun, WorkflowRunStep, WorkflowSchedule  # noqa: E402
from app.models.oauth import OAuthPendingState  # noqa: E402
from app.models.rbac import CustomRole  # noqa: E402
from app.models.custom_role import GroupRoleMapping  # noqa: E402
from app.models.scim_db import SCIMGroupRecord, SCIMUserRecord  # noqa: E402
from app.models.qa import QAWorkflowRequest  # noqa: E402
from app.models.improvement import ImprovementGap, ImprovementProposal  # noqa: E402
from app.models.mcp_container import MCPServerContainer  # noqa: E402


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
    "Budget",
    "Collection",
    "CollectionConfig",
    "CompliancePolicy",
    "ComplianceRecord",
    "Connector",
    "CostAlert",
    "CreatorProfile",
    "DLPDetectedEntity",
    "DLPPolicy",
    "DLPScanResult",
    "DepartmentBudget",
    "DeploymentRecord",
    "DiscoveredService",
    "DiscoveryScan",
    "Document",
    "DocumentChunk",
    "DocumentPermission",
    "DocumentSource",
    "EdgeDevice",
    "EdgeModelDeployment",
    "EdgeSyncRecord",
    "EnterpriseAuditEvent",
    "Execution",
    "FallbackChainConfigDB",
    "FederationConfig",
    "FeatureFlag",
    "FleetConfig",
    "HealthCheck",
    "LifecycleEvent",
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
    "OAuthPendingState",
    "PlatformSetting",
    "ProviderPricing",
    "ProviderHealthHistory",
    "RiskClassification",
    "RoutingRule",
    "SAMLProvider",
    "ScanSummary",
    "SearchHit",
    "SearchResult",
    "SecretRegistration",
    "SecurityScanConfig",
    "SecurityScanResult",
    "SentinelFinding",
    "SentinelScanHistory",
    "SettingsAPIKey",
    "Severity",
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
    "VisualRoutingRuleDB",
    "VulnerabilityFinding",
    "Workflow",
    "WorkflowRun",
    "WorkflowRunStep",
    "WorkflowSchedule",
    "CustomRole",
    "GroupRoleMapping",
    "SCIMGroupRecord",
    "SCIMUserRecord",
    "QAWorkflowRequest",
    "ImprovementGap",
    "ImprovementProposal",
    "MCPServerContainer",
]
