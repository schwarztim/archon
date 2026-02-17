"""Tests for DeploymentService — deploy, status, rollback, scale, infra, certs, backup, metrics."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.deployment import (
    BackupResult,
    CertRotationResult,
    ComponentConfig,
    ComponentStatus,
    DeploymentConfig,
    DeploymentState,
    DeploymentStatus,
    EnvironmentDeployment,
    EnvironmentType,
    InfraHealth,
    PlatformMetrics,
    ScaleResult,
)
from app.services.deployment_service import (
    DeploymentService,
    _deployments,
    _component_replicas,
)

# ── Fixtures ────────────────────────────────────────────────────────

TENANT = "tenant-deploy-test"


def _infra_user(tenant_id: str = TENANT, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="infra@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=[],
        session_id="sess-deploy",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _viewer_user() -> AuthenticatedUser:
    return _infra_user(roles=["viewer"])


def _deploy_config(**overrides: Any) -> DeploymentConfig:
    defaults: dict[str, Any] = dict(
        environment=EnvironmentType.STAGING,
        version="1.0.0",
        components=[
            ComponentConfig(name="api", replicas=2),
            ComponentConfig(name="worker", replicas=1),
        ],
    )
    defaults.update(overrides)
    return DeploymentConfig(**defaults)


@pytest.fixture(autouse=True)
def _clear_stores() -> None:
    _deployments.clear()
    _component_replicas.clear()


# ── deploy_environment ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deploy_environment_success() -> None:
    user = _infra_user()
    config = _deploy_config()
    dep = await DeploymentService.deploy_environment(TENANT, user, config)

    assert isinstance(dep, EnvironmentDeployment)
    assert dep.status == DeploymentState.COMPLETED
    assert dep.tenant_id == TENANT
    assert len(dep.components) == 2


@pytest.mark.asyncio
async def test_deploy_environment_rbac_denied() -> None:
    user = _viewer_user()
    with pytest.raises(PermissionError, match="Insufficient"):
        await DeploymentService.deploy_environment(TENANT, user, _deploy_config())


@pytest.mark.asyncio
async def test_deploy_environment_empty_tenant_raises() -> None:
    user = _infra_user()
    with pytest.raises(ValueError, match="tenant_id"):
        await DeploymentService.deploy_environment("", user, _deploy_config())


# ── get_deployment_status ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_status_success() -> None:
    user = _infra_user()
    dep = await DeploymentService.deploy_environment(TENANT, user, _deploy_config())
    status = await DeploymentService.get_deployment_status(TENANT, dep.id)

    assert isinstance(status, DeploymentStatus)
    assert status.deployment_id == dep.id
    assert status.overall_status == DeploymentState.COMPLETED


@pytest.mark.asyncio
async def test_get_status_not_found() -> None:
    with pytest.raises(ValueError, match="not found"):
        await DeploymentService.get_deployment_status(TENANT, uuid4())


# ── rollback_deployment ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollback_success() -> None:
    user = _infra_user()
    dep = await DeploymentService.deploy_environment(TENANT, user, _deploy_config())
    status = await DeploymentService.rollback_deployment(TENANT, user, dep.id)

    assert status.overall_status == DeploymentState.ROLLED_BACK


@pytest.mark.asyncio
async def test_rollback_rbac_denied() -> None:
    admin = _infra_user()
    dep = await DeploymentService.deploy_environment(TENANT, admin, _deploy_config())
    viewer = _viewer_user()
    with pytest.raises(PermissionError):
        await DeploymentService.rollback_deployment(TENANT, viewer, dep.id)


# ── scale_component ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scale_component_up() -> None:
    user = _infra_user()
    await DeploymentService.deploy_environment(TENANT, user, _deploy_config())
    result = await DeploymentService.scale_component(TENANT, user, "api", 5)

    assert isinstance(result, ScaleResult)
    assert result.previous_replicas == 2
    assert result.new_replicas == 5
    assert result.status == "scaled"


@pytest.mark.asyncio
async def test_scale_component_rbac_denied() -> None:
    viewer = _viewer_user()
    with pytest.raises(PermissionError):
        await DeploymentService.scale_component(TENANT, viewer, "api", 3)


# ── get_infrastructure_health ───────────────────────────────────────


@pytest.mark.asyncio
async def test_infra_health_no_secrets_manager() -> None:
    health = await DeploymentService.get_infrastructure_health(TENANT)

    assert isinstance(health, InfraHealth)
    assert health.overall == ComponentStatus.HEALTHY


@pytest.mark.asyncio
async def test_infra_health_vault_healthy() -> None:
    sm = AsyncMock()
    sm.get_secret = AsyncMock(return_value={"status": "ok"})
    health = await DeploymentService.get_infrastructure_health(TENANT, secrets_manager=sm)

    assert health.vault_status == ComponentStatus.HEALTHY
    assert health.overall == ComponentStatus.HEALTHY


@pytest.mark.asyncio
async def test_infra_health_vault_unhealthy() -> None:
    sm = AsyncMock()
    sm.get_secret = AsyncMock(side_effect=Exception("vault down"))
    health = await DeploymentService.get_infrastructure_health(TENANT, secrets_manager=sm)

    assert health.vault_status == ComponentStatus.UNHEALTHY
    assert health.overall == ComponentStatus.UNHEALTHY


# ── rotate_tls_certificates ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_rotate_certs_no_secrets_manager() -> None:
    user = _infra_user()
    result = await DeploymentService.rotate_tls_certificates(TENANT, user)

    assert isinstance(result, CertRotationResult)
    assert result.certificates_rotated == 3
    assert result.errors == []


@pytest.mark.asyncio
async def test_rotate_certs_with_secrets_manager() -> None:
    user = _infra_user()
    sm = AsyncMock()
    sm.issue_certificate = AsyncMock()
    result = await DeploymentService.rotate_tls_certificates(
        TENANT, user, secrets_manager=sm,
    )

    assert result.certificates_rotated == 3
    assert sm.issue_certificate.await_count == 3


# ── backup ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backup_success() -> None:
    user = _infra_user()
    result = await DeploymentService.backup(TENANT, user)

    assert isinstance(result, BackupResult)
    assert result.size_mb == 256.0
    assert "postgresql" in result.components_backed_up


@pytest.mark.asyncio
async def test_backup_rbac_denied() -> None:
    viewer = _viewer_user()
    with pytest.raises(PermissionError):
        await DeploymentService.backup(TENANT, viewer)


# ── get_metrics ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_metrics_returns_values() -> None:
    metrics = await DeploymentService.get_metrics(TENANT)

    assert isinstance(metrics, PlatformMetrics)
    assert 0.0 <= metrics.cpu_usage <= 100.0
    assert metrics.p99_latency > 0


@pytest.mark.asyncio
async def test_get_metrics_empty_tenant_raises() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        await DeploymentService.get_metrics("")
