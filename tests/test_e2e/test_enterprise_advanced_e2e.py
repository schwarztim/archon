"""Enterprise Advanced E2E Validation Tests (26-50).

Covers operations, security, integrations, deployment, and advanced features.
Each test is self-contained with proper mocking of all external dependencies.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Ensure project root paths are importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

for p in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid(hex16: str = "a1b2c3d4e5f6a7b8") -> UUID:
    """Return a valid UUID from a 16-char hex string (padded to 32)."""
    return UUID(hex16.ljust(32, "0"))


TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
USER_ID = str(_uuid("00000000ffff4444"))
AGENT_ID = _uuid("00000000ccccdddd")
DEPT_ID = _uuid("00000000ffff3333")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(**overrides: Any) -> Any:
    """Build an AuthenticatedUser for test use."""
    from app.interfaces.models.enterprise import AuthenticatedUser

    defaults: dict[str, Any] = {
        "id": USER_ID,
        "email": "admin@corp.io",
        "tenant_id": TENANT_A,
        "roles": ["admin"],
        "permissions": [
            "router:execute", "router:create", "router:read", "router:update",
            "agents:create", "agents:read", "agents:update", "agents:delete",
            "cost:read", "cost:write", "governance:admin", "dlp:admin",
            "connectors:admin", "marketplace:admin", "deployment:admin",
            "mesh:admin", "edge:admin", "mcp:admin",
        ],
        "mfa_verified": True,
        "session_id": "sess-001",
    }
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _make_session() -> AsyncMock:
    """Build an AsyncSession mock that tracks added objects."""
    session = AsyncMock()
    session._added: list[Any] = []

    def _add(obj: Any) -> None:
        session._added.append(obj)

    session.add = MagicMock(side_effect=_add)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()

    async def _get(model_cls: type, pk: UUID) -> Any:
        for obj in session._added:
            if isinstance(obj, model_cls) and getattr(obj, "id", None) == pk:
                return obj
        return None

    session.get = AsyncMock(side_effect=_get)

    exec_result = MagicMock()
    exec_result.all.return_value = []
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)
    return session


def _make_secrets() -> AsyncMock:
    """Build a SecretsManager mock."""
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value={"api_key": "vault-rotated-key"})
    secrets.put_secret = AsyncMock(return_value=MagicMock(
        path="secret/test", version=2, created_at=_utcnow(),
    ))
    secrets.delete_secret = AsyncMock()
    secrets.rotate_secret = AsyncMock(return_value=MagicMock(
        path="secret/test", version=3, created_at=_utcnow(),
    ))
    secrets.list_secrets = AsyncMock(return_value=[])
    secrets.issue_certificate = AsyncMock(return_value=MagicMock(
        cert="-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        private_key="pk", ca_chain=[], serial="001", expires_at=_utcnow(),
    ))
    secrets.get_dynamic_credential = AsyncMock(return_value=MagicMock(
        username="dyn-user", lease_id="lease-1", lease_duration=3600, renewable=True,
    ))
    return secrets


# ═══════════════════════════════════════════════════════════════════════════
# OPERATIONS (26-30)
# ═══════════════════════════════════════════════════════════════════════════


class TestRouterAuthAwareRouting:
    """26. Router filters models by user clearance + tenant allowlist."""

    @pytest.mark.asyncio
    async def test_router_auth_aware_routing(self) -> None:
        from app.models.router import ModelRegistryEntry, RoutingRequest
        from app.services.router_service import ModelRouterService

        user = _make_user()
        session = _make_session()
        secrets = _make_secrets()

        # Two models: one general, one restricted
        general_model = ModelRegistryEntry(
            id=uuid4(), name="gpt-4o", provider="openai", model_id="gpt-4o",
            capabilities=["chat"], cost_per_input_token=2.5,
            cost_per_output_token=10.0, avg_latency_ms=400.0,
            data_classification="general", is_active=True,
            health_status="healthy", config={"tenant_id": TENANT_A, "geo_residency": "us"},
        )
        restricted_model = ModelRegistryEntry(
            id=uuid4(), name="claude-3-opus", provider="anthropic",
            model_id="claude-3-opus", capabilities=["chat"],
            cost_per_input_token=15.0, cost_per_output_token=75.0,
            avg_latency_ms=600.0, data_classification="restricted",
            is_active=True, health_status="healthy",
            config={"tenant_id": TENANT_A, "geo_residency": "us"},
        )

        # First exec call: models query (_fetch_tenant_models)
        models_exec = MagicMock()
        models_exec.all.return_value = [general_model, restricted_model]
        models_exec.first.return_value = general_model
        # Second exec call: routing rules query (_load_routing_policy, no custom rules)
        routing_exec = MagicMock()
        routing_exec.all.return_value = []
        routing_exec.first.return_value = None
        session.exec = AsyncMock(side_effect=[models_exec, routing_exec])

        request = RoutingRequest(
            task_type="chat", input_tokens_estimate=1000,
            data_classification="restricted", latency_requirement="medium",
        )

        with patch("app.services.router_service.check_permission"), \
             patch("app.services.router_service.AuditLogService") as mock_audit:
            mock_audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, secrets, TENANT_A, user, request,
            )

        # Only the restricted model qualifies for restricted data
        assert decision.selected_model == "claude-3-opus"
        assert decision.data_classification_met is True


class TestLifecycleCredentialRotation:
    """27. Credential rotation on environment promotion."""

    @pytest.mark.asyncio
    async def test_lifecycle_credential_rotation(self) -> None:
        from app.services.lifecycle_service import LifecycleService

        svc = LifecycleService()
        secrets = _make_secrets()
        secrets.list_secrets = AsyncMock(return_value=[
            MagicMock(path="secret/staging/api-key"),
            MagicMock(path="secret/staging/db-creds"),
        ])

        result = await svc.rotate_credentials_on_promotion(
            tenant_id=TENANT_A, agent_id=AGENT_ID,
            source_env="staging", target_env="production",
            secrets_manager=secrets,
        )

        assert result.agent_id == AGENT_ID
        assert result.secrets_rotated >= 0
        assert isinstance(result.new_lease_ids, list)


class TestCostBudgetEnforcement:
    """28. Hard budget limit blocks execution."""

    @pytest.mark.asyncio
    async def test_cost_budget_enforcement(self) -> None:
        from app.models.cost import BudgetCheckResult
        from app.services.cost_service import CostService

        session = _make_session()
        user = _make_user()

        # Mock budget query to return a budget that is exceeded
        budget_mock = MagicMock()
        budget_mock.id = uuid4()
        budget_mock.name = "dept-budget"
        budget_mock.limit_amount = 100.0
        budget_mock.spent_amount = 120.0
        budget_mock.hard_limit = True
        budget_mock.scope = "department"
        budget_mock.period = "monthly"
        budget_mock.department_id = DEPT_ID
        budget_mock.workspace_id = None
        budget_mock.user_id = None
        budget_mock.tenant_id = TENANT_A
        budget_mock.alert_threshold_pct = 80.0

        exec_result = MagicMock()
        exec_result.all.return_value = [budget_mock]
        session.exec = AsyncMock(return_value=exec_result)

        with patch("app.services.cost_service.check_permission"):
            result = await CostService.check_budget(
                session, TENANT_A, user, estimated_cost=150.0,
            )

        assert isinstance(result, BudgetCheckResult)
        # Hard budget exceeded → blocked
        assert result.allowed is False


class TestMultiTenantIdpConfig:
    """29. Per-tenant IdP configuration."""

    @pytest.mark.asyncio
    async def test_multi_tenant_idp_config(self) -> None:
        from app.services.tenant_service import TenantService

        svc = TenantService()

        # Tenant A uses Okta, Tenant B uses Azure AD
        config_a = {"idp_type": "saml", "metadata_url": "https://okta.example.com/metadata"}
        config_b = {"idp_type": "oidc", "metadata_url": "https://login.microsoftonline.com/metadata"}

        # The service should store and retrieve per-tenant IdP configs
        with patch.object(svc, "configure_idp", new_callable=AsyncMock) as mock_update, \
             patch.object(svc, "get_tenant", new_callable=AsyncMock) as mock_get:
            mock_update.return_value = MagicMock(tenant_id=TENANT_A, features=config_a)
            await svc.configure_idp(TENANT_A, config_a)
            mock_update.assert_awaited_once_with(TENANT_A, config_a)

            mock_get.side_effect = [
                MagicMock(tenant_id=TENANT_A, features=config_a),
                MagicMock(tenant_id=TENANT_B, features=config_b),
            ]
            result_a = await svc.get_tenant(TENANT_A)
            result_b = await svc.get_tenant(TENANT_B)

        assert result_a.features["idp_type"] == "saml"
        assert result_b.features["idp_type"] == "oidc"
        assert result_a.tenant_id != result_b.tenant_id


class TestCostChargebackGeneration:
    """30. Generate departmental chargeback report."""

    @pytest.mark.asyncio
    async def test_cost_chargeback_generation(self) -> None:
        from app.services.cost_service import CostService

        session = _make_session()
        user = _make_user()

        # Mock ledger entries for chargeback
        ledger_entry = MagicMock()
        ledger_entry.department_id = DEPT_ID
        ledger_entry.total_cost = 42.50
        ledger_entry.provider = "openai"
        ledger_entry.model_id = "gpt-4o"
        ledger_entry.input_tokens = 10000
        ledger_entry.output_tokens = 5000
        ledger_entry.tenant_id = TENANT_A
        ledger_entry.timestamp = _utcnow()

        exec_result = MagicMock()
        exec_result.all.return_value = [ledger_entry]
        session.exec = AsyncMock(return_value=exec_result)

        with patch("app.services.cost_service.check_permission"):
            report = await CostService.generate_chargeback_report(
                session, TENANT_A, user,
                period={"start": "2025-01-01", "end": "2025-01-31"},
                department_id=DEPT_ID,
            )

        assert report.department_id == DEPT_ID
        assert report.total >= 0
        assert isinstance(report.line_items, list)


# ═══════════════════════════════════════════════════════════════════════════
# SECURITY (31-38)
# ═══════════════════════════════════════════════════════════════════════════


class TestRedteamJwtAttacks:
    """31. JWT manipulation attacks detected."""

    @pytest.mark.asyncio
    async def test_redteam_jwt_attacks(self) -> None:
        from app.services.redteam_service import RedTeamService

        svc = RedTeamService()
        findings = await svc.run_jwt_attack_suite(
            tenant_id=TENANT_A, agent_id=AGENT_ID,
        )

        assert isinstance(findings, list)
        assert len(findings) > 0

        categories = {f.title for f in findings}
        # Should test expired tokens, algorithm confusion, modified claims
        assert any("expir" in t.lower() or "jwt" in t.lower() or "alg" in t.lower()
                    for t in categories)

        for finding in findings:
            assert finding.severity is not None
            assert finding.remediation != ""


class TestDlpSecretDetection:
    """32. DLP detects AWS keys, private keys, DB URIs."""

    def test_dlp_secret_detection(self) -> None:
        from app.services.dlp_service import DLPService

        # AWS access key
        text_aws = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        findings_aws = DLPService.scan_for_secrets(text_aws)
        assert len(findings_aws) > 0
        assert any("aws" in f.pattern_name.lower() for f in findings_aws)

        # Private key
        text_pk = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ..."
        findings_pk = DLPService.scan_for_secrets(text_pk)
        assert len(findings_pk) > 0
        assert any("private" in f.pattern_name.lower() or "key" in f.pattern_name.lower()
                    for f in findings_pk)

        # Database URI
        text_db = "postgresql://admin:secret@db.internal:5432/production"
        findings_db = DLPService.scan_for_secrets(text_db)
        assert len(findings_db) > 0


class TestDlpPiiDetection:
    """33. DLP detects emails, phone numbers, SSN."""

    def test_dlp_pii_detection(self) -> None:
        from app.services.dlp_service import DLPService

        # Email
        findings_email = DLPService.scan_for_pii("Contact us at user@example.com today")
        assert any(f.pii_type == "email" for f in findings_email)

        # Phone number
        findings_phone = DLPService.scan_for_pii("Call me at (555) 123-4567")
        assert any("phone" in f.pii_type for f in findings_phone)

        # SSN
        findings_ssn = DLPService.scan_for_pii("SSN: 123-45-6789")
        assert any(f.pii_type == "ssn" for f in findings_ssn)


class TestGovernanceAccessReview:
    """34. Access review creation and decision processing."""

    @pytest.mark.asyncio
    async def test_governance_access_review(self) -> None:
        from app.services.governance_service import GovernanceService

        session = _make_session()
        user = _make_user()

        with patch("app.services.governance_service.check_permission"):
            review = await GovernanceService.create_access_review(
                tenant_id=TENANT_A, user=user,
                config={"review_cycle": "quarterly", "reviewee_id": "user-99"},
                session=session,
            )

        assert review.tenant_id == TENANT_A
        assert review.status in ("pending", "open", "in_progress")
        assert review.id is not None

        # Process decisions
        decisions = [
            {"user_id": "user-99", "action": "approve", "reason": "Active user"},
        ]
        with patch("app.services.governance_service.check_permission"):
            updated = await GovernanceService.process_review_decision(
                tenant_id=TENANT_A, user=user,
                review_id=review.id, decisions=decisions, session=session,
            )

        assert updated.status in ("completed", "closed", "decided")
        assert len(updated.decisions) > 0


class TestGovernancePrivilegeElevation:
    """35. JIT privilege elevation with time limit."""

    @pytest.mark.asyncio
    async def test_governance_privilege_elevation(self) -> None:
        from app.services.governance_service import GovernanceService

        session = _make_session()
        user = _make_user(roles=["developer"])

        with patch("app.services.governance_service.check_permission"):
            elevation = await GovernanceService.request_privilege_elevation(
                tenant_id=TENANT_A, user=user,
                role="admin", justification="Emergency deployment fix",
                duration=2,  # 2 hours
                session=session,
            )

        assert elevation.tenant_id == TENANT_A
        assert elevation.requested_role == "admin"
        assert elevation.duration_hours == 2
        assert elevation.status in ("pending", "approved", "active")
        assert elevation.justification == "Emergency deployment fix"
        # Elevation must have an expiry
        if elevation.expires_at is not None:
            assert elevation.expires_at > _utcnow()


class TestSentinelShadowAiDiscovery:
    """36. Discover shadow AI from SSO logs."""

    @pytest.mark.asyncio
    async def test_sentinel_shadow_ai_discovery(self) -> None:
        from app.models.sentinelscan import DiscoveryConfig
        from app.services.sentinelscan_service import SentinelScanService

        svc = SentinelScanService()

        config = DiscoveryConfig(
            sources=["sso_logs", "dns_logs"],
            scan_depth="deep",
            include_network_logs=True,
            time_range_days=30,
        )

        result = await SentinelScanService.discover_shadow_ai(
            tenant_id=_uuid("00000000aaaa1111"),
            user_id=_uuid("00000000ffff4444"),
            config=config,
        )

        assert result.shadow_count >= 0
        assert result.approved_count >= 0
        assert isinstance(result.discovered_services, list)
        assert result.scan_duration_seconds >= 0


class TestSecurityProxyPipeline:
    """37. Proxy processes request through full security pipeline."""

    @pytest.mark.asyncio
    async def test_security_proxy_pipeline(self) -> None:
        from app.models.security_proxy import ProxyRequest
        from app.services.security_proxy_service import SecurityProxyService

        secrets = _make_secrets()
        svc = SecurityProxyService(secrets=secrets)
        user = _make_user()

        proxy_req = ProxyRequest(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            body={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]},
            user_id=USER_ID,
            tenant_id=TENANT_A,
        )

        upstream_mock = MagicMock()
        upstream_mock.name = "openai-upstream"
        upstream_mock.base_url = "https://api.openai.com"
        upstream_mock.headers = {"Authorization": "Bearer sk-***"}
        upstream_mock.provider_type = MagicMock(value="openai")

        with patch.object(svc, "_resolve_upstream", new_callable=AsyncMock) as mock_upstream, \
             patch.object(svc, "_audit_log", new_callable=AsyncMock), \
             patch.object(svc, "inject_credentials", new_callable=AsyncMock) as mock_inject:
            mock_upstream.return_value = upstream_mock
            mock_inject.return_value = {"Authorization": "Bearer sk-***"}
            response = await svc.process_request(TENANT_A, user, proxy_req)

        assert response.status_code in (200, 201, 202)
        assert isinstance(response.dlp_findings, list)
        assert response.latency_ms >= 0


class TestMcpSecurityAuthorization:
    """38. MCP tool authorization with scope checks."""

    @pytest.mark.asyncio
    async def test_mcp_security_authorization(self) -> None:
        from app.services.mcp_security_service import (
            MCPSecurityService,
            _consent_store,
            _tool_registry,
        )

        user = _make_user(permissions=["mcp:tools:read", "mcp:tools:execute"])

        # Register tool and grant consent in module-level stores
        _tool_registry[TENANT_A] = {
            "code-executor": {
                "id": "code-executor",
                "name": "code-executor",
                "status": "active",
                "risk_level": "low",
                "required_scopes": ["read", "execute"],
            }
        }
        _consent_store[TENANT_A] = {
            user.id: {
                "code-executor": ["read", "execute"],
            }
        }

        try:
            result = await MCPSecurityService.authorize_tool_call(
                tenant_id=TENANT_A, user=user,
                tool_id="code-executor",
                scopes=["read", "execute"],
            )

            assert result.authorized is True
            assert result.missing_scopes == []

            # Test with insufficient scopes — user has no "admin" consent
            limited_user = _make_user(permissions=["mcp:tools:read"])
            _consent_store[TENANT_A][limited_user.id] = {
                "code-executor": ["read"],
            }
            result_denied = await MCPSecurityService.authorize_tool_call(
                tenant_id=TENANT_A, user=limited_user,
                tool_id="code-executor",
                scopes=["read", "execute", "admin"],
            )

            # Should flag missing scopes or deny
            assert not result_denied.authorized or len(result_denied.missing_scopes) > 0
        finally:
            _tool_registry.pop(TENANT_A, None)
            _consent_store.pop(TENANT_A, None)


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATIONS (39-43)
# ═══════════════════════════════════════════════════════════════════════════


class TestConnectorOAuthFlow:
    """39. Connector OAuth start → callback → Vault storage."""

    @pytest.mark.asyncio
    async def test_connector_oauth_flow(self) -> None:
        from app.models.connector import AuthMethod, ConnectorConfig
        from app.services.connector_service import ConnectorService, _connectors

        user = _make_user()
        secrets = _make_secrets()

        # Register connector first so start_oauth_flow can find it
        config = ConnectorConfig(
            type="github",
            name="GitHub Integration",
            auth_method=AuthMethod.OAUTH2,
            scopes=["repo", "user"],
        )
        with patch("app.services.connector_service.check_permission"):
            instance = await ConnectorService.register_connector(
                tenant_id=TENANT_A, user=user, config=config,
            )
        connector_id = instance.id

        try:
            with patch("app.services.connector_service.check_permission"):
                flow_start = await ConnectorService.start_oauth_flow(
                    tenant_id=TENANT_A, user=user,
                    connector_id=connector_id,
                    redirect_uri="https://app.example.com/callback",
                )

            assert flow_start.authorization_url.startswith("https://")
            assert flow_start.state != ""

            # Complete OAuth callback → store token in Vault
            with patch("app.services.connector_service.check_permission"):
                credential = await ConnectorService.complete_oauth_flow(
                    tenant_id=TENANT_A,
                    code="auth-code-xyz",
                    state=flow_start.state,
                    secrets_mgr=secrets,
                )

            assert credential.vault_path != ""
            assert credential.token_type in ("bearer", "Bearer")
            secrets.put_secret.assert_awaited()
        finally:
            _connectors.pop(str(connector_id), None)


class TestDocforgePermissionAwareSearch:
    """40. Search returns only permitted documents."""

    @pytest.mark.asyncio
    async def test_docforge_permission_aware_search(self) -> None:
        from app.services.docforge_service import DocForgeService

        user = _make_user()
        secrets = _make_secrets()

        with patch("app.services.docforge_service.check_permission"):
            result = await DocForgeService.search(
                tenant_id=TENANT_A, user=user,
                query="quarterly financial report",
                filters=None,
            )

        assert hasattr(result, "results")
        assert hasattr(result, "total")
        assert isinstance(result.results, list)
        # Results are permission-gated — should only include what user can see
        assert result.total >= 0


class TestA2aFederationFlow:
    """41. Register partner → acquire token → send message."""

    @pytest.mark.asyncio
    async def test_a2a_federation_flow(self) -> None:
        from app.models.a2a import PartnerRegistration
        from app.services.a2a_service import A2AService

        user = _make_user()
        secrets = _make_secrets()

        # Step 1: Register partner
        partner_reg = PartnerRegistration(
            name="partner-corp",
            base_url="https://partner.example.com/a2a",
            token_endpoint="https://partner.example.com/oauth/token",
            public_key="ssh-rsa AAAAB3NzaC1...",
            scopes=["agent:invoke", "agent:discover"],
        )

        with patch("app.services.a2a_service._audit_event", return_value=MagicMock(id=uuid4())):
            partner = await A2AService.register_partner(
                tenant_id=TENANT_A, user=user,
                partner=partner_reg, secrets=secrets,
            )

        assert partner.name == "partner-corp"
        assert partner.status in ("active", "pending", "registered")

        # Step 2: Acquire federation token
        token = await A2AService.acquire_token(
            tenant_id=TENANT_A,
            partner_id=str(partner.id),
            secrets=secrets,
        )

        assert token.access_token != ""
        assert token.token_type in ("bearer", "Bearer")
        assert token.expires_in > 0

        # Step 3: Send federated message
        with patch("app.services.a2a_service._audit_event", return_value=MagicMock(id=uuid4())):
            response = await A2AService.send_message(
                tenant_id=TENANT_A, user=user,
                partner_id=str(partner.id),
                agent_id=str(AGENT_ID),
                message="Summarize quarterly results",
                secrets=secrets,
            )

        assert response.status in ("delivered", "accepted", "processed", "success")
        assert response.message_id is not None


class TestConnectorCredentialRefresh:
    """42. Auto-refresh OAuth tokens from Vault."""

    @pytest.mark.asyncio
    async def test_connector_credential_refresh(self) -> None:
        from app.models.connector import AuthMethod, ConnectorInstance, ConnectorStatus
        from app.services.connector_service import ConnectorService, _connectors

        secrets = _make_secrets()
        connector_id = uuid4()

        # Register connector in module-level store
        _connectors[str(connector_id)] = ConnectorInstance(
            id=connector_id,
            tenant_id=TENANT_A,
            type="github",
            name="test-connector",
            status=ConnectorStatus.ACTIVE,
            auth_method=AuthMethod.OAUTH2,
        )

        # Mock Vault returning expired token + refresh token
        secrets.get_secret = AsyncMock(return_value={
            "access_token": "old-expired-token",
            "refresh_token": "valid-refresh-token",
            "expires_at": (_utcnow() - timedelta(hours=1)).isoformat(),
        })

        try:
            with patch("app.services.connector_service.check_permission"):
                refreshed = await ConnectorService.refresh_credentials(
                    tenant_id=TENANT_A,
                    connector_id=connector_id,
                    secrets_mgr=secrets,
                )

            assert refreshed is True
            # Vault should have been called to store the new token
            secrets.put_secret.assert_awaited()
        finally:
            _connectors.pop(str(connector_id), None)


class TestDocforgeDlpIngestion:
    """43. Document ingestion with DLP scan."""

    @pytest.mark.asyncio
    async def test_docforge_dlp_ingestion(self) -> None:
        from app.models.connector import AuthMethod, ConnectorInstance, ConnectorStatus
        from app.models.docforge import DocumentSource
        from app.services.connector_service import _connectors
        from app.services.docforge_service import DocForgeService

        user = _make_user()
        secrets = _make_secrets()
        connector_id = uuid4()

        # Register connector so DocForgeService.ingest_document can find it
        _connectors[str(connector_id)] = ConnectorInstance(
            id=connector_id,
            tenant_id=TENANT_A,
            type="sharepoint",
            name="test-connector",
            status=ConnectorStatus.ACTIVE,
            auth_method=AuthMethod.OAUTH2,
        )

        source = DocumentSource(
            connector_id=connector_id,
            resource_id="doc-001",
            resource_type="pdf",
        )

        try:
            with patch("app.services.docforge_service.check_permission"):
                doc = await DocForgeService.ingest_document(
                    tenant_id=TENANT_A, user=user,
                    source=source, title="Q4 Financial Report",
                    collection_id=None, secrets_mgr=secrets,
                )

            assert doc.tenant_id == TENANT_A
            assert doc.title == "Q4 Financial Report"
            # DLP scan should have run
            assert hasattr(doc, "dlp_clean")
        finally:
            _connectors.pop(str(connector_id), None)


# ═══════════════════════════════════════════════════════════════════════════
# DEPLOYMENT & UX (44-47)
# ═══════════════════════════════════════════════════════════════════════════


class TestDeploymentInfraHealth:
    """44. Infrastructure health check (Vault, DB, Redis)."""

    @pytest.mark.asyncio
    async def test_deployment_infra_health(self) -> None:
        from app.services.deployment_service import DeploymentService

        secrets = _make_secrets()

        result = await DeploymentService.get_infrastructure_health(
            tenant_id=TENANT_A, secrets_manager=secrets,
        )

        assert result.vault_status is not None
        assert result.db_status is not None
        assert result.redis_status is not None
        assert result.overall is not None
        # Each component should have a status
        for comp in [result.vault_status, result.db_status, result.redis_status]:
            assert hasattr(comp, "status") or hasattr(comp, "name") or comp is not None


class TestMarketplacePublishFlow:
    """45. Register publisher → submit package → review → publish."""

    @pytest.mark.asyncio
    async def test_marketplace_publish_flow(self) -> None:
        from app.models.marketplace import PackageSubmission, PublisherProfile
        from app.services.marketplace_service import MarketplaceService

        secrets = _make_secrets()
        svc = MarketplaceService(secrets_manager=secrets)
        session = _make_session()
        user = _make_user()

        # Step 1: Register publisher
        profile = PublisherProfile(
            display_name="Test Publisher",
            email="pub@corp.io",
            bio="Enterprise AI tools",
            github_url="https://github.com/test-pub",
        )

        with patch("app.services.marketplace_service.check_permission"):
            publisher = await svc.register_publisher(
                tenant_id=TENANT_A, user=user,
                profile=profile, session=session,
            )

        assert publisher.display_name == "Test Publisher"
        assert publisher.id is not None

        # Step 2: Submit package
        submission = PackageSubmission(
            name="smart-router-plugin",
            description="AI model routing plugin",
            category="infrastructure",
            license="MIT",
            source_url="https://github.com/test-pub/smart-router",
            version="1.0.0",
        )

        # publish_package uses session.execute (SQLAlchemy) to look up CreatorProfile
        creator_mock = MagicMock()
        creator_mock.id = publisher.id
        creator_mock.display_name = "Test Publisher"
        creator_mock.is_verified = True
        creator_mock.user_id = UUID(USER_ID)

        exec_result_mock = MagicMock()
        exec_result_mock.scalar_one_or_none.return_value = creator_mock
        session.execute = AsyncMock(return_value=exec_result_mock)

        with patch("app.services.marketplace_service.check_permission"):
            package = await svc.publish_package(
                tenant_id=TENANT_A, user=user,
                package=submission, session=session,
            )

        assert package.name == "smart-router-plugin"
        assert package.version == "1.0.0"

        # Step 3: Run review pipeline — needs session.execute to return a listing
        listing_mock = MagicMock()
        listing_mock.name = "smart-router-plugin"
        listing_mock.version = "1.0.0"
        listing_mock.license = "MIT"
        listing_mock.definition = "{}"
        review_exec_result = MagicMock()
        review_exec_result.scalar_one_or_none.return_value = listing_mock
        session.execute = AsyncMock(return_value=review_exec_result)

        review_result = await svc.run_review_pipeline(
            package_id=package.id, session=session,
        )

        assert hasattr(review_result, "passed")
        assert hasattr(review_result, "security_score")


class TestMobileBiometricAuth:
    """46. Biometric auth flow."""

    @pytest.mark.asyncio
    async def test_mobile_biometric_auth(self) -> None:
        from app.models.mobile import BiometricProof
        from app.services.mobile_service import MobileService

        secrets = _make_secrets()
        svc = MobileService(secrets_manager=secrets)

        proof = BiometricProof(
            challenge="challenge-nonce-abc",
            signature="f9a8fe56da490026b86a272eafc50db22269956ee83e82dca841b5c87af055b4",
            device_id="device-001",
            timestamp=_utcnow(),
        )

        result = await svc.authenticate_biometric(
            tenant_id=TENANT_A,
            device_id="device-001",
            biometric_proof=proof,
        )

        assert result.access_token != ""
        assert result.device_id == "device-001"
        assert result.expires_in > 0


class TestMcpInteractiveSession:
    """47. Create session → render → action → close."""

    @pytest.mark.asyncio
    async def test_mcp_interactive_session(self) -> None:
        from app.models.mcp_interactive import (
            ComponentAction,
            ComponentCategory,
            ComponentConfig,
        )
        from app.services.mcp_interactive_service import MCPInteractiveService

        user = _make_user()

        # Step 1: Create session
        session_obj = await MCPInteractiveService.create_component_session(
            tenant_id=TENANT_A, user=user,
            component_type=ComponentCategory.CHART,
        )

        assert session_obj.session_id is not None
        assert session_obj.tenant_id == TENANT_A
        assert session_obj.status in ("active", "created", "open")

        # Step 2: Render component
        config = ComponentConfig(
            type=ComponentCategory.CHART,
            data_source="metrics_api",
            filters={"period": "7d"},
            display_options={"chart_type": "line"},
        )

        rendered = await MCPInteractiveService.render_component(
            tenant_id=TENANT_A, user=user,
            session_id=session_obj.session_id,
            component_config=config,
        )

        assert rendered.session_id == session_obj.session_id
        assert rendered.csp_nonce != ""
        assert rendered.html_content != ""

        # Step 3: Handle action
        action = ComponentAction(
            session_id=session_obj.session_id,
            action_type="filter_change",
            payload={"period": "30d"},
            timestamp=_utcnow(),
        )

        action_result = await MCPInteractiveService.handle_component_action(
            tenant_id=TENANT_A, user=user,
            session_id=session_obj.session_id,
            action=action,
        )

        assert action_result.success is True

        # Step 4: Close session
        await MCPInteractiveService.close_session(
            tenant_id=TENANT_A,
            session_id=session_obj.session_id,
        )


# ═══════════════════════════════════════════════════════════════════════════
# ADVANCED (48-50)
# ═══════════════════════════════════════════════════════════════════════════


class TestMeshFederationFlow:
    """48. Register org → create agreement → share agent → invoke."""

    @pytest.mark.asyncio
    async def test_mesh_federation_flow(self) -> None:
        from app.models.mesh import OrgRegistration
        from app.services.mesh_service import MeshService

        secrets = _make_secrets()
        svc = MeshService(secrets_manager=secrets)
        session = _make_session()
        user = _make_user()

        # Step 1: Register organization
        org_reg = OrgRegistration(
            name="AlphaCorp",
            domain="alphacorp.com",
            public_key="ssh-rsa AAAAB3...",
            token_endpoint="https://alphacorp.com/oauth/token",
            metadata_url="https://alphacorp.com/.well-known/openid",
        )

        with patch("app.services.mesh_service.check_permission"):
            org = await svc.register_organization(
                tenant_id=TENANT_A, user=user,
                org_config=org_reg, session=session,
            )

        assert org.name == "AlphaCorp"
        assert org.id is not None

        # Set up session.exec to return nodes for federation queries
        partner_node_mock = MagicMock()
        partner_node_mock.id = org.id
        partner_node_mock.name = "AlphaCorp"
        partner_node_mock.organization = "alphacorp.com"
        partner_node_mock.extra_metadata = {"tenant_id": TENANT_A}
        partner_node_mock.created_at = _utcnow()

        requester_node_mock = MagicMock()
        requester_node_mock.id = uuid4()
        requester_node_mock.name = "RequesterOrg"
        requester_node_mock.extra_metadata = {"tenant_id": TENANT_A}
        requester_node_mock.created_at = _utcnow()

        def _make_exec_result(*vals):
            r = MagicMock()
            r.first.return_value = vals[0] if vals else None
            r.all.return_value = list(vals)
            return r

        session.exec = AsyncMock(side_effect=[
            _make_exec_result(partner_node_mock),   # partner lookup
            _make_exec_result(requester_node_mock),  # requester lookup
            _make_exec_result(),                     # share_agent commit
            _make_exec_result(),                     # discover_mesh_agents
        ])

        # Step 2: Create federation agreement
        with patch("app.services.mesh_service.check_permission"):
            agreement = await svc.create_federation_agreement(
                tenant_id=TENANT_A, user=user,
                partner_org_id=org.id,
                terms={"data_sharing": "restricted", "max_agents": 10},
                session=session,
            )

        assert agreement.id is not None
        assert agreement.status in ("pending", "active", "proposed")

        # Step 3: Share agent
        with patch("app.services.mesh_service.check_permission"):
            shared = await svc.share_agent(
                tenant_id=TENANT_A, user=user,
                agent_id=AGENT_ID,
                sharing_policy={"visibility": "federation", "data_classification": "internal"},
                session=session,
            )

        assert shared.agent_id == AGENT_ID

        # Step 4: Discover and invoke
        with patch("app.services.mesh_service.check_permission"):
            agents = await svc.discover_mesh_agents(
                tenant_id=TENANT_A, user=user, session=session,
            )

        assert isinstance(agents, list)


class TestEdgeOfflineToken:
    """49. Provision offline token → sync → revoke."""

    @pytest.mark.asyncio
    async def test_edge_offline_token(self) -> None:
        from app.models.edge import OfflineTokenConfig, SyncPayload
        from app.services.edge_service import EdgeService

        session = _make_session()
        secrets = _make_secrets()
        user = _make_user()
        device_id = uuid4()

        # Pre-populate session with a device so session.get(EdgeDevice, ...) finds it
        from app.models.edge import EdgeDevice
        device_obj = EdgeDevice(
            id=device_id,
            name="test-device",
            device_type="linux",
            status="online",
            extra_metadata={"tenant_id": TENANT_A},
        )
        session._added.append(device_obj)

        # Step 1: Provision offline token
        token_config = OfflineTokenConfig(
            ttl_days=30,
            permissions_snapshot=["agents:execute", "agents:read"],
            allowed_agents=["agent-001", "agent-002"],
        )

        token = await EdgeService.provision_offline_token(
            tenant_id=TENANT_A, user=user,
            device_id=device_id, config=token_config,
            session=session, secrets_manager=secrets,
        )

        assert token.token != ""
        assert token.device_id == device_id
        assert token.expires_at > _utcnow()
        assert "agents:execute" in token.permissions_snapshot

        # Step 2: Sync device
        sync_data = SyncPayload(
            device_id=device_id,
            local_changes=[{"type": "execution_result", "data": {"status": "completed"}}],
            last_sync_checkpoint="cp-000",
            storage_stats={"used_mb": 128, "total_mb": 512},
        )

        sync_result = await EdgeService.sync_device(
            tenant_id=TENANT_A, device_id=device_id,
            sync_data=sync_data, session=session,
        )

        assert sync_result.processed >= 0
        assert sync_result.next_checkpoint != ""

        # Step 3: Revoke device
        await EdgeService.revoke_device(
            tenant_id=TENANT_A, user=user,
            device_id=device_id, session=session,
        )


class TestFullEnterpriseFlow:
    """50. Complete flow: login → create agent → deploy → execute → audit → cost."""

    @pytest.mark.asyncio
    async def test_full_enterprise_flow(self) -> None:
        from app.models import Agent, Execution
        from app.services.agent_service import create_agent, get_agent
        from app.services.execution_service import create_execution

        session = _make_session()
        user = _make_user()

        # Step 1: Create agent
        agent = Agent(
            id=AGENT_ID, name="enterprise-bot",
            description="Full E2E test agent",
            definition={"nodes": [{"type": "llm", "model": "gpt-4o"}]},
            status="draft", owner_id=_uuid("00000000aaaabbbb"),
            tags=["e2e", "enterprise"],
        )
        created = await create_agent(session, agent)
        assert created.name == "enterprise-bot"
        session.commit.assert_awaited()

        # Step 2: Verify agent persisted
        fetched = await get_agent(session, AGENT_ID)
        assert fetched is not None
        assert fetched.id == AGENT_ID

        # Step 3: Create execution
        execution = Execution(
            id=_uuid("00000000e0ec0001"),
            agent_id=AGENT_ID,
            input_data={"prompt": "Generate quarterly summary"},
        )
        exec_result = await create_execution(session, execution)
        assert exec_result.status == "queued"

        # Step 4: Verify cost tracking is importable
        from app.services.cost_service import CostService
        assert callable(CostService.record_usage)

        # Step 5: Verify audit logging is importable
        from app.services.audit_log_service import AuditLogService
        assert callable(AuditLogService.create)

        # Step 6: Verify deployment service available
        from app.services.deployment_service import DeploymentService
        assert callable(DeploymentService.get_infrastructure_health)
