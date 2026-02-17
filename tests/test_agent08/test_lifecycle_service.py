"""Tests for LifecycleService — state transitions, deployments, cred rotation, health, anomalies, scheduling."""

from __future__ import annotations

import statistics
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.lifecycle import (
    Anomaly,
    CredentialRotationResult,
    CronSchedule,
    Deployment,
    DeploymentStrategy,
    DeploymentStrategyType,
    HealthScore,
    LifecycleTransition,
    ScheduledJob,
)
from app.services.lifecycle_service import (
    LifecycleService,
    _agent_states,
    _classify_severity,
    _metrics_store,
    _scheduled_jobs,
)


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-lifecycle-test"


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


# ── State Transitions ───────────────────────────────────────────────


class TestStateTransitions:
    """Valid and invalid lifecycle state transitions."""

    @pytest.mark.asyncio
    async def test_draft_to_review(self) -> None:
        agent_id = uuid4()
        result = await LifecycleService.transition(
            TENANT_ID, _admin_user(), agent_id, "review",
        )
        assert result.from_state == "draft"
        assert result.to_state == "review"
        assert isinstance(result, LifecycleTransition)

    @pytest.mark.asyncio
    async def test_full_lifecycle_path(self) -> None:
        agent_id = uuid4()
        transitions = ["review", "approved", "published", "deprecated", "archived"]
        for target in transitions:
            result = await LifecycleService.transition(
                TENANT_ID, _admin_user(), agent_id, target,
            )
            assert result.to_state == target

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self) -> None:
        agent_id = uuid4()
        with pytest.raises(ValueError, match="Invalid transition"):
            await LifecycleService.transition(
                TENANT_ID, _admin_user(), agent_id, "published",
            )

    @pytest.mark.asyncio
    async def test_review_back_to_draft(self) -> None:
        agent_id = uuid4()
        await LifecycleService.transition(TENANT_ID, _admin_user(), agent_id, "review")
        result = await LifecycleService.transition(
            TENANT_ID, _admin_user(), agent_id, "draft",
        )
        assert result.from_state == "review"
        assert result.to_state == "draft"

    @pytest.mark.asyncio
    async def test_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            await LifecycleService.transition("", _admin_user(), uuid4(), "review")

    @pytest.mark.asyncio
    async def test_rbac_viewer_cannot_approve(self) -> None:
        agent_id = uuid4()
        await LifecycleService.transition(TENANT_ID, _admin_user(), agent_id, "review")
        with pytest.raises(PermissionError, match="Insufficient permissions"):
            await LifecycleService.transition(
                TENANT_ID, _viewer_user(), agent_id, "approved",
            )

    @pytest.mark.asyncio
    async def test_transition_records_reason(self) -> None:
        agent_id = uuid4()
        result = await LifecycleService.transition(
            TENANT_ID, _admin_user(), agent_id, "review", reason="initial review",
        )
        assert result.reason == "initial review"


# ── Deployment Strategies ───────────────────────────────────────────


class TestDeploymentStrategies:
    """Canary, blue-green, rolling, shadow deployments."""

    @pytest.mark.asyncio
    async def test_canary_deployment(self) -> None:
        strategy = DeploymentStrategy(type=DeploymentStrategyType.CANARY, canary_percentage=10)
        result = await LifecycleService.deploy(
            TENANT_ID, _admin_user(), uuid4(), strategy, "staging",
        )
        assert isinstance(result, Deployment)
        assert result.status == "deploying"
        assert result.strategy.type == DeploymentStrategyType.CANARY

    @pytest.mark.asyncio
    async def test_blue_green_deployment(self) -> None:
        strategy = DeploymentStrategy(type=DeploymentStrategyType.BLUE_GREEN)
        result = await LifecycleService.deploy(
            TENANT_ID, _admin_user(), uuid4(), strategy, "production",
        )
        assert result.status == "deploying"
        assert result.environment == "production"

    @pytest.mark.asyncio
    async def test_shadow_deployment_status(self) -> None:
        strategy = DeploymentStrategy(type=DeploymentStrategyType.SHADOW)
        result = await LifecycleService.deploy(
            TENANT_ID, _admin_user(), uuid4(), strategy, "staging",
        )
        assert result.status == "shadow"

    @pytest.mark.asyncio
    async def test_rollback_deployment(self) -> None:
        strategy = DeploymentStrategy(type=DeploymentStrategyType.ROLLING)
        dep = await LifecycleService.deploy(
            TENANT_ID, _admin_user(), uuid4(), strategy, "staging",
        )
        rolled = await LifecycleService.rollback_deployment(
            TENANT_ID, _admin_user(), dep.id, reason="error rate too high",
        )
        assert rolled.status == "rolled_back"
        assert rolled.completed_at is not None

    @pytest.mark.asyncio
    async def test_rollback_missing_deployment_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            await LifecycleService.rollback_deployment(
                TENANT_ID, _admin_user(), uuid4(),
            )


# ── Credential Rotation on Promotion ────────────────────────────────


class TestCredentialRotation:
    """Credential rotation on promotion via Vault."""

    @pytest.mark.asyncio
    async def test_rotation_with_secrets_manager(self) -> None:
        sm = AsyncMock()
        sm.get_secret = AsyncMock(return_value="secret-value")
        sm.put_secret = AsyncMock()
        sm.delete_secret = AsyncMock()

        result = await LifecycleService.rotate_credentials_on_promotion(
            TENANT_ID, uuid4(), "staging", "production", secrets_manager=sm,
        )

        assert isinstance(result, CredentialRotationResult)
        assert result.secrets_rotated == 3
        assert result.old_leases_revoked == 3
        assert len(result.new_lease_ids) == 3

    @pytest.mark.asyncio
    async def test_rotation_dry_run_without_secrets_manager(self) -> None:
        result = await LifecycleService.rotate_credentials_on_promotion(
            TENANT_ID, uuid4(), "staging", "production",
        )
        assert result.secrets_rotated == 3
        assert result.old_leases_revoked == 3

    @pytest.mark.asyncio
    async def test_rotation_handles_partial_failure(self) -> None:
        sm = AsyncMock()
        call_count = 0

        async def get_side_effect(*args: Any, **kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Vault unavailable")
            return "secret"

        sm.get_secret = AsyncMock(side_effect=get_side_effect)
        sm.put_secret = AsyncMock()
        sm.delete_secret = AsyncMock()

        result = await LifecycleService.rotate_credentials_on_promotion(
            TENANT_ID, uuid4(), "staging", "production", secrets_manager=sm,
        )
        assert result.secrets_rotated == 2


# ── Health Score ────────────────────────────────────────────────────


class TestHealthScore:
    """Health score computation."""

    @pytest.mark.asyncio
    async def test_default_health_no_metrics(self) -> None:
        result = await LifecycleService.compute_health_score(TENANT_ID, uuid4())
        assert isinstance(result, HealthScore)
        assert result.overall == 1.0
        assert result.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_health_with_metrics(self) -> None:
        agent_id = uuid4()
        key = f"{TENANT_ID}:{agent_id}"
        _metrics_store[key] = [
            {"success_rate": 0.95, "latency": 200.0, "error_rate": 0.05, "cost_score": 0.8},
            {"success_rate": 0.90, "latency": 300.0, "error_rate": 0.10, "cost_score": 0.7},
        ]
        result = await LifecycleService.compute_health_score(TENANT_ID, agent_id)
        assert 0.0 <= result.overall <= 1.0
        assert result.avg_latency == 250.0

    @pytest.mark.asyncio
    async def test_health_clamped_0_to_1(self) -> None:
        agent_id = uuid4()
        key = f"{TENANT_ID}:{agent_id}"
        _metrics_store[key] = [
            {"success_rate": 0.0, "latency": 50000.0, "error_rate": 1.0, "cost_score": 0.0},
        ]
        result = await LifecycleService.compute_health_score(TENANT_ID, agent_id)
        assert 0.0 <= result.overall <= 1.0


# ── Anomaly Detection ───────────────────────────────────────────────


class TestAnomalyDetection:
    """Z-score based anomaly detection."""

    @pytest.mark.asyncio
    async def test_no_anomaly_with_few_metrics(self) -> None:
        agent_id = uuid4()
        key = f"{TENANT_ID}:{agent_id}"
        _metrics_store[key] = [
            {"latency": 100.0},
            {"latency": 110.0},
        ]
        result = await LifecycleService.detect_anomalies(TENANT_ID, agent_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_detects_latency_spike(self) -> None:
        agent_id = uuid4()
        key = f"{TENANT_ID}:{agent_id}"
        _metrics_store[key] = [
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 102.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 101.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 99.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 101.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 50000.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
        ]
        anomalies = await LifecycleService.detect_anomalies(TENANT_ID, agent_id)
        latency_anomalies = [a for a in anomalies if a.metric == "latency"]
        assert len(latency_anomalies) >= 1
        assert latency_anomalies[0].z_score >= 2.0

    @pytest.mark.asyncio
    async def test_severity_classification(self) -> None:
        assert _classify_severity(4.5) == "critical"
        assert _classify_severity(3.5) == "high"
        assert _classify_severity(2.7) == "medium"
        assert _classify_severity(2.1) == "low"

    @pytest.mark.asyncio
    async def test_no_anomaly_with_stable_metrics(self) -> None:
        agent_id = uuid4()
        key = f"{TENANT_ID}:{agent_id}"
        _metrics_store[key] = [
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
            {"latency": 100.0, "success_rate": 0.99, "error_rate": 0.01, "cost_score": 0.9},
        ]
        anomalies = await LifecycleService.detect_anomalies(TENANT_ID, agent_id)
        assert anomalies == []


# ── Scheduling ──────────────────────────────────────────────────────


class TestScheduling:
    """Scheduled execution jobs."""

    @pytest.mark.asyncio
    async def test_schedule_creates_job(self) -> None:
        schedule = CronSchedule(expression="0 * * * *")
        result = await LifecycleService.schedule_execution(
            TENANT_ID, _admin_user(), uuid4(), schedule,
        )
        assert isinstance(result, ScheduledJob)
        assert result.status == "active"
        assert result.schedule.expression == "0 * * * *"

    @pytest.mark.asyncio
    async def test_list_scheduled_jobs(self) -> None:
        schedule = CronSchedule(expression="*/5 * * * *")
        await LifecycleService.schedule_execution(
            TENANT_ID, _admin_user(), uuid4(), schedule,
        )
        jobs = await LifecycleService.list_scheduled_jobs(TENANT_ID)
        assert len(jobs) == 1

    @pytest.mark.asyncio
    async def test_list_jobs_empty_tenant(self) -> None:
        jobs = await LifecycleService.list_scheduled_jobs("empty-tenant")
        assert jobs == []

    @pytest.mark.asyncio
    async def test_viewer_cannot_schedule(self) -> None:
        schedule = CronSchedule(expression="0 0 * * *")
        with pytest.raises(PermissionError):
            await LifecycleService.schedule_execution(
                TENANT_ID, _viewer_user(), uuid4(), schedule,
            )
