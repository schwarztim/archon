"""Connector type registry — credential schemas, OAuth, testers, health checks, and implementations."""

from __future__ import annotations

from typing import Any

from app.services.connectors.base import BaseConnector
from app.services.connectors.google_drive import GoogleDriveConnector
from app.services.connectors.health import HealthChecker
from app.services.connectors.oauth import OAuthProviderRegistry
from app.services.connectors.postgresql import PostgreSQLConnector
from app.services.connectors.rest_api import RestApiConnector
from app.services.connectors.s3 import S3Connector
from app.services.connectors.schemas import (
    CONNECTOR_TYPE_REGISTRY,
    ConnectorTypeSchema,
    CredentialField,
)
from app.services.connectors.slack import SlackConnector
from app.services.connectors.testers import ConnectionTester

# Map connector type names → implementation classes
_CONNECTOR_IMPLEMENTATIONS: dict[str, type[BaseConnector]] = {
    "postgresql": PostgreSQLConnector,
    "postgres": PostgreSQLConnector,
    "rest_api": RestApiConnector,
    "rest": RestApiConnector,
    "http": RestApiConnector,
    "slack": SlackConnector,
    "s3": S3Connector,
    "google_drive": GoogleDriveConnector,
    "google": GoogleDriveConnector,
}


def get_connector(
    connector_type: str,
    config: dict[str, Any],
    credentials: dict[str, Any],
) -> BaseConnector | None:
    """Instantiate a connector implementation by type.

    Returns ``None`` if no implementation exists for the given type,
    allowing callers to fall back to config-level validation.

    Args:
        connector_type: Connector type string (e.g. ``"postgresql"``, ``"slack"``).
        config: Type-specific configuration (host, port, bucket name, etc.).
        credentials: Secrets loaded from Vault (tokens, passwords, API keys).

    Returns:
        A ``BaseConnector`` instance ready for use as an async context manager,
        or ``None`` if the type is not implemented.
    """
    cls = _CONNECTOR_IMPLEMENTATIONS.get(connector_type.lower())
    if cls is None:
        return None
    return cls(config=config, credentials=credentials)


__all__ = [
    "BaseConnector",
    "CONNECTOR_TYPE_REGISTRY",
    "ConnectorTypeSchema",
    "ConnectionTester",
    "CredentialField",
    "get_connector",
    "GoogleDriveConnector",
    "HealthChecker",
    "OAuthProviderRegistry",
    "PostgreSQLConnector",
    "RestApiConnector",
    "S3Connector",
    "SlackConnector",
]
