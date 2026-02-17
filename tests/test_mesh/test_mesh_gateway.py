"""Unit tests for MeshGateway service.

Every DB interaction is mocked via AsyncSession so no real database is needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.models.mesh import MeshMessage, MeshNode, TrustRelationship
from app.services.mesh import MeshGateway


# ── Constants (valid hex UUIDs only) ────────────────────────────────

NODE_A_ID = UUID("aabbccdd-1122-3344-5566-778899aabbcc")
NODE_B_ID = UUID("11223344-aabb-ccdd-eeff-001122334455")
TRUST_ID = UUID("aabb0011-2233-4455-6677-8899aabbccdd")
MSG_ID = UUID("ddeeff00-1122-3344-5566-778899001122")
MISSING_ID = UUID("00000000-aaaa-bbbb-cccc-ddddeeeeffff")
CORRELATION_ID = UUID("aabbccdd-eeff-0011-2233-445566778899")


# ── Factories ───────────────────────────────────────────────────────


def _make_node(
    *,
    node_id: UUID = NODE_A_ID,
    name: str = "node-alpha",
    organization: str = "org-alpha",
    endpoint_url: str = "https://alpha.example.com/mesh",
    public_key: str = "ssh-ed25519-AAAA-alpha",
    status: str = "active",
    capabilities: list[str] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> MeshNode:
    """Factory for MeshNode instances."""
    return MeshNode(
        id=node_id,
        name=name,
        organization=organization,
        endpoint_url=endpoint_url,
        public_key=public_key,
        status=status,
        capabilities=capabilities or [],
        extra_metadata=extra_metadata or {},
    )


def _make_trust(
    *,
    trust_id: UUID = TRUST_ID,
    requesting_node_id: UUID = NODE_A_ID,
    target_node_id: UUID = NODE_B_ID,
    status: str = "active",
    trust_level: str = "standard",
    allowed_data_categories: list[str] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> TrustRelationship:
    """Factory for TrustRelationship instances."""
    return TrustRelationship(
        id=trust_id,
        requesting_node_id=requesting_node_id,
        target_node_id=target_node_id,
        status=status,
        trust_level=trust_level,
        allowed_data_categories=allowed_data_categories or [],
        extra_metadata=extra_metadata or {},
    )


def _make_message(
    *,
    msg_id: UUID = MSG_ID,
    source_node_id: UUID = NODE_A_ID,
    target_node_id: UUID = NODE_B_ID,
    content: str = "hello mesh",
    message_type: str = "request",
    data_category: str | None = None,
    status: str = "delivered",
) -> MeshMessage:
    """Factory for MeshMessage instances."""
    return MeshMessage(
        id=msg_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        content=content,
        message_type=message_type,
        data_category=data_category,
        status=status,
    )


# ── Mock helpers ────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Return a fully-mocked AsyncSession with common methods."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock()
    session.exec = AsyncMock()
    return session


def _mock_exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object returned by session.exec()."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


# ── register_node ───────────────────────────────────────────────────


class TestRegisterNode:
    """Tests for MeshGateway.register_node."""

    @pytest.mark.asyncio
    async def test_register_node_creates_and_commits(self) -> None:
        """Node is added, committed, and refreshed."""
        session = _mock_session()

        result = await MeshGateway.register_node(
            session,
            name="node-alpha",
            organization="org-alpha",
            endpoint_url="https://alpha.example.com/mesh",
            public_key="ssh-ed25519-AAAA-alpha",
        )

        assert isinstance(result, MeshNode)
        assert result.name == "node-alpha"
        assert result.organization == "org-alpha"
        assert result.endpoint_url == "https://alpha.example.com/mesh"
        assert result.public_key == "ssh-ed25519-AAAA-alpha"
        assert result.status == "active"
        assert result.capabilities == []
        assert result.extra_metadata == {}
        assert result.last_seen_at is not None
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_node_with_capabilities_and_metadata(self) -> None:
        """Capabilities and extra_metadata are stored on the node."""
        session = _mock_session()
        caps = ["routing", "scheduling"]
        meta = {"region": "us-east-1"}

        result = await MeshGateway.register_node(
            session,
            name="node-beta",
            organization="org-beta",
            endpoint_url="https://beta.example.com/mesh",
            public_key="ssh-ed25519-BBBB-beta",
            capabilities=caps,
            extra_metadata=meta,
        )

        assert result.capabilities == caps
        assert result.extra_metadata == meta

    @pytest.mark.asyncio
    async def test_register_node_defaults_empty_collections(self) -> None:
        """When capabilities/extra_metadata are None, they default to empty."""
        session = _mock_session()

        result = await MeshGateway.register_node(
            session,
            name="n",
            organization="o",
            endpoint_url="https://x.example.com",
            public_key="key",
            capabilities=None,
            extra_metadata=None,
        )

        assert result.capabilities == []
        assert result.extra_metadata == {}


# ── establish_trust ─────────────────────────────────────────────────


class TestEstablishTrust:
    """Tests for MeshGateway.establish_trust."""

    @pytest.mark.asyncio
    async def test_establish_trust_success(self) -> None:
        """Trust is created when both nodes exist."""
        session = _mock_session()
        node_a = _make_node(node_id=NODE_A_ID)
        node_b = _make_node(node_id=NODE_B_ID, name="node-beta", organization="org-beta")
        session.get = AsyncMock(side_effect=[node_a, node_b])

        result = await MeshGateway.establish_trust(
            session,
            requesting_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
        )

        assert isinstance(result, TrustRelationship)
        assert result.requesting_node_id == NODE_A_ID
        assert result.target_node_id == NODE_B_ID
        assert result.status == "active"
        assert result.trust_level == "standard"
        assert result.established_at is not None
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_establish_trust_with_custom_level_and_categories(self) -> None:
        """Custom trust_level and allowed_data_categories are stored."""
        session = _mock_session()
        session.get = AsyncMock(side_effect=[_make_node(), _make_node(node_id=NODE_B_ID)])

        result = await MeshGateway.establish_trust(
            session,
            requesting_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            trust_level="elevated",
            allowed_data_categories=["telemetry", "logs"],
            extra_metadata={"approved_by": "admin"},
        )

        assert result.trust_level == "elevated"
        assert result.allowed_data_categories == ["telemetry", "logs"]
        assert result.extra_metadata == {"approved_by": "admin"}

    @pytest.mark.asyncio
    async def test_establish_trust_requesting_node_not_found(self) -> None:
        """ValueError raised when requesting node does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Requesting node .* not found"):
            await MeshGateway.establish_trust(
                session,
                requesting_node_id=MISSING_ID,
                target_node_id=NODE_B_ID,
            )

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_establish_trust_target_node_not_found(self) -> None:
        """ValueError raised when target node does not exist."""
        session = _mock_session()
        session.get = AsyncMock(side_effect=[_make_node(), None])

        with pytest.raises(ValueError, match="Target node .* not found"):
            await MeshGateway.establish_trust(
                session,
                requesting_node_id=NODE_A_ID,
                target_node_id=MISSING_ID,
            )

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_establish_trust_defaults_empty_categories(self) -> None:
        """allowed_data_categories defaults to empty list when None."""
        session = _mock_session()
        session.get = AsyncMock(side_effect=[_make_node(), _make_node(node_id=NODE_B_ID)])

        result = await MeshGateway.establish_trust(
            session,
            requesting_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            allowed_data_categories=None,
        )

        assert result.allowed_data_categories == []


# ── send_message (with data isolation enforcement) ──────────────────


class TestSendMessage:
    """Tests for MeshGateway.send_message including data isolation."""

    @pytest.mark.asyncio
    async def test_send_message_success(self) -> None:
        """Message is delivered when active trust exists."""
        session = _mock_session()
        trust = _make_trust()
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        result = await MeshGateway.send_message(
            session,
            source_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            content="hello mesh",
        )

        assert isinstance(result, MeshMessage)
        assert result.source_node_id == NODE_A_ID
        assert result.target_node_id == NODE_B_ID
        assert result.content == "hello mesh"
        assert result.message_type == "request"
        assert result.status == "delivered"
        assert result.delivered_at is not None
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_no_trust_raises(self) -> None:
        """ValueError raised when no active trust exists."""
        session = _mock_session()
        exec_result = _mock_exec_result([])
        session.exec.return_value = exec_result

        with pytest.raises(ValueError, match="No active trust relationship"):
            await MeshGateway.send_message(
                session,
                source_node_id=NODE_A_ID,
                target_node_id=NODE_B_ID,
                content="unauthorized",
            )

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_message_allowed_data_category(self) -> None:
        """Message succeeds when data_category is in allowed list."""
        session = _mock_session()
        trust = _make_trust(allowed_data_categories=["telemetry", "logs"])
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        result = await MeshGateway.send_message(
            session,
            source_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            content="telemetry data",
            data_category="telemetry",
        )

        assert result.data_category == "telemetry"
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_blocked_data_category(self) -> None:
        """ValueError raised when data_category is NOT in allowed list."""
        session = _mock_session()
        trust = _make_trust(allowed_data_categories=["telemetry", "logs"])
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        with pytest.raises(ValueError, match="Data category 'pii' not allowed"):
            await MeshGateway.send_message(
                session,
                source_node_id=NODE_A_ID,
                target_node_id=NODE_B_ID,
                content="sensitive",
                data_category="pii",
            )

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_message_no_category_with_restricted_trust(self) -> None:
        """Message without data_category passes even if trust has restrictions."""
        session = _mock_session()
        trust = _make_trust(allowed_data_categories=["telemetry"])
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        result = await MeshGateway.send_message(
            session,
            source_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            content="no category",
        )

        assert result.data_category is None
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_any_category_when_trust_has_no_restrictions(self) -> None:
        """When allowed_data_categories is empty, any category is allowed."""
        session = _mock_session()
        trust = _make_trust(allowed_data_categories=[])
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        result = await MeshGateway.send_message(
            session,
            source_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            content="anything goes",
            data_category="pii",
        )

        assert result.data_category == "pii"
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_with_correlation_id_and_metadata(self) -> None:
        """correlation_id and extra_metadata are stored on the message."""
        session = _mock_session()
        trust = _make_trust()
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        result = await MeshGateway.send_message(
            session,
            source_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            content="correlated",
            message_type="response",
            correlation_id=CORRELATION_ID,
            extra_metadata={"trace": "abc"},
        )

        assert result.correlation_id == CORRELATION_ID
        assert result.extra_metadata == {"trace": "abc"}
        assert result.message_type == "response"

    @pytest.mark.asyncio
    async def test_send_message_defaults_metadata_to_empty(self) -> None:
        """extra_metadata defaults to empty dict when None."""
        session = _mock_session()
        trust = _make_trust()
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        result = await MeshGateway.send_message(
            session,
            source_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            content="x",
            extra_metadata=None,
        )

        assert result.extra_metadata == {}


# ── revoke_trust ────────────────────────────────────────────────────


class TestRevokeTrust:
    """Tests for MeshGateway.revoke_trust."""

    @pytest.mark.asyncio
    async def test_revoke_trust_success(self) -> None:
        """Trust is revoked when it exists."""
        session = _mock_session()
        trust = _make_trust(status="active")
        session.get.return_value = trust

        result = await MeshGateway.revoke_trust(session, TRUST_ID)

        assert result is not None
        assert result.status == "revoked"
        assert result.revoked_at is not None
        assert result.updated_at is not None
        session.add.assert_called_once_with(trust)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_revoke_trust_not_found(self) -> None:
        """Returns None when trust relationship does not exist."""
        session = _mock_session()
        session.get.return_value = None

        result = await MeshGateway.revoke_trust(session, MISSING_ID)

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoke_trust_already_revoked(self) -> None:
        """Revoking an already-revoked trust still updates timestamps."""
        session = _mock_session()
        trust = _make_trust(status="revoked")
        session.get.return_value = trust

        result = await MeshGateway.revoke_trust(session, TRUST_ID)

        assert result is not None
        assert result.status == "revoked"
        session.commit.assert_awaited_once()


# ── list_peers ──────────────────────────────────────────────────────


class TestListPeers:
    """Tests for MeshGateway.list_peers."""

    @pytest.mark.asyncio
    async def test_list_peers_returns_tuple(self) -> None:
        """Returns (list[MeshNode], total_count)."""
        session = _mock_session()
        node = _make_node()
        count_result = _mock_exec_result([node])
        page_result = _mock_exec_result([node])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        nodes, total = await MeshGateway.list_peers(session)

        assert total == 1
        assert nodes == [node]

    @pytest.mark.asyncio
    async def test_list_peers_empty(self) -> None:
        """Returns empty list and 0 total when no nodes exist."""
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        nodes, total = await MeshGateway.list_peers(session)

        assert total == 0
        assert nodes == []

    @pytest.mark.asyncio
    async def test_list_peers_with_status_filter(self) -> None:
        """Status filter is applied to the query."""
        session = _mock_session()
        active_node = _make_node(status="active")
        count_result = _mock_exec_result([active_node])
        page_result = _mock_exec_result([active_node])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        nodes, total = await MeshGateway.list_peers(session, status="active")

        assert total == 1
        assert nodes == [active_node]
        assert session.exec.await_count == 2

    @pytest.mark.asyncio
    async def test_list_peers_with_organization_filter(self) -> None:
        """Organization filter is applied to the query."""
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        nodes, total = await MeshGateway.list_peers(
            session, organization="org-alpha"
        )

        assert total == 0
        assert nodes == []
        assert session.exec.await_count == 2

    @pytest.mark.asyncio
    async def test_list_peers_respects_pagination(self) -> None:
        """limit and offset are forwarded to the query."""
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        await MeshGateway.list_peers(session, limit=5, offset=10)

        assert session.exec.await_count == 2

    @pytest.mark.asyncio
    async def test_list_peers_multiple_nodes(self) -> None:
        """Returns multiple nodes correctly."""
        session = _mock_session()
        node_a = _make_node(node_id=NODE_A_ID, name="alpha")
        node_b = _make_node(node_id=NODE_B_ID, name="beta")
        count_result = _mock_exec_result([node_a, node_b])
        page_result = _mock_exec_result([node_a, node_b])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        nodes, total = await MeshGateway.list_peers(session)

        assert total == 2
        assert len(nodes) == 2


# ── Edge Cases / Cross-Cutting ──────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_send_message_empty_content(self) -> None:
        """Empty string content is valid."""
        session = _mock_session()
        trust = _make_trust()
        exec_result = _mock_exec_result([trust])
        session.exec.return_value = exec_result

        result = await MeshGateway.send_message(
            session,
            source_node_id=NODE_A_ID,
            target_node_id=NODE_B_ID,
            content="",
        )

        assert result.content == ""

    @pytest.mark.asyncio
    async def test_get_node_found(self) -> None:
        """get_node returns the node when it exists."""
        session = _mock_session()
        node = _make_node()
        session.get.return_value = node

        result = await MeshGateway.get_node(session, NODE_A_ID)

        assert result is node
        session.get.assert_awaited_once_with(MeshNode, NODE_A_ID)

    @pytest.mark.asyncio
    async def test_get_node_not_found(self) -> None:
        """get_node returns None when the node does not exist."""
        session = _mock_session()
        session.get.return_value = None

        result = await MeshGateway.get_node(session, MISSING_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_trust_found(self) -> None:
        """get_trust returns the trust when it exists."""
        session = _mock_session()
        trust = _make_trust()
        session.get.return_value = trust

        result = await MeshGateway.get_trust(session, TRUST_ID)

        assert result is trust

    @pytest.mark.asyncio
    async def test_get_trust_not_found(self) -> None:
        """get_trust returns None when trust does not exist."""
        session = _mock_session()
        session.get.return_value = None

        result = await MeshGateway.get_trust(session, MISSING_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_message_found(self) -> None:
        """get_message returns the message when it exists."""
        session = _mock_session()
        msg = _make_message()
        session.get.return_value = msg

        result = await MeshGateway.get_message(session, MSG_ID)

        assert result is msg

    @pytest.mark.asyncio
    async def test_get_message_not_found(self) -> None:
        """get_message returns None when message does not exist."""
        session = _mock_session()
        session.get.return_value = None

        result = await MeshGateway.get_message(session, MISSING_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_register_node_empty_string_name(self) -> None:
        """Empty string name is still accepted (validation is upstream)."""
        session = _mock_session()

        result = await MeshGateway.register_node(
            session,
            name="",
            organization="org",
            endpoint_url="https://x.example.com",
            public_key="key",
        )

        assert result.name == ""
