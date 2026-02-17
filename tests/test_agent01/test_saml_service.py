"""Comprehensive tests for SAMLService — SAML 2.0 SP implementation."""

from __future__ import annotations

import base64
import zlib
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from xml.etree import ElementTree as ET

import pytest

from app.models.saml import SAMLAttributeMapping, SAMLIdPConfig, SAMLRequest
from app.services.saml_service import SAMLService, _NS_SAML2, _NS_SAML2P


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TENANT_A = "tenant-aaa"
_TENANT_B = "tenant-bbb"
_IDP_ENTITY_ID = "https://idp.example.com"
_IDP_SSO_URL = "https://idp.example.com/sso"
_SP_ENTITY_ID = "https://archon.dev/saml/metadata"
_SP_ACS_URL = "https://archon.dev/saml/acs"


def _vault_idp_data(
    entity_id: str = _IDP_ENTITY_ID,
    sso_url: str = _IDP_SSO_URL,
) -> dict[str, Any]:
    """Return a dict matching what Vault stores for an IdP config."""
    return {
        "entity_id": entity_id,
        "sso_url": sso_url,
        "slo_url": "",
        "signing_cert": "",
        "name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        "attribute_mapping": {},
        "enabled": True,
    }


def _build_saml_response_xml(
    issuer: str = _IDP_ENTITY_ID,
    name_id: str = "user@example.com",
    session_index: str = "_session_123",
    status: str = "urn:oasis:names:tc:SAML:2.0:status:Success",
    include_assertion: bool = True,
) -> str:
    """Build a minimal SAML Response XML string."""
    assertion_block = ""
    if include_assertion:
        assertion_block = (
            f'<saml2:Assertion xmlns:saml2="{_NS_SAML2}">'
            f"<saml2:Issuer>{issuer}</saml2:Issuer>"
            f"<saml2:Subject>"
            f"<saml2:NameID>{name_id}</saml2:NameID>"
            f"</saml2:Subject>"
            f'<saml2:AuthnStatement SessionIndex="{session_index}"/>'
            f"<saml2:AttributeStatement>"
            f'<saml2:Attribute Name="urn:oid:0.9.2342.19200300.100.1.3">'
            f"<saml2:AttributeValue>{name_id}</saml2:AttributeValue>"
            f"</saml2:Attribute>"
            f"</saml2:AttributeStatement>"
            f"</saml2:Assertion>"
        )

    return (
        f'<saml2p:Response xmlns:saml2p="{_NS_SAML2P}" xmlns:saml2="{_NS_SAML2}">'
        f"<saml2:Issuer>{issuer}</saml2:Issuer>"
        f"<saml2p:Status>"
        f'<saml2p:StatusCode Value="{status}"/>'
        f"</saml2p:Status>"
        f"{assertion_block}"
        f"</saml2p:Response>"
    )


def _b64_response(xml: str) -> str:
    return base64.b64encode(xml.encode("utf-8")).decode("ascii")


@pytest.fixture()
def mock_secrets() -> AsyncMock:
    """Mocked VaultSecretsManager."""
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value=_vault_idp_data())
    secrets.put_secret = AsyncMock()
    return secrets


@pytest.fixture()
def svc(mock_secrets: AsyncMock) -> SAMLService:
    return SAMLService(
        secrets=mock_secrets,
        sp_entity_id=_SP_ENTITY_ID,
        sp_acs_url=_SP_ACS_URL,
    )


# ---------------------------------------------------------------------------
# generate_authn_request
# ---------------------------------------------------------------------------


class TestGenerateAuthnRequest:
    """Tests for SAMLService.generate_authn_request."""

    @pytest.mark.asyncio
    async def test_returns_saml_request_model(self, svc: SAMLService) -> None:
        result = await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        assert isinstance(result, SAMLRequest)

    @pytest.mark.asyncio
    async def test_request_id_starts_with_prefix(self, svc: SAMLService) -> None:
        result = await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        assert result.request_id.startswith("_archon_")

    @pytest.mark.asyncio
    async def test_redirect_url_contains_saml_request_param(
        self, svc: SAMLService,
    ) -> None:
        result = await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        assert "SAMLRequest=" in result.redirect_url

    @pytest.mark.asyncio
    async def test_redirect_url_starts_with_idp_sso(
        self, svc: SAMLService,
    ) -> None:
        result = await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        assert result.redirect_url.startswith(_IDP_SSO_URL)

    @pytest.mark.asyncio
    async def test_relay_state_contains_tenant(self, svc: SAMLService) -> None:
        result = await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        assert f"tenant={_TENANT_A}" in result.relay_state

    @pytest.mark.asyncio
    async def test_deflated_xml_is_valid_authn_request(
        self, svc: SAMLService,
    ) -> None:
        result = await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        # Extract the SAMLRequest param and decode
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(result.redirect_url)
        saml_b64 = parse_qs(parsed.query)["SAMLRequest"][0]
        deflated = base64.b64decode(saml_b64)
        xml_bytes = zlib.decompress(deflated, -15)
        root = ET.fromstring(xml_bytes.decode("utf-8"))
        assert root.tag == f"{{{_NS_SAML2P}}}AuthnRequest"
        assert root.get("Version") == "2.0"

    @pytest.mark.asyncio
    async def test_authn_request_calls_vault(
        self, svc: SAMLService, mock_secrets: AsyncMock,
    ) -> None:
        await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        mock_secrets.get_secret.assert_awaited_once_with(
            f"saml/idp/{_TENANT_A}", _TENANT_A,
        )


# ---------------------------------------------------------------------------
# process_saml_response — valid assertion
# ---------------------------------------------------------------------------


class TestProcessSAMLResponseValid:
    """Tests for valid SAML response processing."""

    @pytest.mark.asyncio
    async def test_returns_authenticated_user(self, svc: SAMLService) -> None:
        xml = _build_saml_response_xml()
        result = await svc.process_saml_response(_b64_response(xml), _TENANT_A)
        assert result.email == "user@example.com"
        assert result.tenant_id == _TENANT_A

    @pytest.mark.asyncio
    async def test_user_id_is_name_id(self, svc: SAMLService) -> None:
        xml = _build_saml_response_xml(name_id="alice@corp.com")
        result = await svc.process_saml_response(_b64_response(xml), _TENANT_A)
        assert result.id == "alice@corp.com"

    @pytest.mark.asyncio
    async def test_session_id_from_authn_statement(
        self, svc: SAMLService,
    ) -> None:
        xml = _build_saml_response_xml(session_index="_sess_xyz")
        result = await svc.process_saml_response(_b64_response(xml), _TENANT_A)
        assert result.session_id == "_sess_xyz"


# ---------------------------------------------------------------------------
# process_saml_response — invalid / expired assertion
# ---------------------------------------------------------------------------


class TestProcessSAMLResponseInvalid:
    """Tests for invalid SAML responses raising ValueError."""

    @pytest.mark.asyncio
    async def test_invalid_base64_raises(self, svc: SAMLService) -> None:
        with pytest.raises(ValueError, match="Failed to decode"):
            await svc.process_saml_response("%%%not-base64%%%", _TENANT_A)

    @pytest.mark.asyncio
    async def test_issuer_mismatch_raises(self, svc: SAMLService) -> None:
        xml = _build_saml_response_xml(issuer="https://evil.example.com")
        with pytest.raises(ValueError, match="issuer does not match"):
            await svc.process_saml_response(_b64_response(xml), _TENANT_A)

    @pytest.mark.asyncio
    async def test_failed_status_raises(self, svc: SAMLService) -> None:
        xml = _build_saml_response_xml(
            status="urn:oasis:names:tc:SAML:2.0:status:Requester",
        )
        with pytest.raises(ValueError, match="SAML response status"):
            await svc.process_saml_response(_b64_response(xml), _TENANT_A)

    @pytest.mark.asyncio
    async def test_missing_assertion_raises(self, svc: SAMLService) -> None:
        xml = _build_saml_response_xml(include_assertion=False)
        with pytest.raises(ValueError, match="No Assertion element"):
            await svc.process_saml_response(_b64_response(xml), _TENANT_A)

    @pytest.mark.asyncio
    async def test_malformed_xml_raises(self, svc: SAMLService) -> None:
        bad_xml = base64.b64encode(b"<not-xml>").decode()
        with pytest.raises(ValueError):
            await svc.process_saml_response(bad_xml, _TENANT_A)


# ---------------------------------------------------------------------------
# generate_metadata
# ---------------------------------------------------------------------------


class TestGenerateMetadata:
    """Tests for SAMLService.generate_metadata."""

    @pytest.mark.asyncio
    async def test_returns_xml_string(self, svc: SAMLService) -> None:
        result = await svc.generate_metadata(_TENANT_A)
        assert isinstance(result, str)
        assert result.startswith("<md:EntityDescriptor")

    @pytest.mark.asyncio
    async def test_contains_entity_id(self, svc: SAMLService) -> None:
        result = await svc.generate_metadata(_TENANT_A)
        assert _SP_ENTITY_ID in result

    @pytest.mark.asyncio
    async def test_contains_acs_url(self, svc: SAMLService) -> None:
        result = await svc.generate_metadata(_TENANT_A)
        assert _SP_ACS_URL in result

    @pytest.mark.asyncio
    async def test_parseable_as_xml(self, svc: SAMLService) -> None:
        result = await svc.generate_metadata(_TENANT_A)
        root = ET.fromstring(result)
        assert "EntityDescriptor" in root.tag


# ---------------------------------------------------------------------------
# configure_idp
# ---------------------------------------------------------------------------


class TestConfigureIdP:
    """Tests for SAMLService.configure_idp."""

    _IDP_METADATA_XML = (
        '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"'
        ' entityID="https://idp.example.com">'
        "<md:IDPSSODescriptor>"
        '<md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"'
        ' Location="https://idp.example.com/sso"/>'
        '<md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"'
        ' Location="https://idp.example.com/slo"/>'
        "<md:KeyDescriptor>"
        '<ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
        "<ds:X509Data>"
        "<ds:X509Certificate>dGVzdA==</ds:X509Certificate>"
        "</ds:X509Data>"
        "</ds:KeyInfo>"
        "</md:KeyDescriptor>"
        "</md:IDPSSODescriptor>"
        "</md:EntityDescriptor>"
    )

    @pytest.mark.asyncio
    async def test_returns_saml_idp_config(self, svc: SAMLService) -> None:
        result = await svc.configure_idp(_TENANT_A, self._IDP_METADATA_XML)
        assert isinstance(result, SAMLIdPConfig)
        assert result.entity_id == _IDP_ENTITY_ID
        assert result.tenant_id == _TENANT_A

    @pytest.mark.asyncio
    async def test_stores_config_in_vault(
        self, svc: SAMLService, mock_secrets: AsyncMock,
    ) -> None:
        await svc.configure_idp(_TENANT_A, self._IDP_METADATA_XML)
        mock_secrets.put_secret.assert_awaited_once()
        call_args = mock_secrets.put_secret.call_args
        assert call_args[0][0] == f"saml/idp/{_TENANT_A}"
        assert call_args[0][2] == _TENANT_A

    @pytest.mark.asyncio
    async def test_sso_url_parsed_from_metadata(self, svc: SAMLService) -> None:
        result = await svc.configure_idp(_TENANT_A, self._IDP_METADATA_XML)
        assert result.sso_url == "https://idp.example.com/sso"

    @pytest.mark.asyncio
    async def test_slo_url_parsed_from_metadata(self, svc: SAMLService) -> None:
        result = await svc.configure_idp(_TENANT_A, self._IDP_METADATA_XML)
        assert result.slo_url == "https://idp.example.com/slo"

    @pytest.mark.asyncio
    async def test_enabled_by_default(self, svc: SAMLService) -> None:
        result = await svc.configure_idp(_TENANT_A, self._IDP_METADATA_XML)
        assert result.enabled is True

    @pytest.mark.asyncio
    async def test_url_metadata_stores_metadata_url(
        self, svc: SAMLService,
    ) -> None:
        url = "https://idp.example.com/metadata"
        result = await svc.configure_idp(_TENANT_A, url)
        assert result.metadata_url == url


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Verify SAML operations are scoped to the correct tenant."""

    @pytest.mark.asyncio
    async def test_authn_request_uses_tenant_vault_path(
        self, svc: SAMLService, mock_secrets: AsyncMock,
    ) -> None:
        await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        mock_secrets.get_secret.assert_awaited_with(
            f"saml/idp/{_TENANT_A}", _TENANT_A,
        )

    @pytest.mark.asyncio
    async def test_different_tenants_use_different_paths(
        self, svc: SAMLService, mock_secrets: AsyncMock,
    ) -> None:
        await svc.generate_authn_request(_TENANT_A, _IDP_ENTITY_ID)
        await svc.generate_authn_request(_TENANT_B, _IDP_ENTITY_ID)
        calls = mock_secrets.get_secret.await_args_list
        assert calls[0][0] == (f"saml/idp/{_TENANT_A}", _TENANT_A)
        assert calls[1][0] == (f"saml/idp/{_TENANT_B}", _TENANT_B)

    @pytest.mark.asyncio
    async def test_process_response_scopes_user_to_tenant(
        self, svc: SAMLService,
    ) -> None:
        xml = _build_saml_response_xml()
        user = await svc.process_saml_response(_b64_response(xml), _TENANT_B)
        assert user.tenant_id == _TENANT_B

    @pytest.mark.asyncio
    async def test_configure_idp_stores_under_tenant_path(
        self, svc: SAMLService, mock_secrets: AsyncMock,
    ) -> None:
        await svc.configure_idp(
            _TENANT_B,
            "https://idp.example.com/metadata",
        )
        call_args = mock_secrets.put_secret.call_args
        assert call_args[0][0] == f"saml/idp/{_TENANT_B}"
        assert call_args[0][2] == _TENANT_B
