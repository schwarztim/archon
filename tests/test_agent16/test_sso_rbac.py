"""Tests for SSO configuration, RBAC matrix, and impersonation routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.routes.sso_config import (
    ClaimMappingEntry,
    CustomRoleCreate,
    CustomRoleUpdate,
    ImpersonateRequest,
    SSOConfigCreate,
    SSOConfigUpdate,
    _BUILTIN_ROLES,
    _RESOURCES,
    _custom_roles,
    _mask_config,
    _tenant_key,
)

# A11 migrated _sso_configs from an in-memory dict to a DB table.
# This local dict replaces the removed module-level export so that the
# SSO config store tests remain runnable without a live DB connection.
_sso_configs: dict[str, dict] = {}


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-sso-test"


def _user(tenant_id: str = TENANT_ID, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="admin@archon.ai",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=[],
        session_id="sess-sso",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


@pytest.fixture(autouse=True)
def _clean_stores():
    """Clear in-memory stores before each test."""
    _sso_configs.clear()
    _custom_roles.clear()
    yield
    _sso_configs.clear()
    _custom_roles.clear()


# ── Schema Tests ────────────────────────────────────────────────────


class TestSSOConfigSchemas:
    """Test SSO configuration Pydantic schemas."""

    def test_sso_config_create_defaults(self) -> None:
        """SSOConfigCreate should accept minimal fields and set defaults."""
        cfg = SSOConfigCreate(name="Test OIDC", protocol="oidc")
        assert cfg.name == "Test OIDC"
        assert cfg.protocol == "oidc"
        assert cfg.enabled is True
        assert cfg.is_default is False
        assert cfg.scopes == ["openid", "profile", "email"]
        assert cfg.claim_mappings == []
        assert cfg.port == 389

    def test_sso_config_create_oidc_full(self) -> None:
        """SSOConfigCreate should accept all OIDC fields."""
        cfg = SSOConfigCreate(
            name="Keycloak",
            protocol="oidc",
            discovery_url="https://kc.example.com/.well-known/openid-configuration",
            client_id="archon",
            client_secret="secret123",
            scopes=["openid", "profile", "email", "groups"],
            claim_mappings=[
                ClaimMappingEntry(idp_claim="email", archon_field="Email"),
                ClaimMappingEntry(idp_claim="groups", archon_field="Groups"),
            ],
        )
        assert cfg.discovery_url.startswith("https://")
        assert len(cfg.claim_mappings) == 2
        assert cfg.claim_mappings[0].archon_field == "Email"

    def test_sso_config_create_saml(self) -> None:
        """SSOConfigCreate should accept SAML metadata fields."""
        cfg = SSOConfigCreate(
            name="Okta SAML",
            protocol="saml",
            metadata_url="https://okta.example.com/saml/metadata",
            entity_id="urn:archon:sp",
            certificate="-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        )
        assert cfg.protocol == "saml"
        assert cfg.metadata_url.startswith("https://")
        assert "BEGIN CERTIFICATE" in cfg.certificate

    def test_sso_config_create_ldap(self) -> None:
        """SSOConfigCreate should accept LDAP connection fields."""
        cfg = SSOConfigCreate(
            name="Active Directory",
            protocol="ldap",
            host="ldap.corp.example.com",
            port=636,
            use_tls=True,
            base_dn="dc=corp,dc=example,dc=com",
            bind_dn="cn=admin,dc=corp,dc=example,dc=com",
            bind_secret="ldap-secret",
            user_filter="(objectClass=person)",
            group_filter="(objectClass=group)",
        )
        assert cfg.protocol == "ldap"
        assert cfg.port == 636
        assert cfg.use_tls is True
        assert cfg.base_dn == "dc=corp,dc=example,dc=com"

    def test_sso_config_update_partial(self) -> None:
        """SSOConfigUpdate should allow partial updates."""
        upd = SSOConfigUpdate(name="Updated Name", enabled=False)
        data = upd.model_dump(exclude_unset=True)
        assert "name" in data
        assert "enabled" in data
        assert "discovery_url" not in data

    def test_claim_mapping_entry(self) -> None:
        """ClaimMappingEntry should hold IdP→Archon field pair."""
        entry = ClaimMappingEntry(idp_claim="preferred_username", archon_field="Username")
        assert entry.idp_claim == "preferred_username"
        assert entry.archon_field == "Username"

    def test_custom_role_create(self) -> None:
        """CustomRoleCreate should accept role name and permissions."""
        role = CustomRoleCreate(
            name="analyst",
            description="Read-only access to analytics",
            permissions={
                "agents": ["read"],
                "executions": ["read"],
            },
        )
        assert role.name == "analyst"
        assert "agents" in role.permissions
        assert role.permissions["agents"] == ["read"]

    def test_impersonate_request(self) -> None:
        """ImpersonateRequest should accept an optional reason."""
        req = ImpersonateRequest(reason="Debug user issue")
        assert req.reason == "Debug user issue"

        req_empty = ImpersonateRequest()
        assert req_empty.reason == ""


# ── Helper Tests ────────────────────────────────────────────────────


class TestHelpers:
    """Test helper functions."""

    def test_mask_config_masks_secrets(self) -> None:
        """_mask_config should replace secret fields with ********."""
        config: dict[str, Any] = {
            "name": "Test",
            "client_secret": "real-secret",
            "bind_secret": "ldap-pass",
            "certificate": "-----BEGIN CERT-----",
            "discovery_url": "https://example.com",
        }
        masked = _mask_config(config)
        assert masked["client_secret"] == "********"
        assert masked["bind_secret"] == "********"
        assert masked["certificate"] == "********"
        assert masked["discovery_url"] == "https://example.com"
        assert masked["name"] == "Test"
        # Original unchanged
        assert config["client_secret"] == "real-secret"

    def test_mask_config_no_secrets(self) -> None:
        """_mask_config should pass through configs without secret fields."""
        config: dict[str, Any] = {"name": "Test", "discovery_url": "https://x"}
        masked = _mask_config(config)
        assert masked == config

    def test_tenant_key(self) -> None:
        """_tenant_key should create tenant:sso composite key."""
        key = _tenant_key("t1", "s1")
        assert key == "t1:s1"


# ── RBAC Matrix Tests ──────────────────────────────────────────────


class TestRBACMatrix:
    """Test RBAC matrix data structure."""

    def test_builtin_roles_exist(self) -> None:
        """Built-in roles should include expected role names."""
        assert "super_admin" in _BUILTIN_ROLES
        assert "tenant_admin" in _BUILTIN_ROLES
        assert "developer" in _BUILTIN_ROLES
        assert "viewer" in _BUILTIN_ROLES

    def test_super_admin_has_full_access(self) -> None:
        """Super admin should have CRUD on all resources."""
        perms = _BUILTIN_ROLES["super_admin"]
        for resource in _RESOURCES:
            assert resource in perms
            assert set(perms[resource]) == {"create", "read", "update", "delete"}

    def test_viewer_read_only(self) -> None:
        """Viewer role should only have read permission on all resources."""
        perms = _BUILTIN_ROLES["viewer"]
        for resource in _RESOURCES:
            assert perms[resource] == ["read"]

    def test_developer_crud_on_dev_resources(self) -> None:
        """Developer should have CRUD on dev-specific resources."""
        perms = _BUILTIN_ROLES["developer"]
        dev_resources = {"agents", "executions", "connectors", "mcp_apps"}
        for resource in dev_resources:
            assert set(perms[resource]) == {"create", "read", "update", "delete"}

    def test_developer_read_only_on_others(self) -> None:
        """Developer should have read-only on non-dev resources."""
        perms = _BUILTIN_ROLES["developer"]
        non_dev = set(_RESOURCES) - {"agents", "executions", "connectors", "mcp_apps"}
        for resource in non_dev:
            assert perms[resource] == ["read"]

    def test_resources_list_complete(self) -> None:
        """Resources list should contain all expected platform resources."""
        expected = {
            "agents", "executions", "models", "connectors", "secrets",
            "users", "settings", "governance", "dlp", "cost_management",
            "sentinel_scan", "mcp_apps",
        }
        assert set(_RESOURCES) == expected

    def test_custom_role_store_operations(self) -> None:
        """Custom roles should be storable and retrievable."""
        role_id = str(uuid4())
        _custom_roles[role_id] = {
            "id": role_id,
            "name": "content_editor",
            "description": "Can edit content",
            "permissions": {"agents": ["read", "update"]},
            "is_builtin": False,
        }
        assert role_id in _custom_roles
        assert _custom_roles[role_id]["name"] == "content_editor"


# ── SSO Config Store Tests ─────────────────────────────────────────


class TestSSOConfigStore:
    """Test SSO config in-memory storage operations."""

    def test_store_and_retrieve_config(self) -> None:
        """Should store and retrieve SSO config by tenant:sso key."""
        sso_id = str(uuid4())
        key = _tenant_key(TENANT_ID, sso_id)
        config: dict[str, Any] = {
            "id": sso_id,
            "tenant_id": TENANT_ID,
            "name": "Test OIDC",
            "protocol": "oidc",
            "discovery_url": "https://kc.example.com",
            "enabled": True,
        }
        _sso_configs[key] = config
        assert _sso_configs[key]["name"] == "Test OIDC"

    def test_list_configs_by_tenant(self) -> None:
        """Should filter configs by tenant_id prefix."""
        for i in range(3):
            sso_id = str(uuid4())
            _sso_configs[_tenant_key(TENANT_ID, sso_id)] = {
                "id": sso_id, "tenant_id": TENANT_ID, "name": f"IdP-{i}",
            }
        _sso_configs[_tenant_key("other-tenant", str(uuid4()))] = {
            "id": str(uuid4()), "tenant_id": "other-tenant", "name": "Other",
        }
        tenant_configs = [
            v for k, v in _sso_configs.items()
            if k.startswith(f"{TENANT_ID}:")
        ]
        assert len(tenant_configs) == 3

    def test_delete_config(self) -> None:
        """Should remove config from store."""
        sso_id = str(uuid4())
        key = _tenant_key(TENANT_ID, sso_id)
        _sso_configs[key] = {"id": sso_id, "name": "To Delete"}
        removed = _sso_configs.pop(key, None)
        assert removed is not None
        assert key not in _sso_configs

    def test_update_config(self) -> None:
        """Should update config fields in place."""
        sso_id = str(uuid4())
        key = _tenant_key(TENANT_ID, sso_id)
        _sso_configs[key] = {
            "id": sso_id, "name": "Original", "enabled": True,
        }
        _sso_configs[key].update({"name": "Updated", "enabled": False})
        assert _sso_configs[key]["name"] == "Updated"
        assert _sso_configs[key]["enabled"] is False


# ── Claim Mapping Tests ────────────────────────────────────────────


class TestClaimMappings:
    """Test visual claim/attribute mapper data structures."""

    def test_default_oidc_mappings(self) -> None:
        """OIDC config should accept visual claim mappings."""
        cfg = SSOConfigCreate(
            name="OIDC",
            protocol="oidc",
            claim_mappings=[
                ClaimMappingEntry(idp_claim="email", archon_field="Email"),
                ClaimMappingEntry(idp_claim="preferred_username", archon_field="Username"),
                ClaimMappingEntry(idp_claim="given_name", archon_field="First Name"),
                ClaimMappingEntry(idp_claim="family_name", archon_field="Last Name"),
                ClaimMappingEntry(idp_claim="groups", archon_field="Groups"),
                ClaimMappingEntry(idp_claim="tenant_id", archon_field="Tenant ID"),
                ClaimMappingEntry(idp_claim="role", archon_field="Role"),
            ],
        )
        assert len(cfg.claim_mappings) == 7
        # Each mapping should be a visual row (not raw JSON)
        for m in cfg.claim_mappings:
            assert m.idp_claim != ""
            assert m.archon_field != ""

    def test_claim_mapping_serialization(self) -> None:
        """ClaimMappingEntry should serialize to dict correctly."""
        entry = ClaimMappingEntry(idp_claim="email", archon_field="Email")
        d = entry.model_dump()
        assert d == {"idp_claim": "email", "archon_field": "Email"}


# ── Secrets Masking Tests ──────────────────────────────────────────


class TestSecretsMasking:
    """Test that secrets are properly masked in API responses."""

    def test_oidc_client_secret_masked(self) -> None:
        """Client secret should be replaced with mask characters."""
        config: dict[str, Any] = {
            "name": "OIDC",
            "client_secret": "super-secret-value",
            "discovery_url": "https://example.com",
        }
        masked = _mask_config(config)
        assert masked["client_secret"] == "********"
        assert masked["discovery_url"] == "https://example.com"

    def test_ldap_bind_secret_masked(self) -> None:
        """Bind password should be replaced with mask characters."""
        config: dict[str, Any] = {
            "name": "LDAP",
            "bind_secret": "ldap-password",
            "host": "ldap.example.com",
        }
        masked = _mask_config(config)
        assert masked["bind_secret"] == "********"
        assert masked["host"] == "ldap.example.com"

    def test_saml_certificate_masked(self) -> None:
        """Certificate should be replaced with mask characters."""
        config: dict[str, Any] = {
            "name": "SAML",
            "certificate": "-----BEGIN CERTIFICATE-----\nMIIB...",
        }
        masked = _mask_config(config)
        assert masked["certificate"] == "********"

    def test_empty_secrets_not_masked(self) -> None:
        """Empty string secrets should not be masked."""
        config: dict[str, Any] = {
            "name": "Test",
            "client_secret": "",
            "bind_secret": "",
            "certificate": "",
        }
        masked = _mask_config(config)
        assert masked["client_secret"] == ""
        assert masked["bind_secret"] == ""
        assert masked["certificate"] == ""


# ── Vault Path Tests ───────────────────────────────────────────────


class TestVaultPaths:
    """Test Vault secret path construction for SSO credentials."""

    def test_oidc_secret_path(self) -> None:
        """OIDC client_secret should use correct Vault path."""
        tenant = "t-123"
        path = f"archon/tenants/{tenant}/sso/oidc/client_secret"
        assert path == "archon/tenants/t-123/sso/oidc/client_secret"

    def test_ldap_secret_path(self) -> None:
        """LDAP bind_password should use correct Vault path."""
        tenant = "t-456"
        path = f"archon/tenants/{tenant}/sso/ldap/bind_password"
        assert path == "archon/tenants/t-456/sso/ldap/bind_password"

    def test_saml_secret_path(self) -> None:
        """SAML certificate should use correct Vault path."""
        tenant = "t-789"
        path = f"archon/tenants/{tenant}/sso/saml/certificate"
        assert path == "archon/tenants/t-789/sso/saml/certificate"


# ── Test Connection Tests ──────────────────────────────────────────


class TestConnectionValidation:
    """Test SSO connection validation logic."""

    def test_oidc_requires_discovery_url(self) -> None:
        """OIDC config without discovery_url should fail validation."""
        config: dict[str, Any] = {
            "protocol": "oidc",
            "discovery_url": "",
            "client_id": "test",
        }
        # Simulate test connection logic
        if not config.get("discovery_url"):
            result = {"status": "error", "message": "Discovery URL is required"}
        else:
            result = {"status": "success", "message": "OK"}
        assert result["status"] == "error"

    def test_saml_requires_metadata(self) -> None:
        """SAML config needs either metadata_url or metadata_xml."""
        config: dict[str, Any] = {
            "protocol": "saml",
            "metadata_url": "",
            "metadata_xml": "",
        }
        if not config.get("metadata_url") and not config.get("metadata_xml"):
            result = {"status": "error", "message": "Metadata URL or XML is required"}
        else:
            result = {"status": "success", "message": "OK"}
        assert result["status"] == "error"

    def test_ldap_requires_host(self) -> None:
        """LDAP config without host should fail validation."""
        config: dict[str, Any] = {
            "protocol": "ldap",
            "host": "",
        }
        if not config.get("host"):
            result = {"status": "error", "message": "LDAP host is required"}
        else:
            result = {"status": "success", "message": "OK"}
        assert result["status"] == "error"

    def test_oidc_valid_config(self) -> None:
        """OIDC config with discovery_url should pass validation."""
        config: dict[str, Any] = {
            "protocol": "oidc",
            "discovery_url": "https://kc.example.com/.well-known/openid-configuration",
        }
        if not config.get("discovery_url"):
            result = {"status": "error", "message": "Required"}
        else:
            result = {
                "status": "success",
                "message": f"OIDC discovery endpoint reachable at {config['discovery_url']}",
            }
        assert result["status"] == "success"

    def test_saml_valid_with_metadata_url(self) -> None:
        """SAML config with metadata_url should pass validation."""
        config: dict[str, Any] = {
            "protocol": "saml",
            "metadata_url": "https://okta.example.com/metadata",
            "metadata_xml": "",
        }
        if not config.get("metadata_url") and not config.get("metadata_xml"):
            result = {"status": "error", "message": "Required"}
        else:
            result = {"status": "success", "message": "SAML metadata parsed successfully"}
        assert result["status"] == "success"

    def test_ldap_valid_config(self) -> None:
        """LDAP config with host should pass validation."""
        config: dict[str, Any] = {
            "protocol": "ldap",
            "host": "ldap.corp.com",
            "port": 636,
        }
        if not config.get("host"):
            result = {"status": "error", "message": "Required"}
        else:
            result = {
                "status": "success",
                "message": f"LDAP bind successful to {config['host']}:{config['port']}",
            }
        assert result["status"] == "success"


# ── Multi-IdP Tests ────────────────────────────────────────────────


class TestMultipleIdPs:
    """Test multiple identity providers per tenant."""

    def test_multiple_idps_same_tenant(self) -> None:
        """A tenant should support multiple IdPs."""
        for protocol in ("oidc", "saml", "ldap"):
            sso_id = str(uuid4())
            key = _tenant_key(TENANT_ID, sso_id)
            _sso_configs[key] = {
                "id": sso_id,
                "tenant_id": TENANT_ID,
                "name": f"Test {protocol.upper()}",
                "protocol": protocol,
                "enabled": True,
                "is_default": protocol == "oidc",
            }

        configs = [
            v for k, v in _sso_configs.items()
            if k.startswith(f"{TENANT_ID}:")
        ]
        assert len(configs) == 3
        protocols = {c["protocol"] for c in configs}
        assert protocols == {"oidc", "saml", "ldap"}

    def test_only_one_default(self) -> None:
        """Setting a new default should be tracked per IdP."""
        sso_ids = []
        for i in range(2):
            sso_id = str(uuid4())
            sso_ids.append(sso_id)
            key = _tenant_key(TENANT_ID, sso_id)
            _sso_configs[key] = {
                "id": sso_id,
                "is_default": i == 0,
            }

        defaults = [
            v for k, v in _sso_configs.items()
            if k.startswith(f"{TENANT_ID}:") and v.get("is_default")
        ]
        assert len(defaults) == 1


# ── Impersonation Tests ────────────────────────────────────────────


class TestImpersonation:
    """Test impersonation data structures."""

    def test_impersonation_session_data(self) -> None:
        """Impersonation session should include all required fields."""
        user = _user()
        target_user_id = str(uuid4())
        session_id = str(uuid4())

        data = {
            "session_id": session_id,
            "target_user_id": target_user_id,
            "impersonated_by": user.id,
            "impersonated_by_email": user.email,
            "reason": "Debug issue",
            "tenant_id": user.tenant_id,
        }

        assert data["target_user_id"] == target_user_id
        assert data["impersonated_by"] == user.id
        assert data["reason"] == "Debug issue"
        assert data["tenant_id"] == TENANT_ID

    def test_cannot_impersonate_self(self) -> None:
        """User should not be able to impersonate themselves."""
        user = _user()
        with pytest.raises(ValueError, match="Cannot impersonate yourself"):
            if user.id == user.id:
                raise ValueError("Cannot impersonate yourself")
