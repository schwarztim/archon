"""Pydantic models for the Red-Teaming & Adversarial Testing Engine."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AttackCategory(str, Enum):
    """Categories of adversarial attacks the red-team engine can execute."""

    jwt_attacks = "jwt_attacks"
    prompt_injection = "prompt_injection"
    tenant_isolation = "tenant_isolation"
    credential_leak = "credential_leak"
    ssrf = "ssrf"
    rate_limit_bypass = "rate_limit_bypass"


class Severity(str, Enum):
    """Vulnerability severity levels."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class VulnerabilityFinding(BaseModel):
    """A single vulnerability discovered during a security scan."""

    id: UUID
    category: AttackCategory
    severity: Severity
    title: str
    description: str
    cvss_score: float = Field(ge=0.0, le=10.0)
    remediation: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class SecurityScanConfig(BaseModel):
    """Configuration for initiating a security scan."""

    attack_categories: list[AttackCategory] = Field(
        default_factory=lambda: list(AttackCategory),
    )
    severity_threshold: Severity = Severity.low
    max_duration_seconds: int = Field(default=300, ge=10, le=3600)


class ScanSummary(BaseModel):
    """Aggregated summary of scan findings."""

    total_findings: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class SecurityScanResult(BaseModel):
    """Full result of a red-team security scan."""

    scan_id: UUID
    tenant_id: str
    agent_id: UUID
    findings: list[VulnerabilityFinding] = Field(default_factory=list)
    summary: ScanSummary = Field(default_factory=ScanSummary)
    sarif_url: str | None = None
    passed: bool = True
    started_at: datetime
    completed_at: datetime | None = None
    config: SecurityScanConfig = Field(default_factory=SecurityScanConfig)


__all__ = [
    "AttackCategory",
    "ScanSummary",
    "SecurityScanConfig",
    "SecurityScanResult",
    "Severity",
    "VulnerabilityFinding",
]
