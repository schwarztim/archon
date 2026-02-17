"""Cross-agent end-to-end integration tests.

Validates multi-service flows that span agent boundaries:
  1. Create Agent → Execute → View in Audit → See cost
  2. Configure Provider → Create Agent with model → Execute
  3. Create Template → Instantiate → Verify agent created
  4. Create DLP Policy → Execute Agent → Verify DLP scan occurred
  5. Lifecycle pipeline: deploy → promote → rollback

All external dependencies (DB, Vault, Keycloak) are mocked.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models import Agent, AuditLog, Execution, Template
from app.models.cost import TokenLedger, UsageEvent
from app.models.dlp import (
    DLPPolicy,
    DLPScanResultSchema,
    RiskLevel,
    ScanAction,
    ScanDirection,
)
from app.models.lifecycle import (
    Deployment,
    DeploymentStrategy,
    DeploymentStrategyType,
)
from app.services.agent_service import AgentService
from app.services.audit_log_service import AuditLogService
from app.services.cost_service import CostService
from app.services.dlp_service import DLPService
from app.services.execution_service import ExecutionService
from app.services.lifecycle_service import LifecycleService
from app.services.template_service import TemplateService

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid4())
TENANT_UUID = UUID(TENANT_ID)
USER_ID = str(uuid4())
AGENT_ID = uuid4()


def _user(
    *,
    roles: list[str] | None = None,
    tenant_id: str = TENANT_ID,
) -> AuthenticatedUser:
    """Return an authenticated user with sensible defaults."""
    return AuthenticatedUser(
        id=USER_ID,
        email="test@archon.local",
        tenant_id=tenant_id,
        roles=roles or ["admin"],
        permissions=[],
        mfa_verified=True,
        session_id="sess-test",
    )


def _lifecycle_user(
    *,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    """Return a user dict expected by LifecycleService."""
    return {
        "id": USER_ID,
        "email": "test@archon.local",
        "roles": roles or ["admin"],
    }


def _mock_session() -> AsyncMock:
    """Return a minimal async DB session mock that tracks added objects."""
    session = AsyncMock()
    session._added: list[Any] = []

    def _add(obj: Any) -> None:
        session._added.append(obj)

    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock(return_value=None)

    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_result.all.return_value = []
    mock_result.one.return_value = 0
    session.exec = AsyncMock(return_value=mock_result)

    return session


def _mock_vault() -> MagicMock:
    """Return a mock VaultSecretsManager."""
    from app.secrets.manager import VaultSecretsManager

    m = MagicMock(spec=VaultSecretsManager)
    m.get_secret = AsyncMock(return_value={"api_key": "sk-mock"})
    m.put_secret = AsyncMock()
    m.delete_secret = AsyncMock()
    m.list_secrets = AsyncMock(return_value=[])
    m.health = AsyncMock(return_value={"status": "healthy"})
    return m


# ═══════════════════════════════════════════════════════════════════
# Flow 1: Create Agent → Execute → Audit → Cost
# ═══════════════════════════════════════════════════════════════════


class TestAgentExecuteAuditCost:
    """End-to-end: agent creation through cost attribution."""

    @pytest.mark.asyncio
    async def test_create_agent(self) -> None:
        """Create an agent and verify it is persisted with audit trail."""
        session = _mock_session()
        user = _user()

        agent = Agent(
            id=AGENT_ID,
            name="E2E Test Agent",
            description="Integration test agent",
            definition={"type": "langchain", "model": "gpt-4o"},
            status="draft",
            owner_id=UUID(USER_ID),
        )

        created = await AgentService.create(
            session, agent, tenant_id=TENANT_UUID, user=user,
        )

        assert created is agent
        # Agent + AuditLog should both have been added
        types_added = {type(o).__name__ for o in session._added}
        assert "Agent" in types_added
        assert "AuditLog" in types_added
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_execute_agent_records_audit(self) -> None:
        """Starting an execution produces an audit entry and Execution record."""
        session = _mock_session()
        user = _user()

        # Mock that the agent exists in tenant scope
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = AGENT_ID
        mock_agent.name = "E2E Test Agent"
        agent_result = MagicMock()
        agent_result.first.return_value = mock_agent
        session.exec = AsyncMock(return_value=agent_result)

        vault = _mock_vault()
        with patch(
            "app.secrets.manager.get_secrets_manager",
            new_callable=AsyncMock,
            return_value=vault,
        ):
            execution = await ExecutionService.start_execution(
                session,
                AGENT_ID,
                {"prompt": "Hello"},
                tenant_id=TENANT_UUID,
                user=user,
            )

        assert execution.agent_id == AGENT_ID
        assert execution.status == "running"

        # Verify audit entry was created
        audit_entries = [
            o for o in session._added if isinstance(o, AuditLog)
        ]
        assert len(audit_entries) >= 1
        assert audit_entries[0].action == "execution.started"

    @pytest.mark.asyncio
    async def test_audit_log_service_create(self) -> None:
        """AuditLogService.create persists an immutable audit entry."""
        session = _mock_session()

        entry = await AuditLogService.create(
            session,
            actor_id=UUID(USER_ID),
            action="agent.created",
            resource_type="agent",
            resource_id=AGENT_ID,
            details={"name": "E2E Test Agent"},
        )

        assert entry is not None
        audit_entries = [
            o for o in session._added if isinstance(o, AuditLog)
        ]
        assert len(audit_entries) == 1
        assert audit_entries[0].action == "agent.created"

    @pytest.mark.asyncio
    async def test_cost_record_usage(self) -> None:
        """CostService.record_usage creates a ledger entry with attribution."""
        session = _mock_session()

        # Mock session.exec to return a result for _calculate_token_cost
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_result.all.return_value = []
        mock_result.one.return_value = 0
        session.exec = AsyncMock(return_value=mock_result)

        event = UsageEvent(
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            agent_id=AGENT_ID,
            execution_id=uuid4(),
            user_id=UUID(USER_ID),
        )

        entry = await CostService.record_usage(session, TENANT_ID, event)

        assert entry is not None
        ledger_entries = [
            o for o in session._added if isinstance(o, TokenLedger)
        ]
        assert len(ledger_entries) >= 1
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_full_flow_agent_to_cost(self) -> None:
        """Verify the complete create → execute → audit → cost flow."""
        session = _mock_session()
        user = _user()

        # Step 1: Create agent
        agent = Agent(
            id=AGENT_ID,
            name="Flow Test Agent",
            definition={"type": "react"},
            status="draft",
            owner_id=UUID(USER_ID),
        )
        await AgentService.create(session, agent, tenant_id=TENANT_UUID, user=user)

        # Step 2: Execute agent
        agent_result = MagicMock()
        agent_result.first.return_value = agent
        session.exec = AsyncMock(return_value=agent_result)

        vault = _mock_vault()
        with patch(
            "app.secrets.manager.get_secrets_manager",
            new_callable=AsyncMock,
            return_value=vault,
        ):
            execution = await ExecutionService.start_execution(
                session, AGENT_ID, {"input": "test"},
                tenant_id=TENANT_UUID, user=user,
            )

        # Step 3: Verify audit trail exists
        audit_entries = [o for o in session._added if isinstance(o, AuditLog)]
        actions = {e.action for e in audit_entries}
        assert "agent.created" in actions
        assert "execution.started" in actions

        # Step 4: Record cost
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_result.all.return_value = []
        mock_result.one.return_value = 0
        session.exec = AsyncMock(return_value=mock_result)

        event = UsageEvent(
            provider="openai",
            model="gpt-4o",
            input_tokens=500,
            output_tokens=200,
            agent_id=AGENT_ID,
            execution_id=execution.id,
            user_id=UUID(USER_ID),
        )
        cost_entry = await CostService.record_usage(session, TENANT_ID, event)
        assert cost_entry is not None


# ═══════════════════════════════════════════════════════════════════
# Flow 2: Configure Provider → Create Agent with model → Execute
# ═══════════════════════════════════════════════════════════════════


class TestProviderAgentExecution:
    """End-to-end: provider registration → agent creation → execution."""

    @pytest.mark.asyncio
    async def test_register_provider_then_create_agent(self) -> None:
        """Register a model provider, then create an agent using it."""
        from app.models.router import ModelRegistryEntry
        from app.services.router_service import ModelRouterService, ModelProvider

        session = _mock_session()
        user = _user()
        vault = _mock_vault()

        provider = ModelProvider(
            name="OpenAI Production",
            api_type="openai",
            model_ids=["gpt-4o", "gpt-4o-mini"],
            capabilities=["chat", "function_calling"],
            cost_per_1k_tokens=0.01,
            avg_latency_ms=200,
            data_classification_level="confidential",
            geo_residency="us",
            is_active=True,
        )

        registered = await ModelRouterService.register_provider(
            session, vault, TENANT_ID, user, provider,
        )

        assert registered.name == "OpenAI Production"
        assert registered.id is not None

        # Now create an agent that references this model
        agent = Agent(
            name="GPT-4o Agent",
            definition={"model": "gpt-4o", "provider": "openai"},
            llm_config={"model": "gpt-4o", "provider_id": str(registered.id)},
            status="draft",
            owner_id=UUID(USER_ID),
        )
        created = await AgentService.create(
            session, agent, tenant_id=TENANT_UUID, user=user,
        )
        assert created.llm_config["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_provider_agent_execute_flow(self) -> None:
        """Full flow: register provider → create agent → execute."""
        from app.services.router_service import ModelRouterService, ModelProvider

        session = _mock_session()
        user = _user()
        vault = _mock_vault()

        # Register provider
        provider = ModelProvider(
            name="Anthropic",
            api_type="anthropic",
            model_ids=["claude-3-5-sonnet"],
            capabilities=["chat"],
            cost_per_1k_tokens=0.003,
            avg_latency_ms=300,
            data_classification_level="internal",
            geo_residency="us",
            is_active=True,
        )
        await ModelRouterService.register_provider(
            session, vault, TENANT_ID, user, provider,
        )

        # Create agent
        agent = Agent(
            id=uuid4(),
            name="Claude Agent",
            definition={"model": "claude-3-5-sonnet"},
            status="draft",
            owner_id=UUID(USER_ID),
        )
        created = await AgentService.create(
            session, agent, tenant_id=TENANT_UUID, user=user,
        )

        # Execute
        agent_result = MagicMock()
        agent_result.first.return_value = created
        session.exec = AsyncMock(return_value=agent_result)

        with patch(
            "app.secrets.manager.get_secrets_manager",
            new_callable=AsyncMock,
            return_value=vault,
        ):
            execution = await ExecutionService.start_execution(
                session, created.id, {"prompt": "Summarize this"},
                tenant_id=TENANT_UUID, user=user,
            )

        assert execution.status == "running"
        assert execution.agent_id == created.id


# ═══════════════════════════════════════════════════════════════════
# Flow 3: Create Template → Instantiate → Verify agent created
# ═══════════════════════════════════════════════════════════════════


class TestTemplateInstantiation:
    """End-to-end: template lifecycle from creation to agent instantiation."""

    @pytest.mark.asyncio
    async def test_create_template(self) -> None:
        """Create a template and persist it."""
        session = _mock_session()

        template = Template(
            name="Customer Service Bot",
            description="Pre-built support agent template",
            category="customer-service",
            definition={
                "type": "langchain",
                "model": "gpt-4o",
                "tools": ["search", "ticket_create"],
                "_meta": {"difficulty": "beginner", "status": "published"},
            },
            tags=["support", "customer"],
            author_id=UUID(USER_ID),
        )

        created = await TemplateService.create(session, template)

        assert created is template
        assert created.name == "Customer Service Bot"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_instantiate_template_creates_agent(self) -> None:
        """Instantiating a template produces a new agent in draft status."""
        session = _mock_session()
        template_id = uuid4()

        template = Template(
            id=template_id,
            name="Data Analysis Bot",
            description="Analytical workflow template",
            category="data-analysis",
            definition={"type": "react", "tools": ["pandas", "matplotlib"]},
            tags=["analytics"],
            usage_count=5,
            author_id=UUID(USER_ID),
        )

        # Mock session.get to return the template
        session.get = AsyncMock(return_value=template)

        agent = await TemplateService.instantiate(
            session, template_id, UUID(USER_ID),
        )

        assert agent is not None
        assert agent.name == "Data Analysis Bot (from template)"
        assert agent.status == "draft"
        assert agent.owner_id == UUID(USER_ID)
        assert agent.definition == template.definition
        # Template usage_count should be incremented
        assert template.usage_count == 6

    @pytest.mark.asyncio
    async def test_instantiate_missing_template_returns_none(self) -> None:
        """Instantiating a non-existent template returns None."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await TemplateService.instantiate(
            session, uuid4(), UUID(USER_ID),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_template_to_agent_full_flow(self) -> None:
        """Create template → instantiate → verify agent has correct config."""
        session = _mock_session()

        # Step 1: Create template
        template = Template(
            id=uuid4(),
            name="DevOps Pipeline Bot",
            description="CI/CD automation agent",
            category="devops",
            definition={
                "type": "langchain",
                "model": "gpt-4o",
                "tools": ["github", "jenkins", "k8s"],
            },
            tags=["devops", "automation"],
            author_id=UUID(USER_ID),
            usage_count=0,
        )
        await TemplateService.create(session, template)

        # Step 2: Instantiate to agent
        session.get = AsyncMock(return_value=template)
        agent = await TemplateService.instantiate(
            session, template.id, UUID(USER_ID),
        )

        # Step 3: Verify agent matches template
        assert agent is not None
        assert "DevOps Pipeline Bot" in agent.name
        assert agent.definition["tools"] == ["github", "jenkins", "k8s"]
        assert agent.tags == ["devops", "automation"]
        assert template.usage_count == 1


# ═══════════════════════════════════════════════════════════════════
# Flow 4: Create DLP Policy → Execute Agent → Verify DLP scan
# ═══════════════════════════════════════════════════════════════════


class TestDLPScanIntegration:
    """End-to-end: DLP policy enforcement during agent execution."""

    def test_dlp_scan_detects_secrets(self) -> None:
        """DLP scan detects AWS keys in agent output."""
        content = "Here is the key: AKIAIOSFODNN7EXAMPLE and password secret123"
        result = DLPService.scan_content(
            TENANT_ID, content, ScanDirection.OUTPUT,
        )

        assert isinstance(result, DLPScanResultSchema)
        assert result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

        from app.models.dlp import SecretFinding as SF
        secret_findings = [f for f in result.findings if isinstance(f, SF)]
        assert len(secret_findings) >= 1

        # Verify at least one AWS key detected
        pattern_names = [f.pattern_name for f in secret_findings]
        assert any("aws" in name for name in pattern_names)

    def test_dlp_scan_detects_pii(self) -> None:
        """DLP scan detects PII (email, SSN) in content."""
        content = "Contact: john@example.com, SSN: 123-45-6789"
        result = DLPService.scan_content(
            TENANT_ID, content, ScanDirection.INPUT,
        )

        assert isinstance(result, DLPScanResultSchema)

        from app.models.dlp import PIIFinding as PF
        pii_findings = [f for f in result.findings if isinstance(f, PF)]
        assert len(pii_findings) >= 1

        pii_types = [f.pii_type for f in pii_findings]
        assert "email" in pii_types or any("mail" in t.lower() for t in pii_types)

    def test_dlp_scan_clean_content(self) -> None:
        """DLP scan passes clean content with low/no risk."""
        content = "The weather today is sunny with a high of 75 degrees."
        result = DLPService.scan_content(
            TENANT_ID, content, ScanDirection.INPUT,
        )

        assert isinstance(result, DLPScanResultSchema)
        assert result.risk_level in (RiskLevel.LOW,)
        assert result.action in (ScanAction.ALLOW, ScanAction.REDACT)

    @pytest.mark.asyncio
    async def test_dlp_policy_with_execution(self) -> None:
        """Full flow: DLP scan on agent input before execution starts."""
        session = _mock_session()
        user = _user()

        # Step 1: Scan the input with DLP
        agent_input = {"prompt": "Process this: AKIAIOSFODNN7EXAMPLE"}
        dlp_result = DLPService.scan_content(
            TENANT_ID,
            str(agent_input),
            ScanDirection.INPUT,
        )

        # Step 2: If DLP blocks, don't execute
        if dlp_result.action == ScanAction.BLOCK:
            assert dlp_result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            return  # Execution blocked by DLP — expected

        # Step 3: If DLP allows, proceed with execution
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = AGENT_ID
        agent_result_mock = MagicMock()
        agent_result_mock.first.return_value = mock_agent
        session.exec = AsyncMock(return_value=agent_result_mock)

        vault = _mock_vault()
        with patch(
            "app.secrets.manager.get_secrets_manager",
            new_callable=AsyncMock,
            return_value=vault,
        ):
            execution = await ExecutionService.start_execution(
                session, AGENT_ID, agent_input,
                tenant_id=TENANT_UUID, user=user,
            )

        assert execution.status == "running"

        # Step 4: DLP scan on the output
        output_content = "Here is the result without any secrets."
        output_scan = DLPService.scan_content(
            TENANT_ID, output_content, ScanDirection.OUTPUT,
        )
        assert output_scan.action != ScanAction.BLOCK

    def test_dlp_policy_model_fields(self) -> None:
        """Verify DLP policy model has expected fields."""
        policy = DLPPolicy(
            tenant_id=TENANT_ID,
            name="Block AWS Secrets",
            description="Prevent AWS credentials from leaking",
            is_active=True,
            detector_types=["secrets", "pii"],
            action="block",
            sensitivity="high",
        )

        assert policy.name == "Block AWS Secrets"
        assert policy.is_active is True
        assert "secrets" in policy.detector_types


# ═══════════════════════════════════════════════════════════════════
# Flow 5: Lifecycle pipeline — deploy → promote → rollback
# ═══════════════════════════════════════════════════════════════════


class TestLifecyclePipeline:
    """End-to-end: agent lifecycle state transitions and deployment pipeline."""

    @pytest.mark.asyncio
    async def test_lifecycle_state_transitions(self) -> None:
        """Walk an agent through draft → review → approved → published."""
        svc = LifecycleService()
        user = _lifecycle_user()
        agent_id = uuid4()

        # Draft → Review
        t1 = await svc.transition(TENANT_ID, user, agent_id, "review")
        assert t1.from_state == "draft"
        assert t1.to_state == "review"

        # Review → Approved
        t2 = await svc.transition(TENANT_ID, user, agent_id, "approved")
        assert t2.from_state == "review"
        assert t2.to_state == "approved"

        # Approved → Published
        t3 = await svc.transition(TENANT_ID, user, agent_id, "published")
        assert t3.from_state == "approved"
        assert t3.to_state == "published"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self) -> None:
        """Invalid lifecycle transitions raise ValueError."""
        svc = LifecycleService()
        user = _lifecycle_user()
        agent_id = uuid4()

        with pytest.raises(ValueError, match="Invalid transition"):
            await svc.transition(TENANT_ID, user, agent_id, "published")

    @pytest.mark.asyncio
    async def test_deploy_promote_rollback(self) -> None:
        """Full deployment pipeline: deploy → promote → rollback."""
        svc = LifecycleService()
        user = _lifecycle_user()
        agent_id = uuid4()

        strategy = DeploymentStrategy(
            type=DeploymentStrategyType.ROLLING,
            config={"batch_size": 2},
        )

        # Deploy to dev
        deployment = await svc.deploy(
            TENANT_ID, user, agent_id, strategy, "dev",
        )
        assert deployment.environment == "dev"
        assert deployment.status == "deploying"
        deployment_id = deployment.id

        # Promote dev → staging
        promoted = await svc.promote_to_next_stage(
            TENANT_ID, user, deployment_id,
        )
        assert promoted.environment == "staging"

        # Promote staging → canary
        promoted2 = await svc.promote_to_next_stage(
            TENANT_ID, user, deployment_id,
        )
        assert promoted2.environment == "canary"

        # Rollback
        rolled_back = await svc.rollback_deployment(
            TENANT_ID, user, deployment_id, reason="integration test rollback",
        )
        assert rolled_back.status == "rolled_back"

    @pytest.mark.asyncio
    async def test_rbac_enforcement_on_lifecycle(self) -> None:
        """Non-admin users cannot perform admin-only transitions."""
        svc = LifecycleService()
        viewer_user = _lifecycle_user(roles=["viewer"])
        agent_id = uuid4()

        with pytest.raises(PermissionError, match="Insufficient permissions"):
            await svc.transition(TENANT_ID, viewer_user, agent_id, "review")

    @pytest.mark.asyncio
    async def test_deploy_canary_strategy(self) -> None:
        """Canary deployment creates deployment with correct strategy."""
        svc = LifecycleService()
        user = _lifecycle_user()
        agent_id = uuid4()

        strategy = DeploymentStrategy(
            type=DeploymentStrategyType.CANARY,
            config={"canary_percentage": 10, "step_interval": 300},
        )

        deployment = await svc.deploy(
            TENANT_ID, user, agent_id, strategy, "staging",
        )
        assert deployment.strategy.type == DeploymentStrategyType.CANARY
        assert deployment.environment == "staging"

    @pytest.mark.asyncio
    async def test_shadow_deployment_status(self) -> None:
        """Shadow deployments start with 'shadow' status."""
        svc = LifecycleService()
        user = _lifecycle_user()
        agent_id = uuid4()

        strategy = DeploymentStrategy(
            type=DeploymentStrategyType.SHADOW,
            config={},
        )

        deployment = await svc.deploy(
            TENANT_ID, user, agent_id, strategy, "production",
        )
        assert deployment.status == "shadow"
