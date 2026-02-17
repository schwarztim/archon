"""ConnectorBase — abstract base class that every Archon data connector implements."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from integrations.connectors.config import ConnectorConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class ConnectorStatus(str, Enum):
    """Lifecycle states of a connector instance."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class HealthCheckResult:
    """Immutable result returned by ``health_check``."""

    healthy: bool
    status: ConnectorStatus
    latency_ms: float | None = None
    message: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class Resource:
    """A discoverable resource exposed by a connector (table, channel, repo, …)."""

    id: str
    name: str
    resource_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ConnectorBase ABC
# ---------------------------------------------------------------------------

class ConnectorBase(ABC):
    """Abstract base class for all Archon data connectors.

    Subclasses **must** implement every ``@abstractmethod``.  The base class
    provides status tracking, logging, and a consistent lifecycle.

    Typical usage::

        class SlackConnector(ConnectorBase):
            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def read(self, resource_id, params=None) -> Any: ...
            async def write(self, resource_id, data, params=None) -> Any: ...
            async def health_check(self) -> HealthCheckResult: ...
            async def list_resources(self, resource_type=None) -> list[Resource]: ...
    """

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config
        self._status: ConnectorStatus = ConnectorStatus.DISCONNECTED
        self._logger = logging.getLogger(
            f"{__name__}.{config.connector_type}.{config.name}"
        )

    # -- properties ---------------------------------------------------------

    @property
    def status(self) -> ConnectorStatus:
        """Current lifecycle status of the connector."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """``True`` when the connector has an active connection."""
        return self._status == ConnectorStatus.CONNECTED

    # -- abstract interface -------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the remote data source.

        Implementations should set ``self._status`` to ``CONNECTED`` on
        success or ``ERROR`` on failure.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the connection.

        Implementations should set ``self._status`` to ``DISCONNECTED``.
        """

    @abstractmethod
    async def read(
        self,
        resource_id: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Read data from *resource_id* (e.g. a channel, table, or endpoint).

        Args:
            resource_id: Identifier for the resource to read.
            params: Optional provider-specific query parameters.

        Returns:
            Provider-specific data payload.
        """

    @abstractmethod
    async def write(
        self,
        resource_id: str,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Write *data* to *resource_id*.

        Args:
            resource_id: Identifier for the target resource.
            data: Payload to write.
            params: Optional provider-specific parameters.

        Returns:
            Provider-specific write result / confirmation.
        """

    @abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """Probe the remote service and report health status.

        Returns:
            A ``HealthCheckResult`` with current health information.
        """

    @abstractmethod
    async def list_resources(
        self,
        resource_type: str | None = None,
    ) -> list[Resource]:
        """Enumerate resources available through this connector.

        Args:
            resource_type: Optional filter (e.g. ``"channel"``, ``"table"``).

        Returns:
            List of ``Resource`` objects.
        """

    # -- convenience --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"type={self.config.connector_type!r} "
            f"name={self.config.name!r} "
            f"status={self._status.value}>"
        )
