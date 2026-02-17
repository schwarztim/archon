"""Pydantic models for the Agent Version Control service.

Includes signed versions, secrets-aware diffs, deployment promotions,
rollback pre-flight checks, and signature verification results.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(tz=timezone.utc)


# ── Core version snapshot ───────────────────────────────────────────


class AgentVersion(BaseModel):
    """Immutable, cryptographically signed snapshot of an agent definition."""

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    version_number: str
    content_hash: str = Field(description="SHA-256 hash of canonical graph definition")
    signature: str = Field(description="Hex-encoded HMAC-SHA256 signature")
    signing_identity: str = Field(description="Email of the signing key owner")
    graph_definition: dict[str, Any] = Field(default_factory=dict)
    change_reason: str | None = None
    created_by: str = Field(description="User email who created this version")
    created_at: datetime = Field(default_factory=_utcnow)

    model_config = {"frozen": True}


# ── Secrets-aware diff ──────────────────────────────────────────────


class VersionDiff(BaseModel):
    """Diff between two agent versions, secrets-aware (paths only, never values)."""

    version_a: str = Field(description="Version A identifier")
    version_b: str = Field(description="Version B identifier")
    nodes_added: list[str] = Field(default_factory=list)
    nodes_removed: list[str] = Field(default_factory=list)
    nodes_modified: list[dict[str, Any]] = Field(default_factory=list)
    secrets_paths_added: list[str] = Field(
        default_factory=list,
        description="Vault secret paths added (never actual values)",
    )
    secrets_paths_removed: list[str] = Field(
        default_factory=list,
        description="Vault secret paths removed (never actual values)",
    )
    summary: str = ""


# ── Deployment promotion ───────────────────────────────────────────


class DeploymentPromotion(BaseModel):
    """Tracks promotion of a version through environments."""

    version_id: UUID
    source_env: str
    target_env: str
    status: str = Field(default="pending", description="pending | approved | rejected | promoted")
    approvals_required: int = Field(default=0)
    approvals_received: int = Field(default=0)
    promoted_at: datetime | None = None

    model_config = {"frozen": True}


# ── Signature verification ─────────────────────────────────────────


class SignatureVerification(BaseModel):
    """Result of verifying a version's cryptographic signature."""

    version_id: UUID
    valid: bool
    signer_email: str
    signed_at: datetime
    content_hash_matches: bool


# ── Rollback pre-flight ────────────────────────────────────────────


class RollbackPreFlight(BaseModel):
    """Pre-flight check results before rolling back to a target version."""

    target_version: str
    secrets_compatible: bool = True
    models_available: bool = True
    connectors_available: bool = True
    issues: list[str] = Field(default_factory=list)


# ── Request / response helpers ─────────────────────────────────────


class CreateVersionRequest(BaseModel):
    """Request body for creating a new agent version."""

    change_reason: str = Field(min_length=1, max_length=500)


class PromoteVersionRequest(BaseModel):
    """Request body for promoting a version to a target environment."""

    target_env: str = Field(description="Target environment: staging | production")


class VersionListFilters(BaseModel):
    """Query filters for listing versions."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ExportFormat(BaseModel):
    """Export format selector."""

    format: str = Field(default="json", description="json | pdf")
