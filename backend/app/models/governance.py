"""SQLModel database models for Archon governance engine."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
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


class CompliancePolicy(SQLModel, table=True):
    """Governance policy defining compliance rules for agents."""

    __tablename__ = "compliance_policies"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    framework: str = Field(index=True)  # SOC2 | GDPR | HIPAA | custom
    version: int = Field(default=1)
    status: str = Field(default="draft")  # draft | active | archived
    severity: str = Field(default="medium")  # low | medium | high | critical
    rules: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    enforcement_action: str = Field(default="warn")  # warn | block | log
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ComplianceRecord(SQLModel, table=True):
    """Record of a compliance check against an agent."""

    __tablename__ = "compliance_records"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(index=True, foreign_key="agents.id")
    policy_id: UUID = Field(index=True, foreign_key="compliance_policies.id")
    status: str = Field(default="pending")  # compliant | non_compliant | pending | exempted
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    checked_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = Field(default=None)


class AuditEntry(SQLModel, table=True):
    """Tamper-evident audit log entry for governance actions."""

    __tablename__ = "governance_audit_entries"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    actor_id: UUID | None = Field(default=None, foreign_key="users.id")
    agent_id: UUID | None = Field(default=None, index=True, foreign_key="agents.id")
    action: str = Field(index=True)
    resource_type: str = Field(index=True)
    resource_id: UUID | None = Field(default=None)
    outcome: str = Field(default="success")  # success | failure | denied
    details: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    # Hash chain for tamper detection
    previous_hash: str | None = Field(default=None)
    entry_hash: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class AgentRegistryEntry(SQLModel, table=True):
    """Central registry entry for an agent with governance metadata."""

    __tablename__ = "governance_agent_registry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(index=True, unique=True, foreign_key="agents.id")
    owner: str = Field(index=True)
    department: str = Field(index=True)
    approval_status: str = Field(default="draft")  # draft | review | approved | published | deprecated
    models_used: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    data_accessed: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    risk_level: str = Field(default="low")  # low | medium | high | critical
    sunset_date: datetime | None = Field(default=None)
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False)
    )
    registered_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ApprovalRequest(SQLModel, table=True):
    """Approval request for agent production promotion."""

    __tablename__ = "governance_approval_requests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(index=True, foreign_key="agents.id")
    requester_id: UUID | None = Field(default=None, foreign_key="users.id")
    requester_name: str = Field(default="")
    agent_name: str = Field(default="")
    action: str = Field(default="promote_to_production")
    status: str = Field(default="pending")  # pending | approved | rejected
    approval_rule: str = Field(default="any_one")  # any_one | all | majority
    reviewers: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    decisions: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    comment: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


def compute_entry_hash(entry_data: str, previous_hash: str | None = None) -> str:
    """Compute SHA-256 hash for audit entry chain integrity."""
    payload = f"{previous_hash or ''}{entry_data}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ── Pydantic response / request models (non-table) ──────────────────


class RiskFactor(BaseModel):
    """Single factor contributing to an agent's risk score."""

    name: str
    weight: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=100.0)
    description: str = ""


class RiskAssessment(BaseModel):
    """Composite risk assessment for an agent."""

    agent_id: UUID
    overall_score: float = Field(ge=0.0, le=100.0)
    risk_level: str = "low"
    factors: list[RiskFactor] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=_utcnow)


class ControlStatus(BaseModel):
    """Status of a single compliance control."""

    control_id: str
    name: str
    status: str = "unknown"  # passing | failing | not_applicable | unknown
    evidence: str = ""


class ComplianceStatus(BaseModel):
    """Aggregate compliance status for a framework."""

    framework: str
    overall_status: str = "unknown"  # compliant | non_compliant | partial | unknown
    controls: list[ControlStatus] = Field(default_factory=list)
    last_assessed: datetime = Field(default_factory=_utcnow)


class ReviewDecision(BaseModel):
    """Single decision within an access review."""

    user_id: str
    resource: str
    decision: str  # approve | revoke | modify
    notes: str = ""


class AccessReview(BaseModel):
    """Periodic access review record."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    review_cycle: str = ""
    reviewer_id: str = ""
    reviewee_id: str = ""
    status: str = "pending"  # pending | in_progress | completed | cancelled
    decisions: list[ReviewDecision] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None


class ElevationRequest(BaseModel):
    """JIT privilege elevation request."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    user_id: str
    requested_role: str
    justification: str = ""
    duration_hours: int = 1
    status: str = "pending"  # pending | approved | denied | expired
    approved_by: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None


class ApprovalStage(BaseModel):
    """A single stage in a multi-stage approval workflow."""

    stage_number: int
    approver_role: str
    status: str = "pending"  # pending | approved | rejected
    decided_by: str | None = None
    decided_at: datetime | None = None


class ApprovalWorkflow(BaseModel):
    """Multi-stage approval workflow for agent operations."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    agent_id: UUID
    workflow_type: str = ""
    stages: list[ApprovalStage] = Field(default_factory=list)
    current_stage: int = 0
    status: str = "pending"  # pending | approved | rejected | cancelled
    created_by: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class OPAPolicy(BaseModel):
    """OPA (Open Policy Agent) policy definition."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    name: str
    rego_content: str = ""
    description: str = ""
    active: bool = True
    last_tested: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class GovernanceReport(BaseModel):
    """Executive governance report metadata."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    report_type: str = ""
    period: str = ""
    generated_by: str = ""
    format: str = "json"
    download_url: str = ""
    created_at: datetime = Field(default_factory=_utcnow)



__all__ = [
    "AccessReview",
    "AgentRegistryEntry",
    "ApprovalRequest",
    "ApprovalStage",
    "ApprovalWorkflow",
    "AuditEntry",
    "CompliancePolicy",
    "ComplianceRecord",
    "ComplianceStatus",
    "ControlStatus",
    "ElevationRequest",
    "GovernanceReport",
    "OPAPolicy",
    "ReviewDecision",
    "RiskAssessment",
    "RiskFactor",
    "compute_entry_hash",
]
