"""Pydantic models for the Enterprise Connector Hub."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ConnectorCategory(str, Enum):
    """Supported connector integration categories."""

    CRM = "crm"
    STORAGE = "storage"
    COMMUNICATION = "communication"
    DATABASE = "database"
    ANALYTICS = "analytics"
    DEVTOOLS = "devtools"


class ConnectorStatus(str, Enum):
    """Lifecycle status of a connector instance."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING_AUTH = "pending_auth"


class AuthMethod(str, Enum):
    """Supported authentication methods for connectors."""

    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BASIC = "basic"
    SERVICE_ACCOUNT = "service_account"


# ── Connector type catalog ──────────────────────────────────────────


class ConnectorType(BaseModel):
    """Describes a connector type available in the platform catalog."""

    name: str
    category: ConnectorCategory
    auth_methods: list[AuthMethod] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    description: str = ""


# ── Configuration & registration ────────────────────────────────────


class ConnectorConfig(BaseModel):
    """Payload for registering a new connector instance."""

    type: str
    name: str
    auth_method: AuthMethod = AuthMethod.OAUTH2
    scopes: list[str] = Field(default_factory=list)
    custom_config: dict[str, Any] = Field(default_factory=dict)


# ── Instance representation ─────────────────────────────────────────


class ConnectorInstance(BaseModel):
    """Persisted connector record returned by the service layer."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    type: str
    name: str
    status: ConnectorStatus = ConnectorStatus.INACTIVE
    auth_method: AuthMethod = AuthMethod.OAUTH2
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    last_health_check: datetime | None = None


# ── OAuth flow models ───────────────────────────────────────────────


class OAuthFlowStart(BaseModel):
    """Returned when an OAuth 2.0 authorization code flow is initiated."""

    authorization_url: str
    state: str
    code_verifier: str | None = None


class OAuthCredential(BaseModel):
    """Metadata for an OAuth credential stored in Vault."""

    connector_id: UUID
    token_type: str = "Bearer"
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    vault_path: str = ""


# ── Connection testing ──────────────────────────────────────────────


class ConnectionTestResult(BaseModel):
    """Result of a connector health-check probe."""

    connector_id: UUID
    status: str  # "ok" | "error"
    latency_ms: float = 0.0
    error_message: str | None = None


# ── Action execution ────────────────────────────────────────────────


class ActionResult(BaseModel):
    """Result of executing a CRUD action via a connector."""

    connector_id: UUID
    action: str
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ActionResult",
    "AuthMethod",
    "ConnectionTestResult",
    "ConnectorCategory",
    "ConnectorConfig",
    "ConnectorInstance",
    "ConnectorStatus",
    "ConnectorType",
    "OAuthCredential",
    "OAuthFlowStart",
]
