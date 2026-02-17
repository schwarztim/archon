"""Tests for ConnectorBase, ConnectorConfig, and MockConnector."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure project root is importable so absolute imports like
# ``from integrations.connectors.framework import …`` resolve correctly.
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from integrations.connectors.config import (
    AuthType,
    ConnectorAuthConfig,
    ConnectorConfig,
    RateLimitConfig,
    RetryConfig,
)
from integrations.connectors.framework import (
    ConnectorBase,
    ConnectorStatus,
    HealthCheckResult,
    Resource,
)
from integrations.connectors.mock_connector import MockConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def minimal_config() -> ConnectorConfig:
    """Minimal valid ConnectorConfig."""
    return ConnectorConfig(connector_type="mock", name="test-mock")


@pytest.fixture()
def full_config() -> ConnectorConfig:
    """ConnectorConfig with all optional fields populated."""
    return ConnectorConfig(
        connector_type="mock",
        name="full-mock",
        description="A fully-configured mock connector",
        base_url="https://mock.example.com",
        auth=ConnectorAuthConfig(
            auth_type=AuthType.API_KEY,
            api_key="super-secret",
        ),
        retry=RetryConfig(max_retries=5, base_delay_seconds=2.0),
        rate_limit=RateLimitConfig(requests_per_second=10.0),
        timeout_seconds=15.0,
        extra={"custom_flag": True},
    )


@pytest.fixture()
def mock_connector(minimal_config: ConnectorConfig) -> MockConnector:
    """A disconnected MockConnector instance."""
    return MockConnector(minimal_config)


@pytest_asyncio.fixture()
async def connected_connector(mock_connector: MockConnector) -> MockConnector:
    """A MockConnector that has already called ``connect()``."""
    await mock_connector.connect()
    return mock_connector


# ---------------------------------------------------------------------------
# ConnectorConfig validation tests
# ---------------------------------------------------------------------------

class TestConnectorConfig:
    """Tests for Pydantic ConnectorConfig model."""

    def test_minimal_config_valid(self, minimal_config: ConnectorConfig) -> None:
        """Minimal required fields produce a valid config."""
        assert minimal_config.connector_type == "mock"
        assert minimal_config.name == "test-mock"
        assert minimal_config.timeout_seconds == 30.0

    def test_full_config_valid(self, full_config: ConnectorConfig) -> None:
        """All optional fields are stored correctly."""
        assert full_config.description == "A fully-configured mock connector"
        assert full_config.base_url == "https://mock.example.com"
        assert full_config.auth.auth_type == AuthType.API_KEY
        assert full_config.retry.max_retries == 5
        assert full_config.rate_limit.requests_per_second == 10.0
        assert full_config.timeout_seconds == 15.0
        assert full_config.extra == {"custom_flag": True}

    def test_missing_connector_type_raises(self) -> None:
        """connector_type is required — omitting it raises ValidationError."""
        with pytest.raises(Exception):
            ConnectorConfig(name="no-type")  # type: ignore[call-arg]

    def test_missing_name_raises(self) -> None:
        """name is required — omitting it raises ValidationError."""
        with pytest.raises(Exception):
            ConnectorConfig(connector_type="x")  # type: ignore[call-arg]

    def test_empty_connector_type_raises(self) -> None:
        """Empty string for connector_type is rejected by min_length=1."""
        with pytest.raises(Exception):
            ConnectorConfig(connector_type="", name="bad")

    def test_empty_name_raises(self) -> None:
        """Empty string for name is rejected by min_length=1."""
        with pytest.raises(Exception):
            ConnectorConfig(connector_type="x", name="")

    def test_negative_timeout_raises(self) -> None:
        """timeout_seconds must be > 0."""
        with pytest.raises(Exception):
            ConnectorConfig(connector_type="x", name="t", timeout_seconds=-1)

    def test_retry_max_retries_bounds(self) -> None:
        """max_retries must be 0..10."""
        with pytest.raises(Exception):
            RetryConfig(max_retries=20)

    def test_defaults_populated(self, minimal_config: ConnectorConfig) -> None:
        """Default sub-models are created automatically."""
        assert minimal_config.auth.auth_type == AuthType.NONE
        assert minimal_config.retry.max_retries == 3
        assert minimal_config.rate_limit.burst_size == 10


# ---------------------------------------------------------------------------
# ConnectorBase interface tests
# ---------------------------------------------------------------------------

class TestConnectorBaseInterface:
    """Verify ConnectorBase cannot be instantiated directly and enforces ABC."""

    def test_cannot_instantiate_abc(self, minimal_config: ConnectorConfig) -> None:
        """ConnectorBase is abstract — direct instantiation must fail."""
        with pytest.raises(TypeError):
            ConnectorBase(minimal_config)  # type: ignore[abstract]

    def test_subclass_must_implement_all_methods(
        self, minimal_config: ConnectorConfig
    ) -> None:
        """A subclass missing abstract methods cannot be instantiated."""

        class IncompleteConnector(ConnectorBase):
            pass

        with pytest.raises(TypeError):
            IncompleteConnector(minimal_config)  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# MockConnector lifecycle tests
# ---------------------------------------------------------------------------

class TestMockConnectorLifecycle:
    """Lifecycle (connect / disconnect / status) tests."""

    def test_initial_status_disconnected(self, mock_connector: MockConnector) -> None:
        """Freshly created connector starts DISCONNECTED."""
        assert mock_connector.status == ConnectorStatus.DISCONNECTED
        assert mock_connector.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_sets_connected(self, mock_connector: MockConnector) -> None:
        """Calling connect() transitions status to CONNECTED."""
        await mock_connector.connect()
        assert mock_connector.status == ConnectorStatus.CONNECTED
        assert mock_connector.is_connected is True

    @pytest.mark.asyncio
    async def test_disconnect_sets_disconnected(
        self, connected_connector: MockConnector
    ) -> None:
        """Calling disconnect() transitions status back to DISCONNECTED."""
        await connected_connector.disconnect()
        assert connected_connector.status == ConnectorStatus.DISCONNECTED
        assert connected_connector.is_connected is False

    @pytest.mark.asyncio
    async def test_reconnect_cycle(self, mock_connector: MockConnector) -> None:
        """Connect → disconnect → connect produces correct states."""
        await mock_connector.connect()
        assert mock_connector.is_connected
        await mock_connector.disconnect()
        assert not mock_connector.is_connected
        await mock_connector.connect()
        assert mock_connector.is_connected

    def test_repr(self, mock_connector: MockConnector) -> None:
        """__repr__ includes class name, type, name, and status."""
        r = repr(mock_connector)
        assert "MockConnector" in r
        assert "mock" in r
        assert "test-mock" in r
        assert "disconnected" in r


# ---------------------------------------------------------------------------
# MockConnector read / write tests
# ---------------------------------------------------------------------------

class TestMockConnectorReadWrite:
    """Data read/write operations."""

    @pytest.mark.asyncio
    async def test_read_empty_resource(
        self, connected_connector: MockConnector
    ) -> None:
        """Reading a nonexistent resource returns an empty list."""
        result = await connected_connector.read("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_write_then_read(
        self, connected_connector: MockConnector
    ) -> None:
        """Written data is returned by subsequent read."""
        await connected_connector.write("chan-1", {"text": "hello"})
        data = await connected_connector.read("chan-1")
        assert len(data) == 1
        assert data[0] == {"text": "hello"}

    @pytest.mark.asyncio
    async def test_multiple_writes_accumulate(
        self, connected_connector: MockConnector
    ) -> None:
        """Multiple writes to the same resource accumulate."""
        await connected_connector.write("chan-1", "a")
        await connected_connector.write("chan-1", "b")
        data = await connected_connector.read("chan-1")
        assert data == ["a", "b"]

    @pytest.mark.asyncio
    async def test_write_returns_confirmation(
        self, connected_connector: MockConnector
    ) -> None:
        """write() returns a confirmation dict."""
        result = await connected_connector.write("r1", "payload")
        assert result["written"] is True
        assert result["resource_id"] == "r1"

    @pytest.mark.asyncio
    async def test_read_when_disconnected_raises(
        self, mock_connector: MockConnector
    ) -> None:
        """read() raises RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="not connected"):
            await mock_connector.read("any")

    @pytest.mark.asyncio
    async def test_write_when_disconnected_raises(
        self, mock_connector: MockConnector
    ) -> None:
        """write() raises RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="not connected"):
            await mock_connector.write("any", "data")

    @pytest.mark.asyncio
    async def test_seed_data_helper(
        self, connected_connector: MockConnector
    ) -> None:
        """seed_data() pre-populates the store."""
        connected_connector.seed_data("seeded", [1, 2, 3])
        data = await connected_connector.read("seeded")
        assert data == [1, 2, 3]


# ---------------------------------------------------------------------------
# MockConnector health_check tests
# ---------------------------------------------------------------------------

class TestMockConnectorHealthCheck:
    """Health-check behaviour."""

    @pytest.mark.asyncio
    async def test_healthy_when_connected(
        self, connected_connector: MockConnector
    ) -> None:
        """health_check reports healthy when status is CONNECTED."""
        result = await connected_connector.health_check()
        assert result.healthy is True
        assert result.status == ConnectorStatus.CONNECTED
        assert result.message == "ok"
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_unhealthy_when_disconnected(
        self, mock_connector: MockConnector
    ) -> None:
        """health_check reports unhealthy when status is DISCONNECTED."""
        result = await mock_connector.health_check()
        assert result.healthy is False
        assert result.status == ConnectorStatus.DISCONNECTED
        assert result.message == "not connected"

    @pytest.mark.asyncio
    async def test_health_check_result_has_timestamp(
        self, connected_connector: MockConnector
    ) -> None:
        """HealthCheckResult includes a UTC checked_at timestamp."""
        result = await connected_connector.health_check()
        assert result.checked_at is not None
        assert result.checked_at.tzinfo is not None

    def test_health_check_result_immutable(self) -> None:
        """HealthCheckResult is frozen — attributes cannot be reassigned."""
        hcr = HealthCheckResult(
            healthy=True,
            status=ConnectorStatus.CONNECTED,
            latency_ms=1.0,
            message="ok",
        )
        with pytest.raises(AttributeError):
            hcr.healthy = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MockConnector list_resources tests
# ---------------------------------------------------------------------------

class TestMockConnectorResources:
    """Resource discovery tests."""

    @pytest.mark.asyncio
    async def test_list_resources_empty(
        self, mock_connector: MockConnector
    ) -> None:
        """No resources registered → empty list."""
        resources = await mock_connector.list_resources()
        assert resources == []

    @pytest.mark.asyncio
    async def test_list_resources_returns_added(
        self, mock_connector: MockConnector
    ) -> None:
        """Added resources are returned by list_resources."""
        r1 = Resource(id="ch-1", name="general", resource_type="channel")
        r2 = Resource(id="tbl-1", name="users", resource_type="table")
        mock_connector.add_resource(r1)
        mock_connector.add_resource(r2)
        resources = await mock_connector.list_resources()
        assert len(resources) == 2

    @pytest.mark.asyncio
    async def test_list_resources_filter_by_type(
        self, mock_connector: MockConnector
    ) -> None:
        """Filtering by resource_type returns only matching resources."""
        mock_connector.add_resource(
            Resource(id="ch-1", name="general", resource_type="channel")
        )
        mock_connector.add_resource(
            Resource(id="tbl-1", name="users", resource_type="table")
        )
        channels = await mock_connector.list_resources(resource_type="channel")
        assert len(channels) == 1
        assert channels[0].resource_type == "channel"

    @pytest.mark.asyncio
    async def test_list_resources_filter_no_match(
        self, mock_connector: MockConnector
    ) -> None:
        """Filtering by a non-existent type returns empty list."""
        mock_connector.add_resource(
            Resource(id="ch-1", name="general", resource_type="channel")
        )
        result = await mock_connector.list_resources(resource_type="repo")
        assert result == []

    def test_resource_is_frozen(self) -> None:
        """Resource dataclass is immutable."""
        r = Resource(id="x", name="y", resource_type="z")
        with pytest.raises(AttributeError):
            r.id = "changed"  # type: ignore[misc]

    def test_resource_metadata_default(self) -> None:
        """Resource metadata defaults to an empty dict."""
        r = Resource(id="x", name="y", resource_type="z")
        assert r.metadata == {}
