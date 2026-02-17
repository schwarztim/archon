"""Pydantic configuration models for Archon connectors."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr


class AuthType(str, Enum):
    """Supported authentication mechanisms."""

    NONE = "none"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    BASIC = "basic"
    BEARER = "bearer"
    CUSTOM = "custom"


class RetryConfig(BaseModel):
    """Retry behaviour with exponential back-off + jitter."""

    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts")
    base_delay_seconds: float = Field(
        default=1.0, gt=0, description="Initial delay between retries in seconds"
    )
    max_delay_seconds: float = Field(
        default=60.0, gt=0, description="Maximum delay between retries in seconds"
    )
    jitter: bool = Field(default=True, description="Add random jitter to retry delays")


class RateLimitConfig(BaseModel):
    """Provider-specific rate-limit settings."""

    requests_per_second: float | None = Field(
        default=None, ge=0, description="Max requests per second (None = unlimited)"
    )
    requests_per_minute: float | None = Field(
        default=None, ge=0, description="Max requests per minute (None = unlimited)"
    )
    burst_size: int = Field(
        default=10, ge=1, description="Max burst size before throttling"
    )


class ConnectorAuthConfig(BaseModel):
    """Authentication credentials for a connector."""

    auth_type: AuthType = Field(default=AuthType.NONE, description="Authentication type")
    api_key: SecretStr | None = Field(default=None, description="API key or token")
    client_id: str | None = Field(default=None, description="OAuth2 client ID")
    client_secret: SecretStr | None = Field(default=None, description="OAuth2 client secret")
    token_url: str | None = Field(default=None, description="OAuth2 token endpoint URL")
    scopes: list[str] = Field(default_factory=list, description="OAuth2 scopes")
    username: str | None = Field(default=None, description="Basic-auth username")
    password: SecretStr | None = Field(default=None, description="Basic-auth password")
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Provider-specific auth fields"
    )


class ConnectorConfig(BaseModel):
    """Top-level configuration for a connector instance."""

    connector_type: str = Field(
        ..., min_length=1, description="Connector type identifier (e.g. 'slack', 'github')"
    )
    name: str = Field(
        ..., min_length=1, description="Human-readable instance name"
    )
    description: str = Field(default="", description="Optional description")
    base_url: str | None = Field(default=None, description="Base URL for the remote service")
    auth: ConnectorAuthConfig = Field(
        default_factory=ConnectorAuthConfig, description="Authentication configuration"
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry configuration"
    )
    rate_limit: RateLimitConfig = Field(
        default_factory=RateLimitConfig, description="Rate-limit configuration"
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0, description="Default request timeout in seconds"
    )
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Provider-specific settings"
    )
