"""Unit tests for LifecycleManager service logic.

Tests cover:
- Deployment creation (rolling, canary, blue_green strategies)
- Canary traffic promotion
- Replica scaling with min/max bounds
- Rollback to previous deployment
- Retirement
- Health check recording
- Auto-rollback on high error rate
- Edge cases: missing records, boundary values
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models.lifecycle import DeploymentRecord, HealthCheck, LifecycleEvent
from app.services.lifecycle import LifecycleManager

# ── Fixed UUIDs ─────────────────────────────────────────────────────

AGENT_ID = UUID("10000001-0001-0001-0001-000000000001")
VERSION_ID = UUID("20000001-0001-0001-0001-000000000001")
DEPLOY_ID = UUID("30000001-0001-0001-0001-000000000001")
PREV_DEPLOY_ID = UUID("30000002-0002-0002-0002-000000000002")
USER_ID = UUID("40000001-0001-0001-0001-000000000001")
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ── Factories ───────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _deployment(
    *,
    deploy_id: UUID = DEPLOY_ID,
    agent_id: UUID = AGENT_ID,
    version_id: UUID = VERSION_ID,
    environment: str = "staging",
    strategy: str = "rolling",
    status: str = "active",
    traffic_percentage: int = 100,
    error_rate_threshold: float = 0.05,
    replicas: int = 2,
    min_replicas: int = 1,
    max_replicas: int = 10,
    previous_deployment_id: UUID | None = None,
) -> DeploymentRecord:
    """Build a DeploymentRecord with controllable fields."""
    return DeploymentRecord(
        id=deploy_id,
        agent_id=agent_id,
        version_id=version_id,
        environment=environment,
        strategy=strategy,
        status=status,
        traffic_percentage=traffic_percentage,
        error_rate_threshold=error_rate_threshold,
        replicas=replicas,
        min_replicas=min_replicas,
        max_replicas=max_replicas,
        previous_deployment_id=previous_deployment_id,
        config={},
        deployed_by=None,
        deployed_at=NOW,
        retired_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _setup_deploy_session(
    *,
    active_deployment: DeploymentRecord | None = None,
) -> AsyncMock:
    """Wire up a mock session for LifecycleManager.deploy.

    deploy calls _active_deployment (session.exec) then creates a record.
    """
    session = _mock_session()

    # _active_deployment uses session.exec → result.first()
    exec_result = MagicMock()
    exec_result.first.return_value = active_deployment
    session.exec = AsyncMock(return_value=exec_result)

    # session.commit and session.refresh are already AsyncMock stubs
    # Make refresh a no-op that doesn't alter the record
    session.refresh = AsyncMock()

    return session


def _setup_get_session(
    record: DeploymentRecord | None,
) -> AsyncMock:
    """Wire up a mock session where session.get returns the given record."""
    session = _mock_session()
    session.get = AsyncMock(return_value=record)
    session.refresh = AsyncMock()
    return session


# ═══════════════════════════════════════════════════════════════════
# Deploy
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_deploy_rolling_creates_active_record() -> None:
    """Rolling deploy sets traffic to 100% and status to active."""
    session = _setup_deploy_session()

    result = await LifecycleManager.deploy(
        session,
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        environment="staging",
        strategy="rolling",
        replicas=2,
    )

    assert isinstance(result, DeploymentRecord)
    assert result.status == "active"
    assert result.traffic_percentage == 100
    assert result.strategy == "rolling"
    assert result.agent_id == AGENT_ID
    assert result.version_id == VERSION_ID
    assert result.environment == "staging"
    assert result.replicas == 2
    session.add.assert_called()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_deploy_canary_starts_at_5_percent() -> None:
    """Canary deploy starts with 5% traffic."""
    session = _setup_deploy_session()

    result = await LifecycleManager.deploy(
        session,
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        strategy="canary",
    )

    assert result.traffic_percentage == 5
    assert result.strategy == "canary"
    assert result.status == "active"


@pytest.mark.asyncio
async def test_deploy_blue_green_starts_at_0_percent() -> None:
    """Blue-green deploy starts with 0% traffic."""
    session = _setup_deploy_session()

    result = await LifecycleManager.deploy(
        session,
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        strategy="blue_green",
    )

    assert result.traffic_percentage == 0
    assert result.strategy == "blue_green"


@pytest.mark.asyncio
async def test_deploy_links_previous_deployment() -> None:
    """When an active deployment exists, new deploy records previous_deployment_id."""
    prev = _deployment(deploy_id=PREV_DEPLOY_ID)
    session = _setup_deploy_session(active_deployment=prev)

    result = await LifecycleManager.deploy(
        session,
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
    )

    assert result.previous_deployment_id == PREV_DEPLOY_ID


@pytest.mark.asyncio
async def test_deploy_no_previous_deployment() -> None:
    """First deploy has no previous_deployment_id."""
    session = _setup_deploy_session(active_deployment=None)

    result = await LifecycleManager.deploy(
        session,
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
    )

    assert result.previous_deployment_id is None


@pytest.mark.asyncio
async def test_deploy_records_deployed_by() -> None:
    """deploy stores the actor who triggered the deployment."""
    session = _setup_deploy_session()

    result = await LifecycleManager.deploy(
        session,
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        deployed_by=USER_ID,
    )

    assert result.deployed_by == USER_ID


@pytest.mark.asyncio
async def test_deploy_custom_config() -> None:
    """deploy stores arbitrary config dict."""
    session = _setup_deploy_session()
    cfg = {"memory_limit": "512Mi", "cpu": "0.5"}

    result = await LifecycleManager.deploy(
        session,
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        config=cfg,
    )

    assert result.config == cfg


# ═══════════════════════════════════════════════════════════════════
# Promote canary
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_promote_canary_increases_traffic() -> None:
    """promote_canary updates traffic_percentage."""
    record = _deployment(traffic_percentage=5, strategy="canary")
    session = _setup_get_session(record)

    result = await LifecycleManager.promote_canary(
        session, DEPLOY_ID, traffic_percentage=50,
    )

    assert result is not None
    assert result.traffic_percentage == 50
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_promote_canary_caps_at_100() -> None:
    """Traffic percentage is capped at 100."""
    record = _deployment(traffic_percentage=80, strategy="canary")
    session = _setup_get_session(record)

    result = await LifecycleManager.promote_canary(
        session, DEPLOY_ID, traffic_percentage=150,
    )

    assert result is not None
    assert result.traffic_percentage == 100


@pytest.mark.asyncio
async def test_promote_canary_missing_deployment_returns_none() -> None:
    """promote_canary returns None for non-existent deployment."""
    session = _setup_get_session(None)

    result = await LifecycleManager.promote_canary(
        session, uuid4(), traffic_percentage=50,
    )

    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Scale
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scale_within_bounds() -> None:
    """Scaling within min/max bounds sets replicas directly."""
    record = _deployment(replicas=2, min_replicas=1, max_replicas=10)
    session = _setup_get_session(record)

    result = await LifecycleManager.scale(session, DEPLOY_ID, replicas=5)

    assert result is not None
    assert result.replicas == 5
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_scale_clamps_to_max() -> None:
    """Scaling above max_replicas clamps to max."""
    record = _deployment(replicas=2, min_replicas=1, max_replicas=10)
    session = _setup_get_session(record)

    result = await LifecycleManager.scale(session, DEPLOY_ID, replicas=20)

    assert result is not None
    assert result.replicas == 10


@pytest.mark.asyncio
async def test_scale_clamps_to_min() -> None:
    """Scaling below min_replicas clamps to min."""
    record = _deployment(replicas=5, min_replicas=2, max_replicas=10)
    session = _setup_get_session(record)

    result = await LifecycleManager.scale(session, DEPLOY_ID, replicas=0)

    assert result is not None
    assert result.replicas == 2


@pytest.mark.asyncio
async def test_scale_missing_deployment_returns_none() -> None:
    """scale returns None for non-existent deployment."""
    session = _setup_get_session(None)

    result = await LifecycleManager.scale(session, uuid4(), replicas=3)

    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Rollback
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rollback_marks_current_as_rolled_back() -> None:
    """Rollback sets current deployment status to rolled_back."""
    record = _deployment(status="active", previous_deployment_id=None)
    session = _setup_get_session(record)

    result = await LifecycleManager.rollback(session, DEPLOY_ID)

    assert result is not None
    assert record.status == "rolled_back"


@pytest.mark.asyncio
async def test_rollback_reactivates_previous_deployment() -> None:
    """Rollback reactivates the previous deployment at 100% traffic."""
    prev = _deployment(
        deploy_id=PREV_DEPLOY_ID,
        status="rolled_back",
        traffic_percentage=0,
    )
    current = _deployment(
        deploy_id=DEPLOY_ID,
        status="active",
        previous_deployment_id=PREV_DEPLOY_ID,
    )

    session = _mock_session()
    # session.get is called for current deployment, then for previous
    session.get = AsyncMock(side_effect=[current, prev])
    session.refresh = AsyncMock()

    result = await LifecycleManager.rollback(session, DEPLOY_ID, reason="bad release")

    assert current.status == "rolled_back"
    assert prev.status == "active"
    assert prev.traffic_percentage == 100
    # Returns the reactivated deployment
    assert result is prev


@pytest.mark.asyncio
async def test_rollback_no_previous_returns_current() -> None:
    """If no previous deployment exists, rollback returns the (now rolled_back) current."""
    record = _deployment(status="active", previous_deployment_id=None)
    session = _setup_get_session(record)

    result = await LifecycleManager.rollback(session, DEPLOY_ID)

    assert result is record
    assert record.status == "rolled_back"


@pytest.mark.asyncio
async def test_rollback_missing_deployment_returns_none() -> None:
    """rollback returns None for non-existent deployment."""
    session = _setup_get_session(None)

    result = await LifecycleManager.rollback(session, uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_rollback_records_actor_id() -> None:
    """rollback passes actor_id to the lifecycle event."""
    record = _deployment(status="active", previous_deployment_id=None)
    session = _setup_get_session(record)

    with patch.object(
        LifecycleManager, "_record_event", new_callable=AsyncMock,
    ) as mock_event:
        await LifecycleManager.rollback(
            session, DEPLOY_ID, reason="hotfix", actor_id=USER_ID,
        )

        mock_event.assert_awaited_once()
        call_kwargs = mock_event.call_args.kwargs
        assert call_kwargs["actor_id"] == USER_ID
        assert call_kwargs["event_type"] == "rolled_back"
        assert call_kwargs["message"] == "hotfix"


# ═══════════════════════════════════════════════════════════════════
# Retire
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_retire_sets_status_and_zeros() -> None:
    """Retire sets status to retired, traffic to 0, replicas to 0."""
    record = _deployment(status="active", replicas=3, traffic_percentage=100)
    session = _setup_get_session(record)

    result = await LifecycleManager.retire(session, DEPLOY_ID)

    assert result is not None
    assert result.status == "retired"
    assert result.traffic_percentage == 0
    assert result.replicas == 0
    assert result.retired_at is not None
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_retire_missing_deployment_returns_none() -> None:
    """retire returns None for non-existent deployment."""
    session = _setup_get_session(None)

    result = await LifecycleManager.retire(session, uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_retire_records_event() -> None:
    """retire records a lifecycle event with correct type."""
    record = _deployment(status="active")
    session = _setup_get_session(record)

    with patch.object(
        LifecycleManager, "_record_event", new_callable=AsyncMock,
    ) as mock_event:
        await LifecycleManager.retire(
            session, DEPLOY_ID, reason="end of life", actor_id=USER_ID,
        )

        mock_event.assert_awaited_once()
        call_kwargs = mock_event.call_args.kwargs
        assert call_kwargs["event_type"] == "retired"
        assert call_kwargs["from_state"] == "active"
        assert call_kwargs["to_state"] == "retired"
        assert call_kwargs["actor_id"] == USER_ID


# ═══════════════════════════════════════════════════════════════════
# Health check recording
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_record_health_check_healthy() -> None:
    """Recording a healthy check persists the HealthCheck model."""
    record = _deployment(status="active", error_rate_threshold=0.05)
    session = _setup_get_session(record)

    result = await LifecycleManager.record_health_check(
        session,
        deployment_id=DEPLOY_ID,
        status="healthy",
        health_score=0.99,
        error_rate=0.01,
        avg_latency_ms=42.0,
        p95_latency_ms=120.0,
        request_count=1000,
    )

    assert result is not None
    assert isinstance(result, HealthCheck)
    assert result.status == "healthy"
    assert result.error_rate == 0.01
    assert result.request_count == 1000
    session.add.assert_called()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_record_health_check_missing_deployment() -> None:
    """Health check returns None if deployment doesn't exist."""
    session = _setup_get_session(None)

    result = await LifecycleManager.record_health_check(
        session, deployment_id=uuid4(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_record_health_check_degraded_records_event() -> None:
    """A non-healthy status triggers a health_changed lifecycle event."""
    record = _deployment(status="active", error_rate_threshold=0.10)
    session = _setup_get_session(record)

    with patch.object(
        LifecycleManager, "_record_event", new_callable=AsyncMock,
    ) as mock_event:
        await LifecycleManager.record_health_check(
            session,
            deployment_id=DEPLOY_ID,
            status="degraded",
            health_score=0.5,
            error_rate=0.03,
        )

        mock_event.assert_awaited_once()
        call_kwargs = mock_event.call_args.kwargs
        assert call_kwargs["event_type"] == "health_changed"
        assert call_kwargs["to_state"] == "degraded"


# ═══════════════════════════════════════════════════════════════════
# Auto-rollback on high error rate
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_auto_rollback_triggered_on_high_error_rate() -> None:
    """When error_rate exceeds threshold and status is active, auto-rollback fires."""
    record = _deployment(status="active", error_rate_threshold=0.05)
    session = _setup_get_session(record)

    with patch.object(
        LifecycleManager, "rollback", new_callable=AsyncMock,
    ) as mock_rollback:
        await LifecycleManager.record_health_check(
            session,
            deployment_id=DEPLOY_ID,
            status="unhealthy",
            error_rate=0.10,  # exceeds 0.05 threshold
        )

        mock_rollback.assert_awaited_once_with(
            session,
            DEPLOY_ID,
            reason="Auto-rollback: error rate 10.00% exceeds threshold 5.00%",
        )


@pytest.mark.asyncio
async def test_no_auto_rollback_when_below_threshold() -> None:
    """Error rate at or below threshold does not trigger auto-rollback."""
    record = _deployment(status="active", error_rate_threshold=0.05)
    session = _setup_get_session(record)

    with patch.object(
        LifecycleManager, "rollback", new_callable=AsyncMock,
    ) as mock_rollback:
        await LifecycleManager.record_health_check(
            session,
            deployment_id=DEPLOY_ID,
            status="healthy",
            error_rate=0.05,  # exactly at threshold — not exceeded
        )

        mock_rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_auto_rollback_when_not_active() -> None:
    """Auto-rollback only fires when deployment status is active."""
    record = _deployment(status="retired", error_rate_threshold=0.05)
    session = _setup_get_session(record)

    with patch.object(
        LifecycleManager, "rollback", new_callable=AsyncMock,
    ) as mock_rollback:
        await LifecycleManager.record_health_check(
            session,
            deployment_id=DEPLOY_ID,
            status="unhealthy",
            error_rate=0.50,  # way over threshold but deployment is retired
        )

        mock_rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_rollback_reason_contains_rates() -> None:
    """Auto-rollback reason message contains both error rate and threshold."""
    record = _deployment(status="active", error_rate_threshold=0.03)
    session = _setup_get_session(record)

    with patch.object(
        LifecycleManager, "rollback", new_callable=AsyncMock,
    ) as mock_rollback:
        await LifecycleManager.record_health_check(
            session,
            deployment_id=DEPLOY_ID,
            error_rate=0.08,
        )

        reason = mock_rollback.call_args.kwargs["reason"]
        assert "8.00%" in reason
        assert "3.00%" in reason


# ═══════════════════════════════════════════════════════════════════
# Health check details passthrough
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_health_check_stores_details() -> None:
    """Optional details dict is persisted on the HealthCheck."""
    record = _deployment(status="active")
    session = _setup_get_session(record)
    details = {"region": "us-east-1", "pod": "agent-abc-123"}

    result = await LifecycleManager.record_health_check(
        session,
        deployment_id=DEPLOY_ID,
        details=details,
    )

    assert result is not None
    assert result.details == details


@pytest.mark.asyncio
async def test_health_check_defaults_empty_details() -> None:
    """When no details provided, defaults to empty dict."""
    record = _deployment(status="active")
    session = _setup_get_session(record)

    result = await LifecycleManager.record_health_check(
        session, deployment_id=DEPLOY_ID,
    )

    assert result is not None
    assert result.details == {}
