"""SQLModel database models and Pydantic schemas for A2A (Agent-to-Agent) protocol support."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
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


# ── Enums ───────────────────────────────────────────────────────────


class TrustLevel(str, enum.Enum):
    """Trust level for a federated A2A partner."""

    UNTRUSTED = "untrusted"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    FEDERATED = "federated"


# ── Pydantic schemas (API layer) ────────────────────────────────────


class PartnerRegistration(BaseModel):
    """Request schema for registering a new A2A federation partner."""

    name: str
    base_url: str
    token_endpoint: str
    public_key: str | None = None
    scopes: list[str] = PField(default_factory=list)


class Partner(BaseModel):
    """Response schema for an A2A federation partner."""

    id: UUID
    tenant_id: str
    name: str
    base_url: str
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    status: str = "active"
    registered_at: datetime
    last_communication: datetime | None = None


class A2AAccessToken(BaseModel):
    """OAuth 2.0 access token returned from federated client credentials flow."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    scope: str = ""


class AgentCard(BaseModel):
    """JSON-LD agent card describing a published or discovered A2A agent."""

    agent_id: UUID
    name: str
    description: str | None = None
    capabilities: list[str] = PField(default_factory=list)
    input_schema: dict[str, Any] = PField(default_factory=dict)
    output_schema: dict[str, Any] = PField(default_factory=dict)
    version: str = "1.0.0"
    published_at: datetime | None = None


class A2AFederationMessage(BaseModel):
    """Message exchanged between federated A2A partners."""

    message_id: UUID
    sender_agent_id: UUID
    content: str
    metadata: dict[str, Any] = PField(default_factory=dict)
    timestamp: datetime


class A2AResponse(BaseModel):
    """Response to an A2A federation message."""

    message_id: UUID
    response_content: str
    status: str = "completed"
    processing_time_ms: float = 0.0


class TrustLevelUpdate(BaseModel):
    """Request schema for updating a partner's trust level."""

    trust_level: TrustLevel


class FederationStatus(BaseModel):
    """Overall health and statistics for the A2A federation layer."""

    partner_count: int = 0
    active_connections: int = 0
    messages_today: int = 0
    health: str = "healthy"


class A2AAgentCard(SQLModel, table=True):
    """Discovered or published A2A Agent Card (per the A2A protocol spec)."""

    __tablename__ = "a2a_agent_cards"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    url: str = Field(index=True)  # Base URL where the agent is hosted
    version: str = Field(default="1.0.0")

    # A2A protocol fields
    capabilities: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )  # e.g. ["streaming", "push_notifications", "task_delegation"]
    skills: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )  # Skill descriptors from agent card
    auth_schemes: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )  # e.g. ["bearer", "oauth2", "mtls"]

    # Whether this card is published by Archon (outbound) or discovered (inbound)
    direction: str = Field(default="inbound")  # inbound | outbound

    # Link to an internal Archon agent (for outbound cards)
    agent_id: UUID | None = Field(default=None, index=True, foreign_key="agents.id")

    is_active: bool = Field(default=True)
    last_discovered_at: datetime | None = Field(default=None)

    # Arbitrary extra metadata
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class A2AMessage(SQLModel, table=True):
    """A message exchanged via the A2A protocol (inbound or outbound)."""

    __tablename__ = "a2a_messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_id: UUID = Field(index=True, foreign_key="a2a_tasks.id")

    role: str  # user | agent
    content: str = Field(sa_column=Column(SAText, nullable=False))

    # Structured parts (text, file, data, etc.)
    parts: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow)


class A2ATask(SQLModel, table=True):
    """Record of a task delegated via the A2A protocol."""

    __tablename__ = "a2a_tasks"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_card_id: UUID = Field(index=True, foreign_key="a2a_agent_cards.id")

    # Task lifecycle
    status: str = Field(default="submitted", index=True)
    # submitted | working | input_required | completed | failed | canceled

    direction: str = Field(default="outbound")  # outbound (we sent) | inbound (we received)

    # Input/output payloads
    input_data: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    output_data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "A2AAgentCard",
    "A2AAccessToken",
    "A2AFederationMessage",
    "A2AMessage",
    "A2AResponse",
    "A2ATask",
    "AgentCard",
    "FederationStatus",
    "Partner",
    "PartnerRegistration",
    "TrustLevel",
    "TrustLevelUpdate",
]
