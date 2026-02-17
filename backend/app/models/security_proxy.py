"""Pydantic models for the Cross-Platform Security Proxy Gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AuthMethod(str, Enum):
    """Supported upstream authentication methods."""

    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    OAUTH2 = "oauth2"
    AZURE_AD = "azure_ad"
    CUSTOM_HEADER = "custom_header"


class ProviderType(str, Enum):
    """Supported AI provider types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    GOOGLE = "google"
    CUSTOM = "custom"


class SensitivityLevel(str, Enum):
    """Content sensitivity classification levels."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ProxyRequest(BaseModel):
    """Inbound request to be proxied through the security pipeline."""

    method: str = Field(description="HTTP method (GET, POST, etc.)")
    url: str = Field(description="Target URL to proxy to")
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | str | None = Field(default=None)
    tenant_id: str = Field(description="Tenant scope for the request")
    user_id: str = Field(description="Requesting user ID")


class DLPFinding(BaseModel):
    """Individual DLP finding from a scan."""

    entity_type: str
    confidence: float
    redacted_value: str
    direction: str = Field(description="request or response")


class ProxyResponse(BaseModel):
    """Response from the security proxy pipeline."""

    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | str | None = Field(default=None)
    dlp_findings: list[DLPFinding] = Field(default_factory=list)
    cost_usd: float = Field(default=0.0)
    latency_ms: float = Field(default=0.0)


class ProxySession(BaseModel):
    """Internal session created from SAML termination."""

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    tenant_id: str
    authenticated_via: str = Field(default="saml")
    expires_at: datetime
    email: str = ""
    roles: list[str] = Field(default_factory=list)


class UpstreamConfig(BaseModel):
    """Configuration for an upstream AI endpoint."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    base_url: str
    provider_type: ProviderType
    auth_method: AuthMethod
    vault_credential_path: str = Field(
        description="Vault path for credentials — never stored in plaintext",
    )
    rate_limit: int = Field(default=100, description="Max requests per minute")
    tenant_id: str = ""
    enabled: bool = True
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class UpstreamSummary(BaseModel):
    """Summary entry for top upstream usage in metrics."""

    name: str
    request_count: int
    avg_latency_ms: float


class ProxyMetrics(BaseModel):
    """Aggregated proxy metrics for a tenant."""

    total_requests: int = 0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    total_cost_usd: float = 0.0
    top_upstreams: list[UpstreamSummary] = Field(default_factory=list)


class ContentClassification(BaseModel):
    """Result of content classification."""

    topics: list[str] = Field(default_factory=list)
    sensitivity_level: SensitivityLevel = SensitivityLevel.INTERNAL
    intent: str = Field(default="unknown")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ── Route-level request/response schemas ────────────────────────────


class ProxyRequestBody(BaseModel):
    """API request body for proxy/request endpoint."""

    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | str | None = None


class SAMLTerminateBody(BaseModel):
    """API request body for SAML termination."""

    saml_response: str
    issuer: str


class UpstreamCreateBody(BaseModel):
    """API request body for upstream configuration."""

    name: str
    base_url: str
    provider_type: ProviderType
    auth_method: AuthMethod
    vault_credential_path: str
    rate_limit: int = 100


class ClassifyBody(BaseModel):
    """API request body for content classification."""

    content: str


__all__ = [
    "AuthMethod",
    "ClassifyBody",
    "ContentClassification",
    "DLPFinding",
    "ProviderType",
    "ProxyMetrics",
    "ProxyRequest",
    "ProxyRequestBody",
    "ProxyResponse",
    "ProxySession",
    "SAMLTerminateBody",
    "SensitivityLevel",
    "UpstreamConfig",
    "UpstreamCreateBody",
    "UpstreamSummary",
]
