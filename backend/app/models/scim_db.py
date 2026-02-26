"""SCIM User and Group SQLModel tables for persistent storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class SCIMUserRecord(SQLModel, table=True):
    """Persisted SCIM 2.0 User resource (RFC 7643 §4.1)."""

    __tablename__ = "scim_users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    scim_id: str = Field(index=True)
    external_id: str | None = Field(default=None)
    user_name: str = Field(index=True)
    display_name: str = Field(default="")
    emails: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    groups: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SCIMGroupRecord(SQLModel, table=True):
    """Persisted SCIM 2.0 Group resource (RFC 7643 §4.2)."""

    __tablename__ = "scim_groups"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    scim_id: str = Field(index=True)
    display_name: str
    members: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "SCIMGroupRecord",
    "SCIMUserRecord",
]
