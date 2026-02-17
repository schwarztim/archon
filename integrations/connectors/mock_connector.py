"""MockConnector — in-memory connector for testing the Archon connector framework."""

from __future__ import annotations

import time
from typing import Any

from integrations.connectors.config import ConnectorConfig
from integrations.connectors.framework import (
    ConnectorBase,
    ConnectorStatus,
    HealthCheckResult,
    Resource,
)


class MockConnector(ConnectorBase):
    """A fully in-memory connector used in tests and development.

    Stores data in a plain ``dict`` keyed by resource ID.
    """

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._store: dict[str, list[Any]] = {}
        self._resources: list[Resource] = []

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Simulate establishing a connection."""
        self._status = ConnectorStatus.CONNECTING
        self._logger.info("MockConnector connecting")
        self._status = ConnectorStatus.CONNECTED

    async def disconnect(self) -> None:
        """Simulate closing a connection."""
        self._logger.info("MockConnector disconnecting")
        self._status = ConnectorStatus.DISCONNECTED

    # -- CRUD ---------------------------------------------------------------

    async def read(
        self,
        resource_id: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Return stored data for *resource_id*, or an empty list."""
        if not self.is_connected:
            raise RuntimeError("MockConnector is not connected")
        return self._store.get(resource_id, [])

    async def write(
        self,
        resource_id: str,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Append *data* to the in-memory store under *resource_id*."""
        if not self.is_connected:
            raise RuntimeError("MockConnector is not connected")
        self._store.setdefault(resource_id, []).append(data)
        return {"written": True, "resource_id": resource_id}

    # -- health -------------------------------------------------------------

    async def health_check(self) -> HealthCheckResult:
        """Report health based on current status."""
        start = time.monotonic()
        healthy = self._status == ConnectorStatus.CONNECTED
        latency = (time.monotonic() - start) * 1000
        return HealthCheckResult(
            healthy=healthy,
            status=self._status,
            latency_ms=latency,
            message="ok" if healthy else "not connected",
        )

    # -- discovery ----------------------------------------------------------

    async def list_resources(
        self,
        resource_type: str | None = None,
    ) -> list[Resource]:
        """Return registered mock resources, optionally filtered by type."""
        if resource_type is None:
            return list(self._resources)
        return [r for r in self._resources if r.resource_type == resource_type]

    # -- test helpers -------------------------------------------------------

    def add_resource(self, resource: Resource) -> None:
        """Register a resource for discovery (test helper)."""
        self._resources.append(resource)

    def seed_data(self, resource_id: str, items: list[Any]) -> None:
        """Pre-populate the in-memory store (test helper)."""
        self._store[resource_id] = list(items)
