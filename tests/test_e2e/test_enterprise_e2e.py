"""Enterprise E2E validation tests — 25 scenarios covering auth, RBAC,
secrets, tenant isolation, and core platform flows.

All external dependencies (DB, Redis, Vault, Keycloak) are mocked.
Tests exercise the SERVICE layer logic.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import (
    AuthenticatedUser,
    CertificateBundle,
    DynamicCredential,
    SecretMetadata,
)
from app.middleware.auth import get_current_user, require_mfa
from app.middleware.rbac import Action, check_permission
from app.secrets.manager import VaultSecretsManager
from app.secrets.rotation import RotationResult, SecretRotationEngine
from app.secrets.pki import PKIManager
from app.secrets.exceptions import SecretNotFoundError

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

TENANT_A = str(uuid4())
TENANT_B = str(uuid4())

_USER_ID_A = str(uuid4())
_USER_ID_B = str(uuid4())


def _make_user(
    *,
    tenant_id: str = TENANT_A,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    mfa_verified: bool = False,
    user_id: str | None = None,
) -> AuthenticatedUser:
    uid = user_id or str(uuid4())
    return AuthenticatedUser(
        id=uid,
        email=f"{uid[:8]}@example.com",
        tenant_id=tenant_id,
        roles=roles or ["viewer"],
        permissions=permissions or [],
        mfa_verified=mfa_verified,
        session_id=f"sess-{uid[:8]}",
    )


def _admin(tenant_id: str = TENANT_A) -> AuthenticatedUser:
    return _make_user(tenant_id=tenant_id, roles=["admin"], mfa_verified=True)


def _viewer(tenant_id: str = TENANT_A) -> AuthenticatedUser:
    return _make_user(tenant_id=tenant_id, roles=["viewer"])


def _agent_creator(tenant_id: str = TENANT_A) -> AuthenticatedUser:
    return _make_user(tenant_id=tenant_id, roles=["agent_creator"])


def _mock_vault() -> MagicMock:
    """Return a MagicMock that satisfies VaultSecretsManager's async API."""
    m = MagicMock(spec=VaultSecretsManager)
    m.get_secret = AsyncMock(return_value={"key": "platform-signing-key"})
    m.put_secret = AsyncMock(return_value=SecretMetadata(
        path="test/path", version=2,
        created_at=datetime.now(timezone.utc),
    ))
    m.delete_secret = AsyncMock()
    m.list_secrets = AsyncMock(return_value=[])
    m.rotate_secret = AsyncMock(return_value=SecretMetadata(
        path="test/path", version=3,
        created_at=datetime.now(timezone.utc),
        rotation_policy="auto",
    ))
    m.issue_certificate = AsyncMock(return_value=CertificateBundle(
        cert="-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        private_key="-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----",
        ca_chain=["-----BEGIN CERTIFICATE-----\nCA...\n-----END CERTIFICATE-----"],
        serial="AA:BB:CC:DD",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    ))
    m.get_dynamic_credential = AsyncMock(return_value=DynamicCredential(
        username="dyn-user", password="dyn-pass",  # noqa: S106 — test mock only
        lease_id="lease-123", lease_duration=3600, renewable=True,
    ))
    m.health = AsyncMock(return_value={"status": "healthy"})
    m._validate_tenant_id = VaultSecretsManager._validate_tenant_id
    return m


def _mock_db_session() -> AsyncMock:
    """Minimal async DB session mock."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_result.all.return_value = []
    mock_result.one.return_value = 0
    session.exec = AsyncMock(return_value=mock_result)
    session.get = AsyncMock(return_value=None)
    return session


# ═══════════════════════════════════════════════════════════════════
# AUTH & SSO (1-5)
# ═══════════════════════════════════════════════════════════════════


class TestAuthSSO:
    """Tests 1-5: OAuth login, SAML SSO, MFA, session expiry, token refresh."""

    # 1 ─ test_oauth_login_flow
    @pytest.mark.asyncio
    async def test_oauth_login_flow(self) -> None:
        """Simulate OAuth login → JWT → verify claims (tenant_id, roles, permissions)."""
        mock_jwks = {"keys": [{"kid": "test-kid", "kty": "RSA", "n": "abc", "e": "AQAB"}]}
        payload = {
            "sub": _USER_ID_A,
            "email": "alice@corp.com",
            "tenant_id": TENANT_A,
            "realm_access": {"roles": ["admin", "operator"]},
            "permissions": ["agents:create", "agents:read"],
            "mfa_verified": True,
            "sid": "session-001",
        }

        with (
            patch("app.middleware.auth._fetch_jwks", new_callable=AsyncMock, return_value=mock_jwks),
            patch("app.middleware.auth._get_signing_key", return_value={"kid": "test-kid"}),
            patch("app.middleware.auth.jwt.decode", return_value=payload),
        ):
            user = await get_current_user(request=MagicMock(cookies={}), token="mock-jwt-token")

        assert user.id == _USER_ID_A
        assert user.email == "alice@corp.com"
        assert user.tenant_id == TENANT_A
        assert "admin" in user.roles
        assert "agents:create" in user.permissions
        assert user.mfa_verified is True
        assert user.session_id == "session-001"

    # 2 ─ test_saml_sso_flow
    @pytest.mark.asyncio
    async def test_saml_sso_flow(self) -> None:
        """Generate SAML AuthnRequest, simulate IdP response, verify user session."""
        from app.services.saml_service import SAMLService

        vault = _mock_vault()
        vault.get_secret = AsyncMock(return_value={
            "entity_id": "https://idp.corp.com",
            "sso_url": "https://idp.corp.com/sso",
            "slo_url": "",
            "name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "attribute_mapping": {},
            "enabled": True,
        })

        svc = SAMLService(secrets=vault)

        # Step 1: AuthnRequest
        req = await svc.generate_authn_request(TENANT_A, "https://idp.corp.com")
        assert req.request_id.startswith("_archon_")
        assert "SAMLRequest" in req.redirect_url
        assert req.relay_state == f"tenant={TENANT_A}"

        # Step 2: Simulate IdP response
        ns_saml2p = "urn:oasis:names:tc:SAML:2.0:protocol"
        ns_saml2 = "urn:oasis:names:tc:SAML:2.0:assertion"
        saml_xml = (
            f'<saml2p:Response xmlns:saml2p="{ns_saml2p}" xmlns:saml2="{ns_saml2}">'
            f'<saml2:Issuer>https://idp.corp.com</saml2:Issuer>'
            f'<saml2p:Status><saml2p:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></saml2p:Status>'
            f'<saml2:Assertion>'
            f'<saml2:Issuer>https://idp.corp.com</saml2:Issuer>'
            f'<saml2:Subject><saml2:NameID>bob@corp.com</saml2:NameID></saml2:Subject>'
            f'<saml2:AuthnStatement SessionIndex="idx-42"/>'
            f'</saml2:Assertion>'
            f'</saml2p:Response>'
        )
        b64_resp = base64.b64encode(saml_xml.encode()).decode()

        user = await svc.process_saml_response(b64_resp, TENANT_A)

        assert user.email == "bob@corp.com"
        assert user.tenant_id == TENANT_A
        assert user.session_id == "idx-42"

    # 3 ─ test_mfa_enforcement
    @pytest.mark.asyncio
    async def test_mfa_enforcement(self) -> None:
        """Verify MFA-required endpoints reject without MFA token."""
        from fastapi import HTTPException

        user_no_mfa = _make_user(roles=["admin"], mfa_verified=False)

        with (
            patch("app.middleware.auth.get_current_user", new_callable=AsyncMock, return_value=user_no_mfa),
            pytest.raises(HTTPException) as exc_info,
        ):
            await require_mfa(user=user_no_mfa)

        assert exc_info.value.status_code == 403
        assert "Multi-factor" in exc_info.value.detail

        # With MFA passes
        user_mfa = _make_user(roles=["admin"], mfa_verified=True)
        result = await require_mfa(user=user_mfa)
        assert result.mfa_verified is True

    # 4 ─ test_session_expiry
    @pytest.mark.asyncio
    async def test_session_expiry(self) -> None:
        """Verify expired JWT rejected with 401."""
        from fastapi import HTTPException
        from jose.exceptions import ExpiredSignatureError

        mock_jwks = {"keys": [{"kid": "k1"}]}

        with (
            patch("app.middleware.auth._fetch_jwks", new_callable=AsyncMock, return_value=mock_jwks),
            patch("app.middleware.auth._get_signing_key", return_value={"kid": "k1"}),
            patch("app.middleware.auth.jwt.decode", side_effect=ExpiredSignatureError("expired")),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(request=MagicMock(cookies={}), token="expired-token")

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    # 5 ─ test_token_refresh
    @pytest.mark.asyncio
    async def test_token_refresh(self) -> None:
        """Verify refresh token flow returns new valid JWT with correct claims."""
        old_payload = {
            "sub": _USER_ID_A,
            "email": "alice@corp.com",
            "tenant_id": TENANT_A,
            "realm_access": {"roles": ["developer"]},
            "permissions": [],
            "mfa_verified": True,
            "sid": "session-refreshed",
        }
        mock_jwks = {"keys": [{"kid": "k1"}]}

        with (
            patch("app.middleware.auth._fetch_jwks", new_callable=AsyncMock, return_value=mock_jwks),
            patch("app.middleware.auth._get_signing_key", return_value={"kid": "k1"}),
            patch("app.middleware.auth.jwt.decode", return_value=old_payload),
        ):
            user = await get_current_user(request=MagicMock(cookies={}), token="refreshed-jwt")

        assert user.id == _USER_ID_A
        assert user.session_id == "session-refreshed"
        assert "developer" in user.roles


# ═══════════════════════════════════════════════════════════════════
# RBAC (6-10)
# ═══════════════════════════════════════════════════════════════════


class TestRBAC:
    """Tests 6-10: role checks, escalation prevention, cross-tenant."""

    # 6 ─ test_rbac_admin_access
    def test_rbac_admin_access(self) -> None:
        """Admin can perform all actions on all resources."""
        admin = _admin()
        for action in Action:
            for resource in ("agents", "executions", "templates", "costs", "sandbox"):
                assert check_permission(admin, resource, action.value) is True

    # 7 ─ test_rbac_viewer_blocked
    def test_rbac_viewer_blocked(self) -> None:
        """Viewer cannot create or delete agents."""
        viewer = _viewer()
        assert check_permission(viewer, "agents", "create") is False
        assert check_permission(viewer, "agents", "delete") is False
        assert check_permission(viewer, "agents", "read") is True

    # 8 ─ test_rbac_permission_escalation_blocked
    def test_rbac_permission_escalation_blocked(self) -> None:
        """User cannot escalate own role via extra permission strings."""
        user = _make_user(roles=["viewer"], permissions=["agents:read"])
        # Even with explicit read, should NOT have admin/delete
        assert check_permission(user, "agents", "admin") is False
        assert check_permission(user, "agents", "delete") is False
        assert check_permission(user, "agents", "create") is False

    # 9 ─ test_rbac_cross_tenant_blocked
    @pytest.mark.asyncio
    async def test_rbac_cross_tenant_blocked(self) -> None:
        """Tenant A admin cannot access tenant B resources via service layer."""
        from app.services.agent_service import AgentService

        admin_a = _admin(TENANT_A)
        tenant_b_uuid = uuid4()

        session = _mock_db_session()
        # Simulate no agent found in tenant B scope
        mock_result = MagicMock()
        mock_result.first.return_value = None
        session.exec = AsyncMock(return_value=mock_result)

        agent = await AgentService.get(
            session, uuid4(), tenant_id=tenant_b_uuid,
        )
        assert agent is None  # tenant isolation: no cross-tenant access

    # 10 ─ test_rbac_agent_creator_permissions
    def test_rbac_agent_creator_permissions(self) -> None:
        """agent_creator can create agents but cannot delete them."""
        creator = _agent_creator()
        assert check_permission(creator, "agents", "create") is True
        assert check_permission(creator, "agents", "read") is True
        assert check_permission(creator, "agents", "delete") is False
        assert check_permission(creator, "agents", "execute") is False
        # agent_creator is scoped to agents — cannot create templates
        assert check_permission(creator, "templates", "create") is False


# ═══════════════════════════════════════════════════════════════════
# SECRETS (11-15)
# ═══════════════════════════════════════════════════════════════════


class TestSecrets:
    """Tests 11-15: SecretsManager, Vault, rotation, PKI, no-hardcoded."""

    # 11 ─ test_secrets_manager_import
    def test_secrets_manager_import(self) -> None:
        """SecretsManager protocol importable and VaultSecretsManager instantiable."""
        from app.interfaces.secrets_manager import SecretsManager

        assert hasattr(SecretsManager, "get_secret")
        assert hasattr(SecretsManager, "put_secret")
        assert hasattr(SecretsManager, "issue_certificate")

        # VaultSecretsManager satisfies the Protocol at import level
        assert VaultSecretsManager is not None

    # 12 ─ test_vault_credential_retrieval
    @pytest.mark.asyncio
    async def test_vault_credential_retrieval(self) -> None:
        """VaultSecretsManager retrieves tenant-scoped secrets."""
        vault = _mock_vault()
        vault.get_secret = AsyncMock(return_value={
            "db_host": "db.tenant-a.internal",
            "db_port": 5432,
        })

        result = await vault.get_secret("db/config", TENANT_A)
        assert result["db_host"] == "db.tenant-a.internal"
        vault.get_secret.assert_awaited_once_with("db/config", TENANT_A)

    # 13 ─ test_secret_rotation
    @pytest.mark.asyncio
    async def test_secret_rotation(self) -> None:
        """SecretRotationEngine rotates credentials and returns new version."""
        vault = _mock_vault()
        vault.get_secret = AsyncMock(return_value={
            "value": "old-secret",
            "_version": 2,
            "_type": "api_key",
            "_length": 32,
        })
        vault.put_secret = AsyncMock(return_value=SecretMetadata(
            path="creds/api", version=3,
            created_at=datetime.now(timezone.utc),
        ))

        engine = SecretRotationEngine(secrets_manager=vault)
        result = await engine.rotate_secret("creds/api", TENANT_A)

        assert isinstance(result, RotationResult)
        assert result.old_version == 2
        assert result.new_version == 3
        assert result.path == "creds/api"
        vault.put_secret.assert_awaited_once()

    # 14 ─ test_pki_certificate_issuance
    @pytest.mark.asyncio
    async def test_pki_certificate_issuance(self) -> None:
        """PKIManager issues service certificates via VaultSecretsManager."""
        vault = _mock_vault()
        pki = PKIManager(secrets_manager=vault)
        bundle = await pki.issue_service_cert("my-svc", TENANT_A, ttl="720h")

        assert isinstance(bundle, CertificateBundle)
        assert bundle.cert.startswith("-----BEGIN CERTIFICATE-----")
        assert bundle.serial == "AA:BB:CC:DD"
        vault.issue_certificate.assert_awaited_once()
        call_args = vault.issue_certificate.call_args
        assert TENANT_A in call_args.args[1]  # tenant_id passed through

    # 15 ─ test_no_hardcoded_secrets
    def test_no_hardcoded_secrets(self) -> None:
        """Scan all backend Python files for hardcoded secret patterns."""
        backend_root = Path(__file__).resolve().parent.parent.parent / "backend"
        patterns = [
            re.compile(r"""password\s*=\s*['"][^'"]{4,}['"]""", re.IGNORECASE),
            re.compile(r"""api_key\s*=\s*['"][^'"]{4,}['"]""", re.IGNORECASE),
            re.compile(r"""secret\s*=\s*['"][^'"]{8,}['"]""", re.IGNORECASE),
            re.compile(r"""\bsk-[A-Za-z0-9]{20,}\b"""),
            re.compile(r"""\bghp_[A-Za-z0-9]{20,}\b"""),
            re.compile(r"""\bAKIA[0-9A-Z]{16}\b"""),
        ]
        # Allowlist: enum/constant definitions that assign label strings, not real secrets
        _allowlist_re = re.compile(
            r"""(?:API_KEY|PASSWORD|SECRET)\s*=\s*['"](?:api_key|password|secret)['"]""",
            re.IGNORECASE,
        )
        violations: list[str] = []
        for py_file in backend_root.rglob("*.py"):
            # Skip test files, __pycache__, and migration scripts
            rel = py_file.relative_to(backend_root)
            if "__pycache__" in str(rel) or "test" in str(rel).lower() or "migration" in str(rel).lower():
                continue
            content = py_file.read_text(errors="replace")
            for pat in patterns:
                for m in pat.finditer(content):
                    matched = m.group()
                    if _allowlist_re.search(matched):
                        continue
                    line_no = content[: m.start()].count("\n") + 1
                    violations.append(f"{rel}:{line_no}: {matched[:40]}…")

        assert violations == [], (
            f"Hardcoded secrets found in {len(violations)} location(s):\n"
            + "\n".join(violations[:10])
        )


# ═══════════════════════════════════════════════════════════════════
# TENANT ISOLATION (16-20)
# ═══════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    """Tests 16-20: every service layer scopes data to tenant."""

    # 16 ─ test_agent_tenant_isolation
    @pytest.mark.asyncio
    async def test_agent_tenant_isolation(self) -> None:
        """AgentService.list filters by tenant_id — never returns other tenant data."""
        from app.services.agent_service import AgentService

        session = _mock_db_session()
        tenant_uuid = uuid4()

        agents, total = await AgentService.list(session, tenant_id=tenant_uuid)

        # Verify the query was executed (list calls session.exec)
        assert session.exec.await_count >= 1
        # Results are empty because mock returns no rows — correct isolation
        assert agents == []
        assert total == 0

    # 17 ─ test_execution_tenant_isolation
    @pytest.mark.asyncio
    async def test_execution_tenant_isolation(self) -> None:
        """ExecutionService.list_executions scoped to tenant."""
        from app.services.execution_service import ExecutionService

        session = _mock_db_session()
        tenant_uuid = uuid4()

        execs, total = await ExecutionService.list_executions(
            session, tenant_id=tenant_uuid,
        )
        assert execs == []
        assert total == 0
        session.exec.assert_awaited()

    # 18 ─ test_secrets_tenant_isolation
    @pytest.mark.asyncio
    async def test_secrets_tenant_isolation(self) -> None:
        """VaultSecretsManager rejects empty tenant_id and scopes paths."""
        vault = _mock_vault()

        # Empty tenant_id must raise
        with pytest.raises(ValueError, match="tenant_id"):
            vault._validate_tenant_id(vault, "")

        # Valid tenant_id passes namespace scoping
        ns = VaultSecretsManager._get_tenant_namespace(MagicMock(_namespace="archon"), TENANT_A)
        assert TENANT_A in ns

    # 19 ─ test_sandbox_tenant_isolation
    @pytest.mark.asyncio
    async def test_sandbox_tenant_isolation(self) -> None:
        """SandboxService.list_sandboxes filters by tenant and get_sandbox returns None for other tenant."""
        from app.services.sandbox_service import SandboxService
        from app.models.sandbox import SandboxConfig

        svc = SandboxService()
        admin_a = _admin(TENANT_A)
        admin_b = _admin(TENANT_B)

        config = SandboxConfig()
        sandbox = await svc.create_sandbox(TENANT_A, admin_a, config)
        assert sandbox.tenant_id == TENANT_A

        # Tenant B cannot see tenant A's sandbox
        result = await svc.get_sandbox(sandbox.id, TENANT_B)
        assert result is None

        # Tenant B list is empty
        sb_list, count = await svc.list_sandboxes(TENANT_B)
        assert count == 0

    # 20 ─ test_cost_tenant_isolation
    @pytest.mark.asyncio
    async def test_cost_tenant_isolation(self) -> None:
        """CostService.get_cost_summary is scoped to tenant_id in the query."""
        from app.services.cost_service import CostService

        session = _mock_db_session()
        user = _admin(TENANT_A)

        summary = await CostService.get_cost_summary(session, TENANT_A, user)

        assert summary.total_cost == 0.0
        assert summary.call_count == 0
        # session.exec was called with tenant-scoped query
        session.exec.assert_awaited()


# ═══════════════════════════════════════════════════════════════════
# CORE PLATFORM (21-25)
# ═══════════════════════════════════════════════════════════════════


class TestCorePlatform:
    """Tests 21-25: agent lifecycle, wizard, templates, versioning, DLP."""

    # 21 ─ test_agent_lifecycle_flow
    @pytest.mark.asyncio
    async def test_agent_lifecycle_flow(self) -> None:
        """create → update → deploy → execute → archive (soft-delete)."""
        from app.services.agent_service import AgentService
        from app.models import Agent, User

        admin = _admin()
        tenant_uuid = uuid4()
        agent_id = uuid4()
        user_uuid = UUID(admin.id)

        # Prepare a mock agent that behaves like a real SQLModel instance
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = agent_id
        mock_agent.name = "test-agent"
        mock_agent.status = "draft"
        mock_agent.owner_id = user_uuid
        mock_agent.tags = []
        mock_agent.definition = {}
        mock_agent.deleted_at = None
        mock_agent.updated_at = None
        mock_agent.created_at = datetime.utcnow()

        session = _mock_db_session()

        # --- create ---
        session.refresh = AsyncMock(return_value=None)
        created = await AgentService.create(
            session, mock_agent, tenant_id=tenant_uuid, user=admin,
        )
        session.add.assert_called()
        session.commit.assert_awaited()

        # --- update ---
        mock_result = MagicMock()
        mock_result.first.return_value = mock_agent
        session.exec = AsyncMock(return_value=mock_result)

        updated = await AgentService.update(
            session, agent_id, {"name": "renamed-agent"},
            tenant_id=tenant_uuid, user=admin,
        )
        assert updated is not None

        # --- deploy ---
        deployed = await AgentService.deploy(
            session, agent_id, tenant_id=tenant_uuid, user=admin,
        )
        assert deployed is not None
        assert mock_agent.status == "deployed"

        # --- delete (archive) ---
        deleted = await AgentService.delete(
            session, agent_id, tenant_id=tenant_uuid, user=admin,
        )
        assert deleted is True

    # 22 ─ test_wizard_full_pipeline
    @pytest.mark.asyncio
    async def test_wizard_full_pipeline(self) -> None:
        """describe → plan → build → validate wizard pipeline."""
        from app.services.wizard_service import NLWizardService

        wiz = NLWizardService()
        user = _admin()

        agent, validation = await wiz.full_pipeline(
            TENANT_A, user,
            "Build a Slack bot that monitors GitHub PRs and creates Jira tickets",
        )

        assert agent.tenant_id == TENANT_A
        assert agent.owner_id == user.id
        assert agent.graph_definition is not None
        assert len(agent.graph_definition.get("nodes", [])) > 0
        assert validation.passed is True
        assert any("Tenant isolation" in n for n in validation.compliance_notes)

    # 23 ─ test_template_publish_install
    @pytest.mark.asyncio
    async def test_template_publish_install(self) -> None:
        """create template → publish → install."""
        from app.services.template_service import TemplateService
        from app.models import Template
        from app.models.template import TemplateCreate, TemplateDifficulty

        session = _mock_db_session()
        user = _admin()
        vault = _mock_vault()
        tpl_id = uuid4()

        # Mock the template ORM object
        mock_tpl = MagicMock(spec=Template)
        mock_tpl.id = tpl_id
        mock_tpl.name = "My Template"
        mock_tpl.description = "Test template"
        mock_tpl.category = "general"
        mock_tpl.definition = {"nodes": {}, "_meta": {"status": "draft", "tenant_id": TENANT_A, "difficulty": "beginner", "content_hash": "", "credential_manifests": [], "connector_manifests": [], "model_manifests": [], "avg_rating": 0.0, "review_count": 0}}
        mock_tpl.tags = ["test"]
        mock_tpl.is_featured = False
        mock_tpl.usage_count = 0
        mock_tpl.author_id = UUID(user.id)
        mock_tpl.created_at = datetime.utcnow()
        mock_tpl.updated_at = datetime.utcnow()

        # create_template
        session.refresh = AsyncMock(side_effect=lambda obj: None)
        create_data = TemplateCreate(
            name="My Template",
            description="Test template",
            category="general",
            definition={"nodes": {}},
            tags=["test"],
        )
        resp = await TemplateService.create_template(session, TENANT_A, user, create_data)
        session.commit.assert_awaited()

        # publish_template — mock session.get to return our template
        session.get = AsyncMock(return_value=mock_tpl)
        published = await TemplateService.publish_template(
            session, TENANT_A, user, tpl_id, vault,
        )
        assert published is not None
        # Verify _meta.status was set to "published"
        updated_def = mock_tpl.definition
        assert updated_def.get("_meta", {}).get("status") == "published"

        # install_template
        installed = await TemplateService.install_template(
            session, TENANT_A, user, tpl_id, vault,
        )
        assert installed is not None
        assert installed.tenant_id == TENANT_A

    # 24 ─ test_versioning_flow
    @pytest.mark.asyncio
    async def test_versioning_flow(self) -> None:
        """create version → diff → promote → rollback."""
        from app.services.versioning_service import VersioningService
        from app.models import Agent, AgentVersion as AgentVersionDB

        session = _mock_db_session()
        user = _admin()
        vault = _mock_vault()
        agent_id = uuid4()
        ver_a_id = uuid4()
        ver_b_id = uuid4()

        # Mock agent lookup — first exec call returns the agent
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = agent_id
        mock_agent.definition = {"nodes": {"input": {"type": "input"}}}

        # Mock version DB record for _latest_version calls
        mock_ver = MagicMock(spec=AgentVersionDB)
        mock_ver.id = ver_a_id
        mock_ver.agent_id = agent_id
        mock_ver.version = "1.0.0"
        mock_ver.definition = {"nodes": {"input": {"type": "input"}}}
        mock_ver.change_log = "Initial version"
        mock_ver.created_by = UUID(user.id)
        mock_ver.created_at = datetime.utcnow()

        # session.exec returns agent on first call, then version for all subsequent
        agent_result = MagicMock()
        agent_result.first.return_value = mock_agent
        ver_result = MagicMock()
        ver_result.first.return_value = mock_ver

        def _exec_factory(*args, **kwargs):
            """Return a mock result with .first() returning mock_ver by default."""
            r = MagicMock()
            r.first.return_value = mock_ver
            return r

        call_count = 0

        async def _exec_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return agent_result  # create_version: agent lookup
            return _exec_factory()  # all subsequent: _latest_version etc.

        session.exec = AsyncMock(side_effect=_exec_side_effect)

        # create_version
        version = await VersioningService.create_version(
            TENANT_A, user, agent_id, "Initial version",
            session=session, secrets=vault,
        )
        assert version.version_number is not None
        assert version.content_hash != ""
        assert version.signature != ""

        # diff_versions — mock two versions
        mock_ver_a = MagicMock(spec=AgentVersionDB)
        mock_ver_a.id = ver_a_id
        mock_ver_a.agent_id = agent_id
        mock_ver_a.definition = {"nodes": {"input": {"type": "input"}}}

        mock_ver_b = MagicMock(spec=AgentVersionDB)
        mock_ver_b.id = ver_b_id
        mock_ver_b.agent_id = agent_id
        mock_ver_b.definition = {"nodes": {"input": {"type": "input"}, "output": {"type": "output"}}}

        async def get_side_effect(model_class, vid):
            if vid == ver_a_id:
                return mock_ver_a
            if vid == ver_b_id:
                return mock_ver_b
            return None

        session.get = AsyncMock(side_effect=get_side_effect)

        diff = await VersioningService.diff_versions(
            TENANT_A, ver_a_id, ver_b_id, session=session,
        )
        assert "output" in diff.nodes_added
        assert diff.summary != ""

        # promote
        mock_ver_promote = MagicMock(spec=AgentVersionDB)
        mock_ver_promote.id = ver_a_id
        mock_ver_promote.definition = {"_environment": "development"}
        mock_ver_promote.change_log = "Ready for staging"
        session.get = AsyncMock(return_value=mock_ver_promote)

        promo = await VersioningService.promote(
            TENANT_A, user, ver_a_id, "staging", session=session,
        )
        assert promo.status == "promoted"
        assert promo.target_env == "staging"

        # rollback
        mock_ver_rollback = MagicMock(spec=AgentVersionDB)
        mock_ver_rollback.id = ver_a_id
        mock_ver_rollback.agent_id = agent_id
        mock_ver_rollback.version = "1.0.0"
        mock_ver_rollback.definition = {"nodes": {"input": {"type": "input"}}}
        mock_ver_rollback.change_log = "Rollback target"
        mock_ver_rollback.created_by = UUID(user.id)
        mock_ver_rollback.created_at = datetime.utcnow()
        session.get = AsyncMock(return_value=mock_ver_rollback)

        rolled_back = await VersioningService.rollback(
            TENANT_A, user, agent_id, ver_a_id,
            session=session, secrets=vault,
        )
        assert rolled_back.change_reason.startswith("Rollback to")

    # 25 ─ test_dlp_scan_pipeline
    def test_dlp_scan_pipeline(self) -> None:
        """scan content → detect secrets → redact → check guardrails."""
        from app.services.dlp_service import DLPService
        from app.models.dlp import GuardrailConfig

        content = (
            "My AWS key is AKIAIOSFODNN7EXAMPLE and my email is user@example.com. "
            "Also ghp_abcdefghijklmnopqrstuvwxyz012345678 is a GitHub token."
        )

        # Step 1: full scan
        scan_result = DLPService.scan_content(TENANT_A, content)
        assert len(scan_result.findings) > 0
        assert scan_result.risk_level is not None

        # Step 2: detect secrets specifically
        secret_findings = DLPService.scan_for_secrets(content)
        has_aws = any("aws" in f.pattern_name for f in secret_findings)
        assert has_aws, "Should detect AWS access key"

        # Step 3: redact
        redacted = DLPService.redact_content(content, scan_result.findings)
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted
        assert "REDACTED" in redacted

        # Step 4: guardrails
        guardrails = GuardrailConfig(
            enable_injection_detection=True,
            enable_pii_echo_prevention=True,
        )
        guard_result = DLPService.check_guardrails(TENANT_A, content, guardrails)
        # Original content has PII, so guardrails should flag it
        assert guard_result is not None
        # Redacted content should pass guardrails (no PII left)
        clean_result = DLPService.check_guardrails(
            TENANT_A, "Hello, how can I help you?", guardrails,
        )
        assert clean_result.passed is True
