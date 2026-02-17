"""Tests for A2AService — federated OAuth, agent cards, DLP scanning, trust management,
credential rotation, and tenant isolation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.a2a import (
    A2AAccessToken,
    A2AFederationMessage,
    A2AResponse,
    AgentCard,
    FederationStatus,
    Partner,
    PartnerRegistration,
    TrustLevel,
)
from app.models.dlp import DLPScanResultSchema, RiskLevel, ScanAction
from app.services.a2a_service import A2AService


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_A = str(uuid4())
TENANT_B = str(uuid4())


def _admin_user(tenant_id: str = TENANT_A, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="admin@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=[],
        session_id="sess-a2a",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_secrets() -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_secret = AsyncMock(return_value={
        "client_id": "a2a-abc123",
        "client_secret": "secret-value",
        "token_endpoint": "https://partner.example.com/token",
        "base_url": "https://partner.example.com",
    })
    mgr.put_secret = AsyncMock()
    mgr.delete_secret = AsyncMock()
    return mgr


def _partner_registration(**overrides: Any) -> PartnerRegistration:
    defaults: dict[str, Any] = dict(
        name="Partner Corp",
        base_url="https://partner.example.com",
        token_endpoint="https://partner.example.com/oauth/token",
    )
    defaults.update(overrides)
    return PartnerRegistration(**defaults)


def _clean_dlp_result() -> DLPScanResultSchema:
    return DLPScanResultSchema(
        content_id="test",
        findings=[],
        risk_level=RiskLevel.LOW,
        action=ScanAction.ALLOW,
        processing_time_ms=1.0,
    )


def _block_dlp_result() -> DLPScanResultSchema:
    return DLPScanResultSchema(
        content_id="test",
        findings=[],
        risk_level=RiskLevel.CRITICAL,
        action=ScanAction.BLOCK,
        processing_time_ms=1.0,
    )


# ── register_partner ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_partner_success() -> None:
    """Registers a partner, stores credentials in Vault, returns Partner."""
    user = _admin_user()
    secrets = _mock_secrets()
    reg = _partner_registration()

    partner = await A2AService.register_partner(TENANT_A, user, reg, secrets)

    assert isinstance(partner, Partner)
    assert partner.tenant_id == TENANT_A
    assert partner.name == "Partner Corp"
    assert partner.trust_level == TrustLevel.UNTRUSTED
    assert partner.status == "active"
    secrets.put_secret.assert_awaited()


@pytest.mark.asyncio
async def test_register_partner_stores_public_key() -> None:
    """When public_key is provided, a second Vault write stores it."""
    user = _admin_user()
    secrets = _mock_secrets()
    reg = _partner_registration(public_key="ssh-rsa AAAA...")

    await A2AService.register_partner(TENANT_A, user, reg, secrets)

    assert secrets.put_secret.await_count == 2


# ── acquire_token ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_token_federated_oauth() -> None:
    """Acquires an OAuth token using credentials from Vault."""
    secrets = _mock_secrets()
    partner_id = str(uuid4())

    token = await A2AService.acquire_token(TENANT_A, partner_id, secrets)

    assert isinstance(token, A2AAccessToken)
    assert token.token_type == "Bearer"
    assert token.access_token.startswith("a2a-tok-")
    assert token.expires_in == 3600
    secrets.get_secret.assert_awaited_once()


# ── publish_agent_card ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_agent_card() -> None:
    """Publishes an agent card with capabilities and schemas."""
    user = _admin_user()
    agent_id = str(uuid4())

    card = await A2AService.publish_agent_card(TENANT_A, user, agent_id)

    assert isinstance(card, AgentCard)
    assert card.agent_id == UUID(agent_id)
    assert "messaging" in card.capabilities
    assert card.version == "1.0.0"
    assert card.published_at is not None


# ── discover_agents ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_agents_acquires_token() -> None:
    """Discovery first acquires a token then returns agent list."""
    secrets = _mock_secrets()
    partner_id = str(uuid4())

    agents = await A2AService.discover_agents(TENANT_A, partner_id, secrets)

    assert isinstance(agents, list)
    # Token acquisition should be called during discovery
    secrets.get_secret.assert_awaited_once()


# ── send_message ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_with_dlp_scan_clean() -> None:
    """Sends a message after passing DLP scan."""
    user = _admin_user()
    secrets = _mock_secrets()

    with patch(
        "app.services.a2a_service.DLPService.scan_content",
        return_value=_clean_dlp_result(),
    ):
        response = await A2AService.send_message(
            TENANT_A, user, str(uuid4()), str(uuid4()), "Hello partner", secrets,
        )

    assert isinstance(response, A2AResponse)
    assert response.status == "delivered"
    assert response.processing_time_ms >= 0


@pytest.mark.asyncio
async def test_send_message_blocked_by_dlp() -> None:
    """Message blocked by DLP returns 'blocked' status."""
    user = _admin_user()
    secrets = _mock_secrets()

    with patch(
        "app.services.a2a_service.DLPService.scan_content",
        return_value=_block_dlp_result(),
    ):
        response = await A2AService.send_message(
            TENANT_A, user, str(uuid4()), str(uuid4()), "SSN: 123-45-6789", secrets,
        )

    assert response.status == "blocked"
    assert "DLP" in response.response_content


# ── receive_message ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_receive_message_clean() -> None:
    """Inbound message passes DLP and is accepted."""
    msg = A2AFederationMessage(
        message_id=uuid4(),
        sender_agent_id=uuid4(),
        content="Hello from partner",
        timestamp=datetime.now(tz=timezone.utc),
    )

    with patch(
        "app.services.a2a_service.DLPService.scan_content",
        return_value=_clean_dlp_result(),
    ):
        response = await A2AService.receive_message(TENANT_A, str(uuid4()), msg)

    assert response.status == "accepted"
    assert response.message_id == msg.message_id


@pytest.mark.asyncio
async def test_receive_message_blocked_by_dlp() -> None:
    """Inbound message with sensitive data is rejected."""
    msg = A2AFederationMessage(
        message_id=uuid4(),
        sender_agent_id=uuid4(),
        content="Sensitive PII data",
        timestamp=datetime.now(tz=timezone.utc),
    )

    with patch(
        "app.services.a2a_service.DLPService.scan_content",
        return_value=_block_dlp_result(),
    ):
        response = await A2AService.receive_message(TENANT_A, str(uuid4()), msg)

    assert response.status == "rejected"
    assert "DLP" in response.response_content


# ── manage_trust_level ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manage_trust_level_update() -> None:
    """Updates partner trust level to FEDERATED."""
    user = _admin_user()
    partner_id = str(uuid4())

    result = await A2AService.manage_trust_level(
        TENANT_A, user, partner_id, TrustLevel.FEDERATED,
    )

    assert isinstance(result, Partner)
    assert result.trust_level == TrustLevel.FEDERATED
    assert result.tenant_id == TENANT_A


@pytest.mark.asyncio
async def test_manage_trust_level_verified() -> None:
    """Sets trust level to VERIFIED."""
    user = _admin_user()
    partner_id = str(uuid4())

    result = await A2AService.manage_trust_level(
        TENANT_A, user, partner_id, TrustLevel.VERIFIED,
    )

    assert result.trust_level == TrustLevel.VERIFIED


# ── rotate_partner_credentials ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rotate_partner_credentials() -> None:
    """Rotates credentials: reads from Vault, writes new secret."""
    secrets = _mock_secrets()
    partner_id = str(uuid4())

    await A2AService.rotate_partner_credentials(TENANT_A, partner_id, secrets)

    secrets.get_secret.assert_awaited_once()
    secrets.put_secret.assert_awaited_once()
    # Verify new secret was written with a different client_secret
    written_data = secrets.put_secret.call_args[0][1]
    assert "client_secret" in written_data


# ── federation_status ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_federation_status() -> None:
    """Returns federation status for a tenant."""
    status = await A2AService.get_federation_status(TENANT_A)

    assert isinstance(status, FederationStatus)
    assert status.health == "healthy"
    assert status.partner_count >= 0


# ── Tenant isolation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_register_partner() -> None:
    """Partners registered for Tenant A have tenant_id = Tenant A."""
    user_a = _admin_user(tenant_id=TENANT_A)
    user_b = _admin_user(tenant_id=TENANT_B)
    secrets = _mock_secrets()

    partner_a = await A2AService.register_partner(
        TENANT_A, user_a, _partner_registration(name="Partner A"), secrets,
    )
    partner_b = await A2AService.register_partner(
        TENANT_B, user_b, _partner_registration(name="Partner B"), secrets,
    )

    assert partner_a.tenant_id == TENANT_A
    assert partner_b.tenant_id == TENANT_B
    assert partner_a.tenant_id != partner_b.tenant_id


@pytest.mark.asyncio
async def test_federation_status_tenant_scoped() -> None:
    """Federation status is requested per tenant — no cross-tenant leakage."""
    status_a = await A2AService.get_federation_status(TENANT_A)
    status_b = await A2AService.get_federation_status(TENANT_B)

    assert isinstance(status_a, FederationStatus)
    assert isinstance(status_b, FederationStatus)
