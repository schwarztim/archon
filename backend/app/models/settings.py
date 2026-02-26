"""SQLModel database models for platform settings, feature flags, and API keys."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class PlatformSetting(SQLModel, table=True):
    """Key-value platform configuration scoped to a tenant."""

    __tablename__ = "platform_settings"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    key: str = Field(index=True)
    value: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    updated_by: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FeatureFlag(SQLModel, table=True):
    """Feature flag toggle for experimental features."""

    __tablename__ = "feature_flags"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str = Field(index=True)
    description: str = Field(default="", sa_column=Column(SAText, nullable=False))
    enabled: bool = Field(default=False)
    updated_by: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class PlatformSettings(SQLModel, table=True):
    """Platform settings by category, stored as JSON per tenant."""

    __tablename__ = "platform_settings_v2"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    category: str = Field(
        index=True
    )  # general, authentication, notifications, api, appearance
    settings_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow)


class FeatureFlagRecord(SQLModel, table=True):
    """Feature flag toggle with description."""

    __tablename__ = "feature_flags_v2"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str = Field(index=True)
    description: str = Field(default="", sa_column=Column(SAText, nullable=False))
    enabled: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=_utcnow)


class SettingsAPIKey(SQLModel, table=True):
    """API key for programmatic access created through settings."""

    __tablename__ = "settings_api_keys"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str
    key_prefix: str = Field(default="")
    key_hash: str = Field(default="")
    scopes: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    created_by: UUID | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    revoked: bool = Field(default=False)
    last_used_at: datetime | None = Field(default=None)
    rate_limit: int | None = Field(default=None)  # RPM per key; None = tenant default
    created_at: datetime = Field(default_factory=_utcnow)

    @staticmethod
    def generate_key() -> tuple[str, str, str]:
        """Generate a new API key, returning (full_key, prefix, hash)."""
        raw = secrets.token_urlsafe(32)
        prefix = raw[:8]
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        return raw, prefix, key_hash


__all__ = [
    "FeatureFlag",
    "FeatureFlagRecord",
    "PlatformSetting",
    "PlatformSettings",
    "SettingsAPIKey",
]
