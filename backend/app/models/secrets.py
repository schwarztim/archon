"""SQLModel database models for secrets registration, rotation tracking, and access logging."""

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
    secret_type: str = Field(default="static")  # api_key | oauth_token | password | certificate | custom
    rotation_policy_days: int | None = Field(default=None)
    notify_before_days: int = Field(default=14)
    auto_rotate: bool = Field(default=False)
    last_rotated_at: datetime | None = Field(default=None)
    next_rotation_at: datetime | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    created_by: UUID | None = Field(default=None, foreign_key="user_identities.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SecretAccessLog(SQLModel, table=True):
    """Audit log entry for every secret access (read/write/rotate/delete)."""

    __tablename__ = "secret_access_logs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")
    secret_path: str = Field(index=True)
    user_id: UUID | None = Field(default=None, foreign_key="user_identities.id")
    user_email: str = Field(default="")
    action: str = Field(index=True)  # read | write | rotate | delete | reveal
    component: str = Field(default="")  # provider_setup | connector_setup | manual | etc.
    ip_address: str | None = Field(default=None)
    details: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "SecretAccessLog",
    "SecretRegistration",
]
