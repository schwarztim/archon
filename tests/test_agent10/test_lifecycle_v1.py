"""Tests for Lifecycle v1 endpoints — pipeline, promote/demote, environments, diff, history, gates, health."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.models.lifecycle import (
    ApprovalGate,
    ConfigDiff,
    Deployment,
    DeploymentHistoryEntry,
    DeploymentStrategy,
    DeploymentStrategyType,
    EnvironmentInfo,
    HealthMetrics,
    PipelineStageInfo,
)
from app.services.lifecycle_service import (
    LifecycleService,
    _agent_states,
    _approval_gates,
    _deployments,
    _environments,
    _health_metrics,
    _metrics_store,
    _scheduled_jobs,
)


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-lifecycle-v1-test"


def _admin_user(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id": str(uuid4()),
        "email": "admin@example.com",
        "roles": ["admin"],
    }
    defaults.update(overrides)
    return defaults


def _operator_user(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id": str(uuid4()),
        "email": "operator@example.com",
        "roles": ["operator"],
    }
    defaults.update(overrides)
    return defaults


def _viewer_user(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id": str(uuid4()),
        "email": "viewer@example.com",
        "roles": ["viewer"],
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def _clear_stores() -> None:
    """Reset in-memory stores between tests."""
    _agent_states.clear()
    _scheduled_jobs.clear()
    _metrics_store.clear()
    _deployments.clear()
    _approval_gates.clear()
    _environments.clear()
    _health_metrics.clear()


async def _create_deployment(
    tenant_id: str = TENANT_ID,
    environment: str = "dev",
    strategy_type: DeploymentStrategyType = DeploymentStrategyType.ROLLING,
) -> Deployment:
    """Helper to create a deployment for testing."""
    strategy = DeploymentStrategy(type=strategy_type, canary_percentage=10, rollback_threshold=0.05)
    return await LifecycleService.deploy(
        tenant_id=tenant_id,
        user=_admin_user(),
        agent_id=uuid4(),
        strategy=strategy,
        target_env=environment,
    )


# ── Pipeline ────────────────────────────────────────────────────────


class TestPipeline:
    """Tests for pipeline view."""

    @pytest.mark.asyncio
    async def test_get_pipeline_returns_four_stages(self) -> None:
        stages = await LifecycleService.get_pipeline(TENANT_ID)
        assert isinstance(stages, list)
        assert len(stages) == 4
        assert all(isinstance(s, PipelineStageInfo) for s in stages)

    @pytest.mark.asyncio
    async def test_pipeline_stage_names(self) -> None:
        stages = await LifecycleService.get_pipeline(TENANT_ID)
        names = [s.stage for s in stages]
        assert names == ["dev", "staging", "canary", "production"]

    @pytest.mark.asyncio
    async def test_pipeline_includes_deployments(self) -> None:
        await _create_deployment(environment="dev")
        stages = await LifecycleService.get_pipeline(TENANT_ID)
        dev_stage = next(s for s in stages if s.stage == "dev")
        assert len(dev_stage.deployments) == 1

    @pytest.mark.asyncio
    async def test_pipeline_includes_approval_gates(self) -> None:
        await LifecycleService.configure_gates(
            TENANT_ID,
            _admin_user(),
            [{"from_stage": "dev", "to_stage": "staging", "required_approvers": 2}],
        )
        stages = await LifecycleService.get_pipeline(TENANT_ID)
        dev_stage = next(s for s in stages if s.stage == "dev")
        assert dev_stage.approval_gate is not None
        assert dev_stage.approval_gate.required_approvers == 2

    @pytest.mark.asyncio
    async def test_pipeline_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await LifecycleService.get_pipeline("")


# ── Promote / Demote ────────────────────────────────────────────────


class TestPromoteDemote:
    """Tests for promote and demote operations."""

    @pytest.mark.asyncio
    async def test_promote_dev_to_staging(self) -> None:
        dep = await _create_deployment(environment="dev")
        result = await LifecycleService.promote_to_next_stage(
            TENANT_ID, _admin_user(), dep.id,
        )
        assert result.environment == "staging"

    @pytest.mark.asyncio
    async def test_promote_staging_to_canary(self) -> None:
        dep = await _create_deployment(environment="staging")
        result = await LifecycleService.promote_to_next_stage(
            TENANT_ID, _admin_user(), dep.id,
        )
        assert result.environment == "canary"

    @pytest.mark.asyncio
    async def test_promote_canary_to_production(self) -> None:
        dep = await _create_deployment(environment="canary")
        result = await LifecycleService.promote_to_next_stage(
            TENANT_ID, _admin_user(), dep.id,
        )
        assert result.environment == "production"

    @pytest.mark.asyncio
    async def test_promote_production_raises(self) -> None:
        dep = await _create_deployment(environment="production")
        with pytest.raises(ValueError, match="Cannot promote"):
            await LifecycleService.promote_to_next_stage(
                TENANT_ID, _admin_user(), dep.id,
            )

    @pytest.mark.asyncio
    async def test_promote_missing_deployment_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            await LifecycleService.promote_to_next_stage(
                TENANT_ID, _admin_user(), uuid4(),
            )

    @pytest.mark.asyncio
    async def test_demote_staging_to_dev(self) -> None:
        dep = await _create_deployment(environment="staging")
        result = await LifecycleService.demote_to_previous_stage(
            TENANT_ID, _admin_user(), dep.id,
        )
        assert result.environment == "dev"

    @pytest.mark.asyncio
    async def test_demote_production_to_canary(self) -> None:
        dep = await _create_deployment(environment="production")
        result = await LifecycleService.demote_to_previous_stage(
            TENANT_ID, _admin_user(), dep.id,
        )
        assert result.environment == "canary"

    @pytest.mark.asyncio
    async def test_demote_dev_raises(self) -> None:
        dep = await _create_deployment(environment="dev")
        with pytest.raises(ValueError, match="Cannot demote"):
            await LifecycleService.demote_to_previous_stage(
                TENANT_ID, _admin_user(), dep.id,
            )

    @pytest.mark.asyncio
    async def test_demote_missing_deployment_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            await LifecycleService.demote_to_previous_stage(
                TENANT_ID, _admin_user(), uuid4(),
            )

    @pytest.mark.asyncio
    async def test_promote_rbac_viewer_denied(self) -> None:
        dep = await _create_deployment(environment="dev")
        with pytest.raises(PermissionError, match="Insufficient permissions"):
            await LifecycleService.promote_to_next_stage(
                TENANT_ID, _viewer_user(), dep.id,
            )

    @pytest.mark.asyncio
    async def test_demote_rbac_viewer_denied(self) -> None:
        dep = await _create_deployment(environment="staging")
        with pytest.raises(PermissionError, match="Insufficient permissions"):
            await LifecycleService.demote_to_previous_stage(
                TENANT_ID, _viewer_user(), dep.id,
            )


# ── Environment Management ──────────────────────────────────────────


class TestEnvironments:
    """Tests for environment listing."""

    @pytest.mark.asyncio
    async def test_list_environments_returns_defaults(self) -> None:
        envs = await LifecycleService.list_environments(TENANT_ID)
        assert isinstance(envs, list)
        assert len(envs) == 4
        assert all(isinstance(e, EnvironmentInfo) for e in envs)

    @pytest.mark.asyncio
    async def test_environment_names(self) -> None:
        envs = await LifecycleService.list_environments(TENANT_ID)
        names = [e.name for e in envs]
        assert "dev" in names
        assert "staging" in names
        assert "production" in names

    @pytest.mark.asyncio
    async def test_environment_with_deployment(self) -> None:
        await _create_deployment(environment="staging")
        envs = await LifecycleService.list_environments(TENANT_ID)
        staging = next(e for e in envs if e.name == "staging")
        assert staging.deployed_version is not None
        assert staging.instance_count > 0

    @pytest.mark.asyncio
    async def test_environment_without_deployment(self) -> None:
        envs = await LifecycleService.list_environments(TENANT_ID)
        dev = next(e for e in envs if e.name == "dev")
        assert dev.deployed_version is None
        assert dev.instance_count == 0

    @pytest.mark.asyncio
    async def test_list_environments_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await LifecycleService.list_environments("")


# ── Config Diff ─────────────────────────────────────────────────────


class TestConfigDiff:
    """Tests for config diff between environments."""

    @pytest.mark.asyncio
    async def test_diff_no_deployments(self) -> None:
        diff = await LifecycleService.get_config_diff(TENANT_ID, "dev", "staging")
        assert isinstance(diff, ConfigDiff)
        assert diff.source_env == "dev"
        assert diff.target_env == "staging"
        assert diff.differences == []

    @pytest.mark.asyncio
    async def test_diff_with_different_versions(self) -> None:
        await _create_deployment(environment="dev")
        await _create_deployment(environment="staging")
        diff = await LifecycleService.get_config_diff(TENANT_ID, "dev", "staging")
        # Different agent_ids means different version_ids
        version_diff = [d for d in diff.differences if d.get("field") == "version_id"]
        assert len(version_diff) == 1

    @pytest.mark.asyncio
    async def test_diff_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await LifecycleService.get_config_diff("", "dev", "staging")


# ── Deployment History ──────────────────────────────────────────────


class TestDeploymentHistory:
    """Tests for deployment history timeline."""

    @pytest.mark.asyncio
    async def test_history_empty(self) -> None:
        entries = await LifecycleService.get_deployment_history(TENANT_ID, "staging")
        assert entries == []

    @pytest.mark.asyncio
    async def test_history_with_deployments(self) -> None:
        await _create_deployment(environment="staging")
        await _create_deployment(environment="staging")
        entries = await LifecycleService.get_deployment_history(TENANT_ID, "staging")
        assert len(entries) == 2
        assert all(isinstance(e, DeploymentHistoryEntry) for e in entries)

    @pytest.mark.asyncio
    async def test_history_filters_by_environment(self) -> None:
        await _create_deployment(environment="staging")
        await _create_deployment(environment="production")
        staging_entries = await LifecycleService.get_deployment_history(TENANT_ID, "staging")
        assert len(staging_entries) == 1
        assert staging_entries[0].environment == "staging"

    @pytest.mark.asyncio
    async def test_history_entry_fields(self) -> None:
        await _create_deployment(environment="dev")
        entries = await LifecycleService.get_deployment_history(TENANT_ID, "dev")
        entry = entries[0]
        assert entry.id is not None
        assert entry.agent_id is not None
        assert entry.version_id is not None
        assert entry.strategy == "rolling"
        assert entry.environment == "dev"

    @pytest.mark.asyncio
    async def test_history_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await LifecycleService.get_deployment_history("", "staging")


# ── Approval Gates ──────────────────────────────────────────────────


class TestApprovalGates:
    """Tests for approval gate configuration."""

    @pytest.mark.asyncio
    async def test_configure_gates(self) -> None:
        gates = await LifecycleService.configure_gates(
            TENANT_ID,
            _admin_user(),
            [
                {"from_stage": "dev", "to_stage": "staging", "required_approvers": 1},
                {"from_stage": "staging", "to_stage": "canary", "required_approvers": 2},
            ],
        )
        assert len(gates) == 2
        assert all(isinstance(g, ApprovalGate) for g in gates)

    @pytest.mark.asyncio
    async def test_configure_gates_replaces_existing(self) -> None:
        await LifecycleService.configure_gates(
            TENANT_ID,
            _admin_user(),
            [{"from_stage": "dev", "to_stage": "staging", "required_approvers": 1}],
        )
        gates = await LifecycleService.configure_gates(
            TENANT_ID,
            _admin_user(),
            [{"from_stage": "staging", "to_stage": "canary", "required_approvers": 3}],
        )
        assert len(gates) == 1
        assert gates[0].from_stage == "staging"

    @pytest.mark.asyncio
    async def test_gate_defaults(self) -> None:
        gates = await LifecycleService.configure_gates(
            TENANT_ID,
            _admin_user(),
            [{"from_stage": "dev", "to_stage": "staging"}],
        )
        gate = gates[0]
        assert gate.required_approvers == 1
        assert gate.require_health_check is True
        assert gate.require_tests_pass is True
        assert gate.enabled is True

    @pytest.mark.asyncio
    async def test_configure_gates_rbac(self) -> None:
        with pytest.raises(PermissionError, match="Insufficient permissions"):
            await LifecycleService.configure_gates(
                TENANT_ID,
                _viewer_user(),
                [{"from_stage": "dev", "to_stage": "staging"}],
            )

    @pytest.mark.asyncio
    async def test_configure_gates_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await LifecycleService.configure_gates(
                "",
                _admin_user(),
                [{"from_stage": "dev", "to_stage": "staging"}],
            )


# ── Post-Deployment Health ──────────────────────────────────────────


class TestDeploymentHealth:
    """Tests for post-deployment health metrics."""

    @pytest.mark.asyncio
    async def test_health_defaults(self) -> None:
        dep = await _create_deployment(environment="staging")
        health = await LifecycleService.get_deployment_health(TENANT_ID, dep.id)
        assert isinstance(health, HealthMetrics)
        assert health.status == "healthy"
        assert health.response_time_p50 >= 0
        assert health.response_time_p95 >= 0
        assert health.response_time_p99 >= 0
        assert 0 <= health.error_rate <= 1
        assert health.throughput_rps >= 0

    @pytest.mark.asyncio
    async def test_health_missing_deployment_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            await LifecycleService.get_deployment_health(TENANT_ID, uuid4())

    @pytest.mark.asyncio
    async def test_health_includes_rollback_threshold(self) -> None:
        dep = await _create_deployment(environment="staging")
        health = await LifecycleService.get_deployment_health(TENANT_ID, dep.id)
        assert health.auto_rollback_threshold == 0.05

    @pytest.mark.asyncio
    async def test_health_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await LifecycleService.get_deployment_health("", uuid4())


# ── Model Validation ────────────────────────────────────────────────


class TestModelValidation:
    """Tests for new Pydantic model validation."""

    def test_approval_gate_defaults(self) -> None:
        gate = ApprovalGate(from_stage="dev", to_stage="staging")
        assert gate.required_approvers == 1
        assert gate.auto_approve_after_hours is None
        assert gate.require_health_check is True
        assert gate.require_tests_pass is True
        assert gate.enabled is True

    def test_environment_info_defaults(self) -> None:
        env = EnvironmentInfo(name="dev", display_name="Development")
        assert env.status == "active"
        assert env.deployed_version is None
        assert env.health_status == "unknown"
        assert env.instance_count == 0

    def test_health_metrics_defaults(self) -> None:
        hm = HealthMetrics(deployment_id=uuid4())
        assert hm.status == "healthy"
        assert hm.response_time_p50 == 0.0
        assert hm.error_rate == 0.0
        assert hm.uptime_pct == 100.0
        assert hm.auto_rollback_triggered is False

    def test_pipeline_stage_info(self) -> None:
        stage = PipelineStageInfo(stage="dev", label="Draft")
        assert stage.deployments == []
        assert stage.approval_gate is None

    def test_config_diff(self) -> None:
        diff = ConfigDiff(source_env="dev", target_env="staging")
        assert diff.differences == []
        assert diff.source_version is None

    def test_deployment_history_entry(self) -> None:
        entry = DeploymentHistoryEntry(
            id=uuid4(),
            agent_id=uuid4(),
            version_id="v1",
            environment="staging",
            strategy="rolling",
            status="active",
        )
        assert entry.deployed_by is None
        assert entry.duration_seconds is None
