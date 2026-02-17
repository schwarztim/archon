"""SQLModel database models and Pydantic schemas for the Archon DLP engine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field as PField
from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# ── ORM Models (table=True) ────────────────────────────────────────


class DLPPolicy(SQLModel, table=True):
    """Configurable DLP policy that defines what to detect and how to act."""

    __tablename__ = "dlp_policies"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    description_nl: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    is_active: bool = Field(default=True)

    # Detection configuration
    detector_types: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    # Custom regex patterns beyond built-in detectors
    custom_patterns: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    # Structured rules derived from natural language policy
    rules: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    # Action to take on detection: allow | mask | redact | block | alert
    action: str = Field(default="redact")

    # Sensitivity level: low | medium | high | critical
    sensitivity: str = Field(default="high")

    # Scope filters
    agent_id: UUID | None = Field(default=None, index=True)
    department_id: UUID | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class DLPScanResult(SQLModel, table=True):
    """Result of a DLP scan against text content."""

    __tablename__ = "dlp_scan_results"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(default="", index=True)
    policy_id: UUID | None = Field(default=None, index=True)
    source: str = Field(default="manual")
    text_hash: str | None = Field(default=None)
    has_findings: bool = Field(default=False)
    findings_count: int = Field(default=0)
    action_taken: str = Field(default="none")

    entity_types_found: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow)


class DLPDetectedEntity(SQLModel, table=True):
    """Individual sensitive entity detected during a DLP scan."""

    __tablename__ = "dlp_detected_entities"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    scan_result_id: UUID = Field(index=True, foreign_key="dlp_scan_results.id")
    entity_type: str = Field(index=True)
    confidence: float = Field(default=1.0)
    start_offset: int = Field(default=0)
    end_offset: int = Field(default=0)
    redacted_value: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)


# ── Enums ───────────────────────────────────────────────────────────


class RiskLevel(str, Enum):
    """Risk severity for scan findings."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ScanAction(str, Enum):
    """Action to take after a DLP scan."""

    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"


class ScanDirection(str, Enum):
    """Direction of content flow being scanned."""

    INPUT = "input"
    OUTPUT = "output"


# ── Pydantic Schemas (API layer) ───────────────────────────────────


class SecretFinding(BaseModel):
    """A single secret detected by regex scanning."""

    pattern_name: str
    matched_text_preview: str = PField(
        description="First 8 chars + '...' — never the full secret"
    )
    position: tuple[int, int]
    confidence: float = PField(ge=0.0, le=1.0)
    severity: str = "high"


class PIIFinding(BaseModel):
    """A single PII entity detected."""

    pii_type: str
    matched_text_preview: str
    position: tuple[int, int]
    confidence: float = PField(ge=0.0, le=1.0)


class DLPScanResultSchema(BaseModel):
    """Schema returned from a full DLP scan."""

    content_id: str
    findings: list[SecretFinding | PIIFinding]
    risk_level: RiskLevel
    action: ScanAction
    processing_time_ms: float


class GuardrailConfig(BaseModel):
    """Configuration for input/output guardrails."""

    enable_injection_detection: bool = True
    blocked_topics: list[str] = PField(default_factory=list)
    max_toxicity_score: float = PField(default=0.8, ge=0.0, le=1.0)
    enable_pii_echo_prevention: bool = True


class GuardrailViolation(BaseModel):
    """A single guardrail violation."""

    rule: str
    detail: str
    severity: str = "medium"


class GuardrailResult(BaseModel):
    """Result of a guardrail check."""

    passed: bool
    violations: list[GuardrailViolation] = PField(default_factory=list)
    action: ScanAction = ScanAction.ALLOW


class DLPPolicySchema(BaseModel):
    """API representation of a DLP policy."""

    id: UUID
    tenant_id: str
    name: str
    description_nl: str | None = None
    rules: list[dict[str, Any]] = PField(default_factory=list)
    active: bool = True


class PolicyEvaluation(BaseModel):
    """Evaluation of content against a single policy."""

    policy_id: UUID
    matched: bool
    action: ScanAction
    reason: str


class VaultCrossRef(BaseModel):
    """Cross-reference of a finding against Vault."""

    finding: SecretFinding
    vault_path: str
    exists_in_vault: bool
    rotation_triggered: bool


__all__ = [
    "DLPDetectedEntity",
    "DLPPolicy",
    "DLPPolicySchema",
    "DLPScanResult",
    "DLPScanResultSchema",
    "GuardrailConfig",
    "GuardrailResult",
    "GuardrailViolation",
    "PIIFinding",
    "PolicyEvaluation",
    "RiskLevel",
    "ScanAction",
    "ScanDirection",
    "SecretFinding",
    "VaultCrossRef",
]
