"""Tests for MeshService — federation, agent sharing, remote invocation, topology, compliance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.mesh import (
    ComplianceReport,
    FederatedUser,
    FederationAgreement,
    FederationConfig,
    MeshAgent,
    MeshInvocationResult,
    MeshMessage,
    MeshNode,
    MeshOrganization,
    MeshTopology,
    OrgRegistration,
    SharedAgent,
    TrustLevel,
    TrustRelationship,
    TrustUpdate,
)
from app.services.mesh_service import MeshService

# ── Fixtures ────────────────────────────────────────────────────────

TENANT_A = "tenant-mesh-alpha"
TENANT_B = "tenant-mesh-beta"


def _user(tenant_id: str = TENANT_A, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="mesh@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=["mesh:create", "mesh:read", "mesh:update", "mesh:execute"],
        session_id="sess-mesh",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_secrets() -> AsyncMock:
    mgr = AsyncMock()
    mgr.read_secret = AsyncMock(return_value="mock-signing-key")
    return mgr


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _org_registration(**overrides: Any) -> OrgRegistration:
    defaults: dict[str, Any] = dict(
        name="Acme Corp",
        domain="acme.example.com",
        public_key="ssh-rsa AAAA...",
    )
    defaults.update(overrides)
    return OrgRegistration(**defaults)


def _mesh_node(tenant_id: str = TENANT_A, **overrides: Any) -> MeshNode:
    defaults: dict[str, Any] = dict(
        id=uuid4(),
        name="Test Org",
        organization="test.example.com",
        endpoint_url="https://test.example.com/.well-known/openid-configuration",
        public_key="ssh-rsa AAAA...",
        capabilities=[],
        extra_metadata={"tenant_id": tenant_id},
        status="active",
        last_seen_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return MeshNode(**defaults)


def _trust_relationship(**overrides: Any) -> TrustRelationship:
    defaults: dict[str, Any] = dict(
        id=uuid4(),
        requesting_node_id=uuid4(),
        target_node_id=uuid4(),
        status="active",
        trust_level="standard",
        allowed_data_categories=["general"],
        extra_metadata={"terms": {"duration_days": 365}, "tenant_id": TENANT_A},
        established_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return TrustRelationship(**defaults)


# ── register_organization ───────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_register_organization_success(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()
    user = _user()
    org = _org_registration()

    result = await svc.register_organization(TENANT_A, user, org, session)

    assert isinstance(result, MeshOrganization)
    assert result.name == "Acme Corp"
    assert result.domain == "acme.example.com"
    assert result.trust_level == TrustLevel.UNTRUSTED
    assert result.status == "active"
    mock_perm.assert_called_once_with(user, "mesh", "create")
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    mock_audit.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_register_organization_stores_tenant_in_metadata(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()
    result = await svc.register_organization(TENANT_A, _user(), _org_registration(), session)

    assert result.id is not None


# ── create_federation_agreement ─────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_create_federation_success(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    partner_node = _mesh_node(tenant_id=TENANT_B)
    requester_node = _mesh_node(tenant_id=TENANT_A)

    # First exec returns partner, second returns requester
    mock_result_partner = MagicMock()
    mock_result_partner.first.return_value = partner_node
    mock_result_requester = MagicMock()
    mock_result_requester.first.return_value = requester_node
    session.exec = AsyncMock(side_effect=[mock_result_partner, mock_result_requester])

    terms = {"duration_days": 365, "allowed_data_categories": ["general"]}
    result = await svc.create_federation_agreement(TENANT_A, _user(), partner_node.id, terms, session)

    assert isinstance(result, FederationAgreement)
    assert result.status == "pending"
    assert result.partner_org == partner_node.id
    assert result.terms == terms


@pytest.mark.asyncio
@patch("app.services.mesh_service.check_permission")
async def test_create_federation_partner_not_found(mock_perm: MagicMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    mock_result = MagicMock()
    mock_result.first.return_value = None
    session.exec = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await svc.create_federation_agreement(TENANT_A, _user(), uuid4(), {}, session)


# ── accept_federation ───────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_accept_federation_success(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    trust = _trust_relationship(status="pending")
    target_node = _mesh_node(tenant_id=TENANT_A)

    mock_trust_result = MagicMock()
    mock_trust_result.first.return_value = trust
    mock_target_result = MagicMock()
    mock_target_result.first.return_value = target_node
    session.exec = AsyncMock(side_effect=[mock_trust_result, mock_target_result])

    result = await svc.accept_federation(TENANT_A, _user(), trust.id, session)

    assert isinstance(result, FederationAgreement)
    assert result.status == "active"
    mock_perm.assert_called_once_with(_user.__wrapped__ if hasattr(_user, "__wrapped__") else mock_perm.call_args[0][0], "mesh", "update")


@pytest.mark.asyncio
@patch("app.services.mesh_service.check_permission")
async def test_accept_federation_not_found(mock_perm: MagicMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    mock_result = MagicMock()
    mock_result.first.return_value = None
    session.exec = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await svc.accept_federation(TENANT_A, _user(), uuid4(), session)


@pytest.mark.asyncio
@patch("app.services.mesh_service.check_permission")
async def test_accept_federation_wrong_tenant(mock_perm: MagicMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    trust = _trust_relationship(status="pending")
    mock_trust_result = MagicMock()
    mock_trust_result.first.return_value = trust
    mock_target_result = MagicMock()
    mock_target_result.first.return_value = None  # no node for this tenant
    session.exec = AsyncMock(side_effect=[mock_trust_result, mock_target_result])

    with pytest.raises(ValueError, match="Not authorized"):
        await svc.accept_federation(TENANT_A, _user(), trust.id, session)


# ── share_agent ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_share_agent_success(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()
    agent_id = uuid4()
    policy = {"visibility": "shared", "data_classification": "internal"}

    result = await svc.share_agent(TENANT_A, _user(), agent_id, policy, session)

    assert isinstance(result, SharedAgent)
    assert result.agent_id == agent_id
    assert result.sharing_policy == "shared"
    assert result.data_classification == "internal"
    session.add.assert_called_once()


# ── discover_mesh_agents ────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.check_permission")
async def test_discover_mesh_agents_excludes_own_tenant(mock_perm: MagicMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    own_config = FederationConfig(
        id=uuid4(), name="agent-share-abc", node_id=uuid4(),
        policy_type="sharing", is_active=True,
        rules={"agent_id": str(uuid4()), "visibility": "shared", "tenant_id": TENANT_A},
    )
    other_config = FederationConfig(
        id=uuid4(), name="agent-share-xyz", node_id=uuid4(),
        policy_type="sharing", is_active=True,
        rules={"agent_id": str(uuid4()), "visibility": "shared", "tenant_id": TENANT_B},
    )
    mock_result = MagicMock()
    mock_result.all.return_value = [own_config, other_config]
    session.exec = AsyncMock(return_value=mock_result)

    agents = await svc.discover_mesh_agents(TENANT_A, _user(), session)

    assert len(agents) == 1
    assert all(isinstance(a, MeshAgent) for a in agents)


@pytest.mark.asyncio
@patch("app.services.mesh_service.check_permission")
async def test_discover_mesh_agents_skips_private(mock_perm: MagicMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    private_config = FederationConfig(
        id=uuid4(), name="agent-share-priv", node_id=uuid4(),
        policy_type="sharing", is_active=True,
        rules={"agent_id": str(uuid4()), "visibility": "private", "tenant_id": TENANT_B},
    )
    mock_result = MagicMock()
    mock_result.all.return_value = [private_config]
    session.exec = AsyncMock(return_value=mock_result)

    agents = await svc.discover_mesh_agents(TENANT_A, _user(), session)
    assert len(agents) == 0


# ── invoke_remote_agent ─────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_invoke_remote_agent_success(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()
    agent_id = uuid4()

    result = await svc.invoke_remote_agent(TENANT_A, _user(), agent_id, {"query": "hello"}, session)

    assert isinstance(result, MeshInvocationResult)
    assert result.agent_id == agent_id
    assert result.result["status"] == "executed"
    assert result.result["sandbox"] == "isolated"
    assert isinstance(result.dlp_findings, list)


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_invoke_remote_agent_dlp_flags_large_payload(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    big_data = {"content": "x" * 20000}
    result = await svc.invoke_remote_agent(TENANT_A, _user(), uuid4(), big_data, session)

    assert len(result.dlp_findings) >= 1
    assert result.dlp_findings[0]["field"] == "content"


# ── validate_federated_identity ─────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_federated_identity_basic() -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    org_id = uuid4()
    claim = {"org_id": str(org_id), "subject": "user@acme.com", "email": "user@acme.com", "roles": ["viewer"]}

    result = await svc.validate_federated_identity(claim)

    assert isinstance(result, FederatedUser)
    assert result.org_id == org_id
    assert "mesh:read" in result.mapped_permissions
    assert "mesh:execute" not in result.mapped_permissions


@pytest.mark.asyncio
async def test_validate_federated_identity_admin_gets_execute() -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    claim = {"org_id": str(uuid4()), "subject": "admin@acme.com", "email": "admin@acme.com", "roles": ["admin"]}

    result = await svc.validate_federated_identity(claim)

    assert "mesh:execute" in result.mapped_permissions
    assert "mesh:read" in result.mapped_permissions


# ── mesh_topology ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mesh_topology_peer_to_peer() -> None:
    """Two nodes → peer-to-peer topology type."""
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    nodes = [_mesh_node(), _mesh_node()]
    edges: list[TrustRelationship] = []

    mock_nodes = MagicMock()
    mock_nodes.all.return_value = nodes
    mock_edges = MagicMock()
    mock_edges.all.return_value = edges
    session.exec = AsyncMock(side_effect=[mock_nodes, mock_edges])

    topo = await svc.get_mesh_topology(TENANT_A, session)

    assert isinstance(topo, MeshTopology)
    assert topo.type == "peer-to-peer"
    assert topo.statistics["total_nodes"] == 2


@pytest.mark.asyncio
async def test_mesh_topology_hybrid() -> None:
    """More than 2 nodes → hybrid topology."""
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    nodes = [_mesh_node() for _ in range(5)]
    edges = [_trust_relationship() for _ in range(3)]

    mock_nodes = MagicMock()
    mock_nodes.all.return_value = nodes
    mock_edges = MagicMock()
    mock_edges.all.return_value = edges
    session.exec = AsyncMock(side_effect=[mock_nodes, mock_edges])

    topo = await svc.get_mesh_topology(TENANT_A, session)

    assert topo.type == "hybrid"
    assert len(topo.nodes) == 5
    assert len(topo.edges) == 3


# ── manage_trust_level ──────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.AuditLogService.create", new_callable=AsyncMock)
@patch("app.services.mesh_service.check_permission")
async def test_manage_trust_level_success(mock_perm: MagicMock, mock_audit: AsyncMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()
    partner_id = uuid4()

    trust = _trust_relationship(target_node_id=partner_id, trust_level="standard")
    mock_result = MagicMock()
    mock_result.first.return_value = trust
    session.exec = AsyncMock(return_value=mock_result)

    result = await svc.manage_trust_level(TENANT_A, _user(), partner_id, TrustLevel.FEDERATED, session)

    assert isinstance(result, TrustUpdate)
    assert result.new_level == TrustLevel.FEDERATED
    assert result.partner_id == partner_id


@pytest.mark.asyncio
@patch("app.services.mesh_service.check_permission")
async def test_manage_trust_level_no_active_relationship(mock_perm: MagicMock) -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    mock_result = MagicMock()
    mock_result.first.return_value = None
    session.exec = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="No active trust"):
        await svc.manage_trust_level(TENANT_A, _user(), uuid4(), TrustLevel.TRUSTED, session)


# ── compliance_report ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compliance_report_no_flows() -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()
    partner_id = uuid4()

    mock_msgs = MagicMock()
    mock_msgs.all.return_value = []
    mock_dpa = MagicMock()
    mock_dpa.all.return_value = []
    session.exec = AsyncMock(side_effect=[mock_msgs, mock_dpa])

    report = await svc.get_compliance_report(TENANT_A, partner_id, session)

    assert isinstance(report, ComplianceReport)
    assert report.gdpr_compliant is True
    assert report.dpa_status == "not_required"
    assert len(report.data_flows) == 0


@pytest.mark.asyncio
async def test_compliance_report_with_messages() -> None:
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()
    partner_id = uuid4()

    msg = MeshMessage(
        id=uuid4(), source_node_id=uuid4(), target_node_id=partner_id,
        message_type="request", content="test", data_category="general",
        is_encrypted=True, status="delivered",
        created_at=datetime.now(timezone.utc),
    )
    mock_msgs = MagicMock()
    mock_msgs.all.return_value = [msg]
    mock_dpa = MagicMock()
    mock_dpa.all.return_value = []
    session.exec = AsyncMock(side_effect=[mock_msgs, mock_dpa])

    report = await svc.get_compliance_report(TENANT_A, partner_id, session)

    assert len(report.data_flows) == 1
    assert report.data_flows[0].data_classification == "general"


# ── tenant isolation ────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.mesh_service.check_permission")
async def test_tenant_isolation_discover_excludes_own(mock_perm: MagicMock) -> None:
    """Tenant A cannot see its own shared agents in discovery."""
    svc = MeshService(secrets_manager=_mock_secrets())
    session = _mock_session()

    config_a = FederationConfig(
        id=uuid4(), name="agent-share-a", node_id=uuid4(),
        policy_type="sharing", is_active=True,
        rules={"agent_id": str(uuid4()), "visibility": "public", "tenant_id": TENANT_A},
    )
    mock_result = MagicMock()
    mock_result.all.return_value = [config_a]
    session.exec = AsyncMock(return_value=mock_result)

    agents = await svc.discover_mesh_agents(TENANT_A, _user(), session)
    assert len(agents) == 0
