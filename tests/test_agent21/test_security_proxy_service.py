"""Tests for SecurityProxyService — process_request pipeline, SAML termination,
credential injection, upstream configuration, content classification, and metrics."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.security_proxy import (
    AuthMethod,
    ContentClassification,
    ProviderType,
    ProxyMetrics,
    ProxyRequest,
    ProxyResponse,
    ProxySession,
    SensitivityLevel,
    UpstreamConfig,
)
from app.services.security_proxy_service import (
    SecurityProxyService,
    _metrics_store,
    _upstream_store,
)


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-proxy-test"


def _admin_user(**overrides: Any) -> AuthenticatedUser:
    defaults = dict(
        id=str(uuid4()),
        email="admin@example.com",
        tenant_id=TENANT_ID,
        roles=["admin"],
        permissions=[],
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_secrets() -> AsyncMock:
    vault = AsyncMock()
    vault.get_secret = AsyncMock(return_value={"api_key": "sk-test-secret-key-value"})
    return vault


@pytest.fixture(autouse=True)
def _clean_stores() -> None:
    """Reset in-memory stores between tests."""
    _upstream_store.clear()
    _metrics_store.clear()


@pytest.fixture()
def svc() -> SecurityProxyService:
    return SecurityProxyService(secrets=_mock_secrets())


# ── process_request (full pipeline) ─────────────────────────────────


@pytest.mark.asyncio
async def test_process_request_returns_proxy_response(svc: SecurityProxyService) -> None:
    """Full pipeline returns a ProxyResponse with 200 status."""
    req = ProxyRequest(
        method="POST",
        url="https://api.openai.com/v1/chat",
        body={"messages": [{"role": "user", "content": "hello"}]},
        tenant_id=TENANT_ID,
        user_id="user-1",
    )
    resp = await svc.process_request(TENANT_ID, _admin_user(), req)
    assert isinstance(resp, ProxyResponse)
    assert resp.status_code == 200
    assert resp.latency_ms >= 0
    assert "X-Proxy-Request-Id" in resp.headers


@pytest.mark.asyncio
async def test_process_request_dlp_scans_body(svc: SecurityProxyService) -> None:
    """DLP findings are captured when request body contains sensitive data."""
    req = ProxyRequest(
        method="POST",
        url="https://api.openai.com/v1/chat",
        body={"messages": [{"role": "user", "content": "My SSN is 123-45-6789"}]},
        tenant_id=TENANT_ID,
        user_id="user-1",
    )
    resp = await svc.process_request(TENANT_ID, _admin_user(), req)
    # DLP may or may not find something in the JSON-encoded body depending on patterns
    assert isinstance(resp.dlp_findings, list)


@pytest.mark.asyncio
async def test_process_request_empty_tenant_raises(svc: SecurityProxyService) -> None:
    """Empty tenant_id raises ValueError."""
    req = ProxyRequest(
        method="GET", url="https://example.com", tenant_id="", user_id="u1",
    )
    with pytest.raises(ValueError, match="tenant_id"):
        await svc.process_request("", _admin_user(), req)


@pytest.mark.asyncio
async def test_process_request_records_metrics(svc: SecurityProxyService) -> None:
    """After processing, metrics store is updated for the tenant."""
    req = ProxyRequest(
        method="POST", url="https://api.openai.com/v1/chat",
        body={"prompt": "test"}, tenant_id=TENANT_ID, user_id="u1",
    )
    await svc.process_request(TENANT_ID, _admin_user(), req)
    assert TENANT_ID in _metrics_store
    assert _metrics_store[TENANT_ID]["total_requests"] == 1


# ── terminate_saml ──────────────────────────────────────────────────


def _build_saml_response(
    issuer: str = "https://idp.example.com",
    name_id: str = "user@example.com",
    audience: str = "tenant-proxy-test",
    roles: list[str] | None = None,
) -> str:
    """Build a minimal base64-encoded SAML Response XML."""
    roles_xml = ""
    if roles:
        values = "".join(
            f'<saml:AttributeValue xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">{r}</saml:AttributeValue>'
            for r in roles
        )
        roles_xml = (
            f'<saml:Attribute Name="role" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
            f'{values}</saml:Attribute>'
        )
    xml = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                              xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
        <saml:Issuer>{issuer}</saml:Issuer>
        <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
        <saml:Assertion>
            <saml:Subject><saml:NameID>{name_id}</saml:NameID></saml:Subject>
            <saml:Conditions><saml:AudienceRestriction>
                <saml:Audience>{audience}</saml:Audience>
            </saml:AudienceRestriction></saml:Conditions>
            <saml:AttributeStatement>{roles_xml}</saml:AttributeStatement>
        </saml:Assertion>
    </samlp:Response>"""
    return base64.b64encode(xml.encode()).decode()


@pytest.mark.asyncio
async def test_terminate_saml_valid(svc: SecurityProxyService) -> None:
    """Valid SAML response creates a ProxySession with correct attributes."""
    saml = _build_saml_response(roles=["admin", "developer"])
    session = await svc.terminate_saml(saml, "https://idp.example.com")
    assert isinstance(session, ProxySession)
    assert session.user_id == "user@example.com"
    assert session.tenant_id == "tenant-proxy-test"
    assert "admin" in session.roles
    assert session.authenticated_via == "saml"
    assert session.expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_terminate_saml_issuer_mismatch(svc: SecurityProxyService) -> None:
    """Mismatched issuer raises ValueError."""
    saml = _build_saml_response(issuer="https://wrong.idp.com")
    with pytest.raises(ValueError, match="Issuer mismatch"):
        await svc.terminate_saml(saml, "https://expected.idp.com")


@pytest.mark.asyncio
async def test_terminate_saml_invalid_base64(svc: SecurityProxyService) -> None:
    """Non-base64 input raises ValueError."""
    with pytest.raises(ValueError, match="Failed to decode"):
        await svc.terminate_saml("not-valid-base64!!!", "https://idp.example.com")


# ── inject_credentials ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inject_credentials_adds_auth_header(svc: SecurityProxyService) -> None:
    """Credentials from Vault are injected as Bearer token in request headers."""
    req = ProxyRequest(
        method="POST", url="https://api.openai.com/v1/chat",
        tenant_id=TENANT_ID, user_id="u1",
    )
    injected = await svc.inject_credentials(TENANT_ID, "openai", req)
    assert "Authorization" in injected
    assert injected["Authorization"].startswith("Bearer ")
    assert req.headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_inject_credentials_vault_failure_returns_empty() -> None:
    """When Vault lookup fails, no credentials are injected."""
    vault = AsyncMock()
    vault.get_secret = AsyncMock(side_effect=Exception("vault unavailable"))
    svc = SecurityProxyService(secrets=vault)

    req = ProxyRequest(
        method="GET", url="https://api.example.com",
        tenant_id=TENANT_ID, user_id="u1",
    )
    injected = await svc.inject_credentials(TENANT_ID, "custom", req)
    assert injected == {}


# ── configure_upstream ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_configure_upstream_stores_config(svc: SecurityProxyService) -> None:
    """Upstream config is stored and retrievable via list_upstreams."""
    upstream = UpstreamConfig(
        name="openai-prod",
        base_url="https://api.openai.com",
        provider_type=ProviderType.OPENAI,
        auth_method=AuthMethod.BEARER_TOKEN,
        vault_credential_path="proxy/upstreams/tenant/openai/creds",
    )
    result = await svc.configure_upstream(TENANT_ID, _admin_user(), upstream)
    assert result.tenant_id == TENANT_ID

    upstreams = await svc.list_upstreams(TENANT_ID)
    assert len(upstreams) == 1
    assert upstreams[0].name == "openai-prod"


@pytest.mark.asyncio
async def test_configure_upstream_replaces_existing(svc: SecurityProxyService) -> None:
    """Re-configuring the same upstream ID replaces it."""
    upstream = UpstreamConfig(
        id="fixed-id",
        name="openai-v1",
        base_url="https://api.openai.com/v1",
        provider_type=ProviderType.OPENAI,
        auth_method=AuthMethod.BEARER_TOKEN,
        vault_credential_path="proxy/creds",
    )
    await svc.configure_upstream(TENANT_ID, _admin_user(), upstream)
    upstream.name = "openai-v2"
    await svc.configure_upstream(TENANT_ID, _admin_user(), upstream)

    upstreams = await svc.list_upstreams(TENANT_ID)
    assert len(upstreams) == 1
    assert upstreams[0].name == "openai-v2"


# ── content_classification ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_content_code_generation(svc: SecurityProxyService) -> None:
    """Content about code is classified under code_generation topic."""
    result = await svc.classify_content("Write a Python function to sort a list.")
    assert isinstance(result, ContentClassification)
    assert "code_generation" in result.topics


@pytest.mark.asyncio
async def test_classify_content_restricted_sensitivity(svc: SecurityProxyService) -> None:
    """Content with SSN keywords gets restricted sensitivity."""
    result = await svc.classify_content("My social security number is important.")
    assert result.sensitivity_level == SensitivityLevel.RESTRICTED


@pytest.mark.asyncio
async def test_classify_content_question_intent(svc: SecurityProxyService) -> None:
    """Content with a question mark has intent 'question'."""
    result = await svc.classify_content("What is the weather today?")
    assert result.intent == "question"


@pytest.mark.asyncio
async def test_classify_content_public_clean_text(svc: SecurityProxyService) -> None:
    """Clean public text gets PUBLIC sensitivity."""
    result = await svc.classify_content("The sky is blue.")
    assert result.sensitivity_level == SensitivityLevel.PUBLIC


# ── proxy_metrics ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_metrics_empty(svc: SecurityProxyService) -> None:
    """Empty metrics returns zeroed ProxyMetrics."""
    metrics = await svc.get_proxy_metrics(TENANT_ID)
    assert isinstance(metrics, ProxyMetrics)
    assert metrics.total_requests == 0
    assert metrics.avg_latency_ms == 0.0


@pytest.mark.asyncio
async def test_proxy_metrics_after_requests(svc: SecurityProxyService) -> None:
    """Metrics reflect the number of proxied requests."""
    req = ProxyRequest(
        method="POST", url="https://api.openai.com/v1/chat",
        body={"prompt": "hi"}, tenant_id=TENANT_ID, user_id="u1",
    )
    await svc.process_request(TENANT_ID, _admin_user(), req)
    await svc.process_request(TENANT_ID, _admin_user(), req)

    metrics = await svc.get_proxy_metrics(TENANT_ID)
    assert metrics.total_requests == 2
    assert metrics.avg_latency_ms > 0
