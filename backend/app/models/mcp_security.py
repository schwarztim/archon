"""SQLModel database models for the Archon MCP Security Guardian.

Covers tool authorizations, sandbox sessions, security events,
tool version tracking, and response validation records.
"""

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


class MCPToolAuthorization(SQLModel, table=True):
    """Per-tool authorization policy controlling who may invoke which MCP tools."""

    __tablename__ = "mcp_tool_authorizations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tool_name: str = Field(index=True)
    server_name: str = Field(index=True)

    # Scope: which principals this policy applies to
    agent_id: UUID | None = Field(default=None, index=True)
    user_id: UUID | None = Field(default=None, index=True)
    department_id: UUID | None = Field(default=None, index=True)

    # Policy settings
    action: str = Field(default="allow")  # allow | deny | require_approval
    risk_level: str = Field(default="low")  # low | medium | high | critical
    is_active: bool = Field(default=True)

    # Parameter constraints: JSON schema or pattern restrictions
    parameter_constraints: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    # Allowed parameter patterns (e.g. {"path": "^/tmp/.*"})
    allowed_patterns: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MCPSandboxSession(SQLModel, table=True):
    """Record of an ephemeral sandbox execution for an MCP tool call."""

    __tablename__ = "mcp_sandbox_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tool_name: str = Field(index=True)
    server_name: str = Field(index=True)
    agent_id: UUID | None = Field(default=None, index=True)
    user_id: UUID | None = Field(default=None, index=True)

    # Sandbox configuration
    status: str = Field(default="pending")  # pending | running | completed | failed | destroyed
    resource_limits: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )  # cpu, memory, network, disk
    network_policy: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )  # allowed endpoints
    timeout_seconds: int = Field(default=30)

    # Execution details
    input_hash: str | None = Field(default=None)  # SHA-256 of input (never store raw)
    output_hash: str | None = Field(default=None)  # SHA-256 of output
    exit_code: int | None = Field(default=None)
    error_message: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    destroyed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class MCPSecurityEvent(SQLModel, table=True):
    """Audit trail for MCP security-relevant events."""

    __tablename__ = "mcp_security_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    event_type: str = Field(index=True)
    # auth_granted | auth_denied | sandbox_created | sandbox_destroyed
    # tool_changed | tool_added | tool_removed | response_blocked
    # injection_detected | anomaly_detected | validation_failed

    severity: str = Field(default="info")  # info | warning | error | critical
    tool_name: str | None = Field(default=None, index=True)
    server_name: str | None = Field(default=None, index=True)
    agent_id: UUID | None = Field(default=None, index=True)
    user_id: UUID | None = Field(default=None, index=True)
    sandbox_session_id: UUID | None = Field(default=None, index=True)

    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow)


class MCPToolVersion(SQLModel, table=True):
    """Versioned snapshot of an MCP tool definition for change tracking."""

    __tablename__ = "mcp_tool_versions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tool_name: str = Field(index=True)
    server_name: str = Field(index=True)
    version: str = Field(index=True)

    # Full tool definition at this version
    definition: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False)
    )
    definition_hash: str = Field(index=True)  # SHA-256 for quick comparison

    # Change info relative to previous version
    change_type: str | None = Field(default=None)  # added | modified | removed
    previous_version_id: UUID | None = Field(default=None)
    diff_summary: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))

    is_pinned: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)


class MCPResponseValidation(SQLModel, table=True):
    """Record of a validated MCP tool response."""

    __tablename__ = "mcp_response_validations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    sandbox_session_id: UUID | None = Field(default=None, index=True)
    tool_name: str = Field(index=True)
    server_name: str = Field(index=True)

    # Validation results
    is_valid: bool = Field(default=True)
    response_size_bytes: int = Field(default=0)
    was_truncated: bool = Field(default=False)

    # Security checks
    injection_detected: bool = Field(default=False)
    injection_patterns: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    dlp_findings_count: int = Field(default=0)
    anomaly_score: float = Field(default=0.0)

    # Schema validation
    schema_valid: bool | None = Field(default=None)
    validation_errors: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    action_taken: str = Field(default="pass")  # pass | warn | block | redact

    created_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic request/response schemas (non-ORM) ────────────────────

from enum import Enum

from pydantic import BaseModel, Field as PField


class RiskLevel(str, Enum):
    """Tool risk classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MCPToolDefinition(BaseModel):
    """Schema for registering or updating an MCP tool."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = PField(default_factory=dict)
    output_schema: dict[str, Any] = PField(default_factory=dict)
    required_scopes: list[str] = PField(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW


class MCPTool(BaseModel):
    """Registered MCP tool with security metadata."""

    id: str
    name: str
    version: str = "1.0.0"
    scopes: list[str] = PField(default_factory=list)
    security_score: float = 100.0
    status: str = "active"
    registered_at: str = ""


class AuthorizationResult(BaseModel):
    """Outcome of an OAuth-scope authorization check."""

    authorized: bool
    missing_scopes: list[str] = PField(default_factory=list)
    requires_admin_approval: bool = False
    reason: str = ""


class ToolExecutionResult(BaseModel):
    """Result returned after sandboxed tool execution."""

    tool_id: str
    output: dict[str, Any] = PField(default_factory=dict)
    execution_time_ms: float = 0.0
    sandbox_id: str = ""
    dlp_findings: list[str] = PField(default_factory=list)


class ConsentStatus(BaseModel):
    """Current consent state for a user × tool pair."""

    user_id: str
    tool_id: str
    granted_scopes: list[str] = PField(default_factory=list)
    revoked_scopes: list[str] = PField(default_factory=list)
    updated_at: str = ""


class ValidationResult(BaseModel):
    """Outcome of schema + DLP validation on a tool response."""

    valid: bool
    schema_errors: list[str] = PField(default_factory=list)
    dlp_findings: list[str] = PField(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW


class SecurityScoreFactor(BaseModel):
    """Individual factor contributing to the security score."""

    name: str
    score: float
    weight: float = 1.0
    detail: str = ""


class SecurityScore(BaseModel):
    """Per-tool security posture score (0-100)."""

    tool_id: str
    overall: float = 100.0
    factors: list[SecurityScoreFactor] = PField(default_factory=list)
    recommendations: list[str] = PField(default_factory=list)


class AuthMatrix(BaseModel):
    """Authorization matrix: role × department → allowed tools."""

    roles: dict[str, list[str]] = PField(default_factory=dict)
    departments: dict[str, list[str]] = PField(default_factory=dict)


class ToolVersionDiff(BaseModel):
    """Diff between two versions of a tool definition."""

    tool_id: str
    old_version: str
    new_version: str
    schema_changes: list[str] = PField(default_factory=list)
    breaking_changes: bool = False


__all__ = [
    "MCPResponseValidation",
    "MCPSandboxSession",
    "MCPSecurityEvent",
    "MCPToolAuthorization",
    "MCPToolVersion",
    "AuthMatrix",
    "AuthorizationResult",
    "ConsentStatus",
    "MCPTool",
    "MCPToolDefinition",
    "RiskLevel",
    "SecurityScore",
    "SecurityScoreFactor",
    "ToolExecutionResult",
    "ToolVersionDiff",
    "ValidationResult",
]
