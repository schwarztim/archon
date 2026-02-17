"""SQLModel database models for enterprise audit events with hash-chain integrity."""

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


class EnterpriseAuditEvent(SQLModel, table=True):
    """Extended audit event with request context and hash-chain for tamper detection.

    Complements the base AuditLog model with enterprise-grade fields
    (IP, user-agent, session, hash chain).
    """

    __tablename__ = "enterprise_audit_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")
    user_id: UUID | None = Field(default=None, index=True, foreign_key="user_identities.id")
    action: str = Field(index=True)
    resource_type: str = Field(index=True)
    resource_id: str | None = Field(default=None, index=True)
    details: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True),
    )
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    session_id: str | None = Field(default=None, index=True)
    previous_hash: str | None = Field(default=None)
    event_hash: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow, index=True)


__all__ = [
    "EnterpriseAuditEvent",
]
