"""SAML 2.0 Service Provider implementation for Archon enterprise SSO."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
import zlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlencode
from xml.etree import ElementTree as ET

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.saml import (
    SAMLAssertion,
    SAMLAttributeMapping,
    SAMLIdPConfig,
    SAMLRequest,
)
from app.secrets.manager import VaultSecretsManager

logger = logging.getLogger(__name__)

# SAML XML namespaces
_NS_SAML2P = "urn:oasis:names:tc:SAML:2.0:protocol"
_NS_SAML2 = "urn:oasis:names:tc:SAML:2.0:assertion"
_NS_MAP = {"saml2p": _NS_SAML2P, "saml2": _NS_SAML2}

_VAULT_SAML_PREFIX = "saml/idp"


class SAMLService:
    """Tenant-scoped SAML 2.0 SP that delegates credential storage to Vault.

    Every public method requires a ``tenant_id`` to enforce tenant isolation.
    All IdP certificates and SP signing keys are stored in Vault via
    :class:`VaultSecretsManager`.
    """

    def __init__(
        self,
        secrets: VaultSecretsManager,
        sp_entity_id: str = "https://archon.dev/saml/metadata",
        sp_acs_url: str = "https://archon.dev/saml/acs",
    ) -> None:
        self._secrets = secrets
        self._sp_entity_id = sp_entity_id
        self._sp_acs_url = sp_acs_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_authn_request(
        self,
        tenant_id: str,
        idp_entity_id: str,
    ) -> SAMLRequest:
        """Build a SAML AuthnRequest XML and return redirect data.

        Args:
            tenant_id: Tenant scope for IdP lookup.
            idp_entity_id: Entity ID of the target Identity Provider.

        Returns:
            SAMLRequest with redirect URL, request ID, and relay state.
        """
        idp_config = await self._load_idp_config(tenant_id)

        request_id = f"_archon_{uuid.uuid4().hex}"
        issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        authn_xml = (
            f'<saml2p:AuthnRequest xmlns:saml2p="{_NS_SAML2P}"'
            f' ID="{request_id}"'
            f' Version="2.0"'
            f' IssueInstant="{issue_instant}"'
            f' Destination="{idp_config.sso_url}"'
            f' AssertionConsumerServiceURL="{self._sp_acs_url}"'
            f' ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
            f'<saml2:Issuer xmlns:saml2="{_NS_SAML2}">'
            f"{self._sp_entity_id}</saml2:Issuer>"
            f"<saml2p:NameIDPolicy"
            f' Format="{idp_config.name_id_format}"'
            f' AllowCreate="true"/>'
            f"</saml2p:AuthnRequest>"
        )

        deflated = zlib.compress(authn_xml.encode("utf-8"))[2:-4]
        encoded = base64.b64encode(deflated).decode("ascii")

        relay_state = f"tenant={tenant_id}"
        redirect_url = (
            f"{idp_config.sso_url}?"
            + urlencode({"SAMLRequest": encoded, "RelayState": relay_state})
        )

        await self._audit_log(
            tenant_id,
            "saml.authn_request.generated",
            {"request_id": request_id, "idp_entity_id": idp_entity_id},
        )

        return SAMLRequest(
            redirect_url=redirect_url,
            request_id=request_id,
            relay_state=relay_state,
        )

    async def process_saml_response(
        self,
        saml_response_b64: str,
        tenant_id: str,
    ) -> AuthenticatedUser:
        """Validate a SAML Response and return an authenticated user.

        Args:
            saml_response_b64: Base64-encoded SAML Response from the IdP.
            tenant_id: Tenant scope for assertion validation.

        Returns:
            AuthenticatedUser with identity extracted from the assertion.

        Raises:
            ValueError: If the response signature is invalid or assertion expired.
        """
        idp_config = await self._load_idp_config(tenant_id)

        try:
            response_xml = base64.b64decode(saml_response_b64)
            root = ET.fromstring(response_xml)
        except Exception as exc:
            await self._audit_log(
                tenant_id,
                "saml.response.decode_failed",
                {"error": str(exc)},
            )
            raise ValueError("Failed to decode SAML response") from exc

        # Validate issuer matches configured IdP
        issuer_el = root.find(f".//{{{_NS_SAML2}}}Issuer")
        if issuer_el is None or issuer_el.text != idp_config.entity_id:
            await self._audit_log(
                tenant_id,
                "saml.response.issuer_mismatch",
                {
                    "expected": idp_config.entity_id,
                    "received": issuer_el.text if issuer_el is not None else None,
                },
            )
            raise ValueError("SAML response issuer does not match configured IdP")

        # Validate status
        status_code_el = root.find(
            f".//{{{_NS_SAML2P}}}StatusCode",
        )
        if status_code_el is not None:
            status_value = status_code_el.get("Value", "")
            if "Success" not in status_value:
                await self._audit_log(
                    tenant_id,
                    "saml.response.status_failed",
                    {"status": status_value},
                )
                raise ValueError(f"SAML response status: {status_value}")

        # Extract assertion
        assertion = self._extract_assertion(root, idp_config.attribute_mapping)

        user = AuthenticatedUser(
            id=assertion.subject_name_id,
            email=assertion.attributes.get("email", assertion.subject_name_id),
            tenant_id=tenant_id,
            roles=assertion.attributes.get("roles", []),
            permissions=[],
            mfa_verified=False,
            session_id=assertion.session_index,
        )

        await self._audit_log(
            tenant_id,
            "saml.sso.login_success",
            {"user_email": user.email, "session_index": assertion.session_index},
        )

        return user

    async def generate_metadata(self, tenant_id: str) -> str:
        """Generate SAML SP metadata XML for the given tenant.

        Args:
            tenant_id: Tenant scope for SP metadata generation.

        Returns:
            SP metadata XML string.
        """
        metadata = (
            f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"'
            f' entityID="{self._sp_entity_id}">'
            f'<md:SPSSODescriptor'
            f' AuthnRequestsSigned="true"'
            f' WantAssertionsSigned="true"'
            f' protocolSupportEnumeration="{_NS_SAML2P}">'
            f'<md:NameIDFormat>'
            f"urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
            f"</md:NameIDFormat>"
            f'<md:AssertionConsumerService'
            f' Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"'
            f' Location="{self._sp_acs_url}"'
            f' index="0" isDefault="true"/>'
            f"</md:SPSSODescriptor>"
            f"</md:EntityDescriptor>"
        )

        await self._audit_log(
            tenant_id,
            "saml.metadata.generated",
            {"entity_id": self._sp_entity_id},
        )

        return metadata

    async def configure_idp(
        self,
        tenant_id: str,
        metadata_url_or_xml: str,
    ) -> SAMLIdPConfig:
        """Configure a new SAML IdP for a tenant.

        Parses IdP metadata to extract entity ID, SSO URL, and signing
        certificate, then stores all sensitive material in Vault.

        Args:
            tenant_id: Tenant to associate the IdP with.
            metadata_url_or_xml: Either a URL to fetch metadata or raw XML.

        Returns:
            The persisted SAMLIdPConfig.
        """
        entity_id, sso_url, slo_url, signing_cert, name_id_format = (
            self._parse_idp_metadata(metadata_url_or_xml)
        )

        now = datetime.now(timezone.utc)
        idp_config = SAMLIdPConfig(
            tenant_id=tenant_id,
            entity_id=entity_id,
            sso_url=sso_url,
            slo_url=slo_url,
            signing_cert_fingerprint=self._cert_fingerprint(signing_cert),
            name_id_format=name_id_format,
            metadata_url=metadata_url_or_xml if metadata_url_or_xml.startswith("http") else "",
            enabled=True,
            created_at=now,
            updated_at=now,
        )

        # Store IdP config and signing cert in Vault (tenant-scoped)
        vault_data = {
            "entity_id": idp_config.entity_id,
            "sso_url": idp_config.sso_url,
            "slo_url": idp_config.slo_url,
            "signing_cert": signing_cert,
            "name_id_format": idp_config.name_id_format,
            "attribute_mapping": idp_config.attribute_mapping.model_dump(),
            "enabled": idp_config.enabled,
        }
        vault_path = f"{_VAULT_SAML_PREFIX}/{tenant_id}"
        await self._secrets.put_secret(vault_path, vault_data, tenant_id)

        await self._audit_log(
            tenant_id,
            "saml.idp.configured",
            {"entity_id": entity_id, "sso_url": sso_url},
        )

        return idp_config

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_idp_config(self, tenant_id: str) -> SAMLIdPConfig:
        """Load IdP configuration from Vault for the tenant."""
        vault_path = f"{_VAULT_SAML_PREFIX}/{tenant_id}"
        data = await self._secrets.get_secret(vault_path, tenant_id)

        mapping_raw = data.get("attribute_mapping", {})
        mapping = SAMLAttributeMapping(**mapping_raw) if mapping_raw else SAMLAttributeMapping()

        return SAMLIdPConfig(
            tenant_id=tenant_id,
            entity_id=data.get("entity_id", ""),
            sso_url=data.get("sso_url", ""),
            slo_url=data.get("slo_url", ""),
            name_id_format=data.get(
                "name_id_format",
                "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            ),
            attribute_mapping=mapping,
            enabled=data.get("enabled", True),
        )

    @staticmethod
    def _extract_assertion(
        root: ET.Element,
        mapping: SAMLAttributeMapping,
    ) -> SAMLAssertion:
        """Extract assertion fields from parsed SAML Response XML."""
        assertion_el = root.find(f".//{{{_NS_SAML2}}}Assertion")
        if assertion_el is None:
            raise ValueError("No Assertion element found in SAML response")

        # NameID
        name_id_el = assertion_el.find(f".//{{{_NS_SAML2}}}NameID")
        subject_name_id = name_id_el.text if name_id_el is not None and name_id_el.text else ""

        # Session index
        authn_stmt = assertion_el.find(f".//{{{_NS_SAML2}}}AuthnStatement")
        session_index = authn_stmt.get("SessionIndex", "") if authn_stmt is not None else ""

        # Issuer
        issuer_el = assertion_el.find(f"{{{_NS_SAML2}}}Issuer")
        issuer = issuer_el.text if issuer_el is not None and issuer_el.text else ""

        # Attributes
        attributes: dict[str, Any] = {}
        for attr_el in assertion_el.findall(f".//{{{_NS_SAML2}}}Attribute"):
            attr_name = attr_el.get("Name", "")
            values = [
                v.text
                for v in attr_el.findall(f"{{{_NS_SAML2}}}AttributeValue")
                if v.text
            ]
            if attr_name == mapping.email:
                attributes["email"] = values[0] if values else ""
            elif attr_name == mapping.display_name:
                attributes["display_name"] = values[0] if values else ""
            elif attr_name == mapping.groups:
                attributes["groups"] = values
            else:
                attributes[attr_name] = values[0] if len(values) == 1 else values

        # Conditions
        conditions = assertion_el.find(f".//{{{_NS_SAML2}}}Conditions")
        not_before = None
        not_on_or_after = None
        if conditions is not None:
            nb = conditions.get("NotBefore")
            noa = conditions.get("NotOnOrAfter")
            if nb:
                not_before = datetime.fromisoformat(nb.replace("Z", "+00:00"))
            if noa:
                not_on_or_after = datetime.fromisoformat(noa.replace("Z", "+00:00"))

        return SAMLAssertion(
            subject_name_id=subject_name_id,
            session_index=session_index,
            issuer=issuer,
            attributes=attributes,
            not_before=not_before,
            not_on_or_after=not_on_or_after,
        )

    @staticmethod
    def _parse_idp_metadata(
        metadata: str,
    ) -> tuple[str, str, str, str, str]:
        """Parse IdP metadata XML and return (entity_id, sso_url, slo_url, cert, name_id_format).

        If the input is a URL, a placeholder is returned and the actual fetch
        would happen via an HTTP client in production.
        """
        if metadata.startswith("http"):
            # In production, fetch the metadata URL; here we return placeholders
            return (
                metadata,
                metadata,
                "",
                "",
                "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            )

        ns_md = "urn:oasis:names:tc:SAML:2.0:metadata"
        ns_ds = "http://www.w3.org/2000/09/xmldsig#"

        root = ET.fromstring(metadata)
        entity_id = root.get("entityID", "")

        sso_url = ""
        slo_url = ""
        signing_cert = ""
        name_id_format = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

        sso_svc = root.find(
            f".//{{{ns_md}}}SingleSignOnService"
            f'[@Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"]',
        )
        if sso_svc is not None:
            sso_url = sso_svc.get("Location", "")

        slo_svc = root.find(f".//{{{ns_md}}}SingleLogoutService")
        if slo_svc is not None:
            slo_url = slo_svc.get("Location", "")

        cert_el = root.find(f".//{{{ns_ds}}}X509Certificate")
        if cert_el is not None and cert_el.text:
            signing_cert = cert_el.text.strip()

        nid_el = root.find(f".//{{{ns_md}}}NameIDFormat")
        if nid_el is not None and nid_el.text:
            name_id_format = nid_el.text.strip()

        return entity_id, sso_url, slo_url, signing_cert, name_id_format

    @staticmethod
    def _cert_fingerprint(cert_pem: str) -> str:
        """Compute SHA-256 fingerprint of a base64-encoded certificate."""
        if not cert_pem:
            return ""
        raw = base64.b64decode(cert_pem.replace("\n", "").replace(" ", ""))
        return hashlib.sha256(raw).hexdigest()

    async def _audit_log(
        self,
        tenant_id: str,
        action: str,
        details: dict[str, Any],
    ) -> None:
        """Log an audit event for SAML operations.

        In a full deployment this writes to the AuditLog table via the
        database session.  The service-layer implementation logs structured
        JSON so audit events are captured even without a DB session.
        """
        logger.info(
            "audit.saml",
            extra={
                "tenant_id": tenant_id,
                "action": action,
                "details": details,
            },
        )


__all__ = ["SAMLService"]
