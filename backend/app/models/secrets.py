"""SQLModel database models for secrets registration and rotation tracking."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class SecretRegistration(SQLModel, table=True):
    """Registry entry tracking a secret's path, type, and rotation schedule."""

    __tablename__ = "secret_registrations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    path: str = Field(index=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")
    secret_type: str = Field(default="static")  # static | dynamic | pki
    rotation_policy_days: int | None = Field(default=None)
    last_rotated_at: datetime | None = Field(default=None)
    next_rotation_at: datetime | None = Field(default=None)
    created_by: UUID | None = Field(default=None, foreign_key="user_identities.id")
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "SecretRegistration",
]
