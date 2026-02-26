"""SQLModel database models for custom RBAC roles."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class CustomRole(SQLModel, table=True):
    """Tenant-scoped custom RBAC role with explicit permission grants."""

    __tablename__ = "custom_roles"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    permissions: dict[str, list[str]] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    is_builtin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "CustomRole",
]
