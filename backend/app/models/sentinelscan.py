"""SQLModel database models for Archon SentinelScan — shadow AI discovery and posture management."""

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


class DiscoveryScan(SQLModel, table=True):
    """A scheduled or ad-hoc discovery scan for shadow AI services."""

    __tablename__ = "sentinelscan_discovery_scans"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    scan_type: str = Field(
        index=True
    )  # sso | network | api_gateway | saas | browser | custom
    status: str = Field(
        default="pending"
    )  # pending | running | completed | failed | cancelled
    config: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    results_summary: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    services_found: int = Field(default=0)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    error_message: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    initiated_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class DiscoveredService(SQLModel, table=True):
    """An AI service discovered by a SentinelScan scan."""

    __tablename__ = "sentinelscan_discovered_services"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    scan_id: UUID = Field(index=True, foreign_key="sentinelscan_discovery_scans.id")
    service_name: str = Field(index=True)
    service_type: str = Field(
        index=True
    )  # llm | copilot | chatbot | image_gen | custom_model | saas_ai
    provider: str = Field(
        index=True
    )  # openai | anthropic | google | microsoft | cohere | custom
    detection_source: str  # sso_log | network_traffic | api_gateway | saas_integration | browser_telemetry
    department: str | None = Field(default=None, index=True)
    owner: str | None = Field(default=None)
    user_count: int = Field(default=0)
    data_sensitivity: str = Field(
        default="unknown"
    )  # public | internal | confidential | restricted | unknown
    is_sanctioned: bool = Field(default=False)
    first_seen: datetime = Field(default_factory=_utcnow)
    last_seen: datetime = Field(default_factory=_utcnow)
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class RiskClassification(SQLModel, table=True):
    """Risk classification for a discovered AI service."""

    __tablename__ = "sentinelscan_risk_classifications"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    service_id: UUID = Field(
        index=True, unique=True, foreign_key="sentinelscan_discovered_services.id"
    )
    risk_tier: str = Field(index=True)  # critical | high | medium | low | informational
    risk_score: int = Field(default=0)  # 0-100
    factors: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    data_sensitivity_score: int = Field(default=0)
    blast_radius_score: int = Field(default=0)
    compliance_score: int = Field(default=0)
    model_capability_score: int = Field(default=0)
    policy_violations: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    recommended_actions: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    classified_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SentinelFinding(SQLModel, table=True):
    """A security finding produced by a SentinelScan scan."""

    __tablename__ = "sentinelscan_findings"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    scan_id: UUID = Field(index=True, foreign_key="sentinelscan_discovery_scans.id")
    service_id: UUID | None = Field(
        default=None,
        index=True,
        foreign_key="sentinelscan_discovered_services.id",
    )
    finding_type: str = Field(
        index=True
    )  # shadow_ai | policy_violation | credential_exposure | data_risk
    severity: str = Field(
        default="medium"
    )  # critical | high | medium | low | informational
    title: str
    description: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    remediation: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    status: str = Field(default="open")  # open | in_progress | resolved | suppressed
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SentinelScanHistory(SQLModel, table=True):
    """Historical record of a completed SentinelScan run."""

    __tablename__ = "sentinelscan_history"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    scan_id: UUID = Field(index=True, foreign_key="sentinelscan_discovery_scans.id")
    tenant_id: UUID = Field(index=True)
    scan_type: str = Field(index=True)
    services_found: int = Field(default=0)
    findings_count: int = Field(default=0)
    shadow_count: int = Field(default=0)
    risk_score: int = Field(default=0, ge=0, le=100)
    duration_seconds: float = Field(default=0.0)
    completed_at: datetime = Field(default_factory=_utcnow)
    created_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic API schema models (non-table) ──────────────────────────

from pydantic import BaseModel, Field as PField


class DiscoveryConfig(BaseModel):
    """Configuration for a shadow AI discovery scan."""

    sources: list[str] = PField(default_factory=lambda: ["sso"])
    scan_depth: str = "standard"  # quick | standard | deep
    include_network_logs: bool = False
    time_range_days: int = 30


class DiscoveryResult(BaseModel):
    """Result of a shadow AI discovery scan."""

    id: UUID
    tenant_id: UUID
    discovered_services: list[dict[str, Any]] = PField(default_factory=list)
    shadow_count: int = 0
    approved_count: int = 0
    blocked_count: int = 0
    new_since_last_scan: int = 0
    scan_duration_seconds: float = 0.0
    completed_at: datetime | None = None


class AIAsset(BaseModel):
    """Unified AI asset in the tenant inventory."""

    id: UUID
    tenant_id: UUID
    service_name: str
    category: str  # llm | copilot | chatbot | image_gen | code_assistant | saas_ai
    status: str  # approved | shadow | blocked | under_review
    users: list[str] = PField(default_factory=list)
    user_count: int = 0
    department: str | None = None
    first_seen: datetime
    last_seen: datetime
    risk_level: str = "medium"  # critical | high | medium | low | informational
    data_classification: str = "unknown"


class CredentialExposure(BaseModel):
    """A detected credential exposure in repos or logs."""

    id: UUID
    tenant_id: UUID
    credential_type: (
        str  # api_key | oauth_token | service_account | personal_access_token
    )
    location: str  # repo path, log file, etc.
    service_name: str | None = None
    severity: str  # critical | high | medium | low
    detected_at: datetime
    remediated: bool = False
    remediated_at: datetime | None = None


class PostureScore(BaseModel):
    """Organization-wide AI security posture score."""

    tenant_id: UUID
    overall: int = PField(ge=0, le=100)
    categories: dict[str, int] = PField(default_factory=dict)
    trend: str = "stable"  # improving | stable | declining
    benchmark_percentile: int = PField(default=50, ge=0, le=100)
    computed_at: datetime
    factors: dict[str, Any] = PField(default_factory=dict)


class RemediationWorkflow(BaseModel):
    """A remediation workflow for a shadow AI asset."""

    id: UUID
    tenant_id: UUID
    asset_id: UUID
    action: str  # notify | offer_alternative | escalate | block
    status: str = "pending"  # pending | in_progress | completed | cancelled
    assigned_to: str | None = None
    escalation_level: int = 0  # 0=initial, 1=manager, 2=ciso, 3=block
    created_at: datetime
    updated_at: datetime | None = None
    notes: str | None = None


class PostureReport(BaseModel):
    """Monthly AI security posture report."""

    tenant_id: UUID
    period: str  # e.g. "2026-02"
    score_trend: list[dict[str, Any]] = PField(default_factory=list)
    current_score: int = 0
    findings: list[dict[str, Any]] = PField(default_factory=list)
    recommendations: list[str] = PField(default_factory=list)
    shadow_ai_count: int = 0
    credential_exposures: int = 0
    generated_at: datetime


class KnownAIService(BaseModel):
    """A known AI service in the reference database."""

    name: str
    domain: str
    category: str  # llm | copilot | chatbot | image_gen | code_assistant | saas_ai
    risk_level: str = "medium"  # critical | high | medium | low | informational
    description: str = ""
    provider: str = ""


class SSOLogSource(BaseModel):
    """An SSO/IdP log source configuration."""

    type: str  # okta | azure_ad | ping | onelogin | custom
    name: str
    config: dict[str, Any] = PField(default_factory=dict)


class IngestResult(BaseModel):
    """Result of SSO log ingestion."""

    source: str
    records_processed: int = 0
    services_detected: int = 0
    new_services: int = 0
    errors: int = 0


__all__ = [
    "AIAsset",
    "CredentialExposure",
    "DiscoveredService",
    "DiscoveryConfig",
    "DiscoveryResult",
    "DiscoveryScan",
    "IngestResult",
    "KnownAIService",
    "PostureReport",
    "PostureScore",
    "RemediationWorkflow",
    "RiskClassification",
    "SentinelFinding",
    "SentinelScanHistory",
    "SSOLogSource",
]
