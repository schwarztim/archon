"""BaseConnector ABC — defines the interface all connector implementations must satisfy."""

from __future__ import annotations

import abc
from typing import Any


class BaseConnector(abc.ABC):
    """Abstract base class for all connector implementations.

    Subclasses must implement all abstract methods and may override
    ``_build_credentials`` to customise how Vault data is converted
    into connection parameters.
    """

    # Subclasses set this to identify their connector type.
    connector_type: str = ""

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        """Initialise the connector with configuration and credentials.

        Args:
            config: Non-secret configuration (host, port, bucket name, etc.).
            credentials: Secret values loaded from Vault
                (passwords, tokens, API keys).
        """
        self.config = config
        self.credentials = credentials

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Verify that the connector can reach the target system.

        Returns:
            Dict with at minimum ``{"success": bool, "message": str}``.
        """

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return a health-status snapshot for the connector.

        Returns:
            Dict with at minimum ``{"status": str, "latency_ms": float}``.
            ``status`` should be one of ``"healthy"`` / ``"degraded"`` /
            ``"error"`` / ``"unknown"``.
        """

    @abc.abstractmethod
    async def list_resources(self) -> list[dict[str, Any]]:
        """List the top-level resources accessible via this connector.

        For databases this is a list of tables; for S3 it is buckets;
        for Slack it is channels; for Google Drive it is files/folders.

        Returns:
            List of resource descriptor dicts.  Each dict must have at
            minimum ``{"id": str, "name": str}``.
        """

    @abc.abstractmethod
    async def read(self, resource_id: str, params: dict[str, Any] | None = None) -> Any:
        """Read data from the connector.

        Args:
            resource_id: Identifier of the resource to read
                (table name, S3 key, Slack channel ID, etc.).
            params: Optional read parameters (query filters, limit, etc.).

        Returns:
            Resource data — exact shape depends on the connector type.
        """

    @abc.abstractmethod
    async def write(
        self, resource_id: str, data: Any, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Write data via the connector.

        Args:
            resource_id: Identifier of the target resource.
            data: Payload to write.
            params: Optional write parameters.

        Returns:
            Dict describing the write outcome, e.g.
            ``{"success": bool, "written_id": str}``.
        """

    @abc.abstractmethod
    async def get_schema(self, resource_id: str) -> dict[str, Any]:
        """Return the schema / field definitions for a resource.

        Args:
            resource_id: Identifier of the resource whose schema to fetch.

        Returns:
            Dict describing the resource schema, e.g.
            ``{"columns": [{"name": str, "type": str}]}``.
        """

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release any open connections held by the connector.

        Override if the implementation keeps persistent connections
        (e.g. asyncpg pool, httpx client).
        """

    async def __aenter__(self) -> "BaseConnector":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


__all__ = ["BaseConnector"]
