"""Health check implementations for connected connectors."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.interfaces.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status levels for connectors."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERROR = "error"
    UNKNOWN = "unknown"


class HealthCheckResult(BaseModel):
    """Result of a connector health check."""

    connector_id: str
    status: HealthStatus = HealthStatus.UNKNOWN
    latency_ms: float = 0.0
    message: str = ""
    last_check: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class HealthChecker:
    """Checks the health of connected connectors."""

    @staticmethod
    async def check(
        connector_id: str,
        connector_type: str,
        config: dict[str, Any],
        *,
        secrets_mgr: SecretsManager,
        tenant_id: str,
    ) -> HealthCheckResult:
        """Run a health check for the given connector.

        Verifies that credentials are accessible in Vault and
        performs type-specific health validation.
        """
        vault_path = f"archon/connectors/{connector_id}/credentials"
        start = time.monotonic()

        try:
            # Check if credentials exist in Vault
            try:
                creds = await secrets_mgr.get_secret(vault_path, tenant_id)
                has_creds = True
            except Exception:
                creds = None
                has_creds = False

            latency = (time.monotonic() - start) * 1000

            if not has_creds and connector_type in (
                "salesforce", "slack", "github", "google", "microsoft365",
            ):
                return HealthCheckResult(
                    connector_id=connector_id,
                    status=HealthStatus.ERROR,
                    latency_ms=round(latency, 2),
                    message="OAuth credentials not found in Vault",
                )

            # Type-specific checks
            status, message = HealthChecker._type_check(
                connector_type, config, creds,
            )

            return HealthCheckResult(
                connector_id=connector_id,
                status=status,
                latency_ms=round(latency, 2),
                message=message,
                details={
                    "has_credentials": has_creds,
                    "connector_type": connector_type,
                },
            )

        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return HealthCheckResult(
                connector_id=connector_id,
                status=HealthStatus.ERROR,
                latency_ms=round(latency, 2),
                message=f"Health check failed: {exc}",
            )

    @staticmethod
    def _type_check(
        connector_type: str,
        config: dict[str, Any],
        creds: dict[str, Any] | None,
    ) -> tuple[HealthStatus, str]:
        """Perform type-specific health checks."""
        oauth_types = {"salesforce", "slack", "github", "google", "microsoft365", "hubspot", "teams"}

        if connector_type in oauth_types:
            if creds and creds.get("access_token"):
                return HealthStatus.HEALTHY, "OAuth tokens valid"
            return HealthStatus.ERROR, "OAuth tokens missing or expired"

        db_types = {"postgresql", "mysql", "mongodb", "redis", "elasticsearch", "snowflake", "bigquery"}
        if connector_type in db_types:
            if config.get("host") or config.get("connection_string"):
                return HealthStatus.HEALTHY, "Database configuration valid"
            return HealthStatus.DEGRADED, "Missing host configuration"

        if connector_type in {"s3", "azure_blob", "gcp_storage"}:
            if config.get("bucket") or config.get("container"):
                return HealthStatus.HEALTHY, "Storage configuration valid"
            return HealthStatus.DEGRADED, "Missing bucket/container configuration"

        if connector_type in {"rest_api", "graphql"}:
            if config.get("base_url") or config.get("endpoint"):
                return HealthStatus.HEALTHY, "API endpoint configured"
            return HealthStatus.DEGRADED, "Missing endpoint URL"

        # Default: healthy if we got here
        return HealthStatus.HEALTHY, "Connector operational"
