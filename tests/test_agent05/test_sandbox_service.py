"""Tests for the enterprise SandboxService.

Covers create_sandbox, execute_in_sandbox, destroy_sandbox,
arena_compare, run_benchmark, tenant isolation, cost guardrails,
and mocked SecretsManager / DB interactions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser, DynamicCredential
from app.models.sandbox import (
    ArenaConfig,
    BenchmarkSet,
    BenchmarkTestCase,
    ExecutionStatus,
    NetworkPolicy,
    ResourceLimits,
    SandboxConfig,
    SandboxStatus,
    ScoringRubric,
    StatisticalMethod,
)
from app.services.sandbox_service import SandboxService


# ── Fixtures ────────────────────────────────────────────────────────


def _make_user(
    tenant_id: str = "tenant-1",
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(uuid4()),
        email="dev@example.com",
        tenant_id=tenant_id,
        roles=roles or ["admin"],
        permissions=permissions or [],
    )


def _make_config(**overrides: Any) -> SandboxConfig:
    defaults: dict[str, Any] = {
        "resource_limits": ResourceLimits(),
        "ttl_seconds": 3600,
        "network_policy": NetworkPolicy.RESTRICTED,
    }
    defaults.update(overrides)
    return SandboxConfig(**defaults)


def _mock_secrets_manager() -> AsyncMock:
    sm = AsyncMock()
    sm.get_dynamic_credential = AsyncMock(
        return_value=DynamicCredential(
            username="sandbox-user",
            lease_id="lease-abc",
            lease_duration=3600,
            renewable=False,
            **{"password": "dynamic-tok"},
        )
    )
    return sm


@pytest.fixture()
def svc() -> SandboxService:
    return SandboxService()


@pytest.fixture()
def user() -> AuthenticatedUser:
    return _make_user()


@pytest.fixture()
def config() -> SandboxConfig:
    return _make_config()


# ── create_sandbox ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_sandbox_success(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Sandbox is created with correct tenant and status."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    assert sandbox.tenant_id == "tenant-1"
    assert sandbox.status == SandboxStatus.READY
    assert sandbox.created_by == user.id
    assert sandbox.expires_at is not None


@pytest.mark.asyncio
async def test_create_sandbox_rbac_denied(svc: SandboxService, config: SandboxConfig) -> None:
    """Users without sandbox:create permission are rejected."""
    viewer = _make_user(roles=["viewer"])
    with pytest.raises(PermissionError, match="sandbox:create"):
        await svc.create_sandbox("tenant-1", viewer, config)


@pytest.mark.asyncio
async def test_create_sandbox_ttl_sets_expiry(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """expires_at is set to now + ttl_seconds."""
    cfg = _make_config(ttl_seconds=120)
    sandbox = await svc.create_sandbox("tenant-1", user, cfg)
    delta = sandbox.expires_at - sandbox.created_at
    assert abs(delta.total_seconds() - 120) < 2


# ── execute_in_sandbox ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_in_sandbox_success(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Execution completes and records output."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    sm = _mock_secrets_manager()
    execution = await svc.execute_in_sandbox(
        sandbox.id, "tenant-1", uuid4(), {"key": "val"}, user=user, secrets_manager=sm,
    )
    assert execution.status == ExecutionStatus.COMPLETED
    assert execution.cost > 0
    assert execution.output_data is not None


@pytest.mark.asyncio
async def test_execute_in_sandbox_tenant_mismatch(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Access denied when tenant_id does not match."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    with pytest.raises(ValueError, match="not found or access denied"):
        await svc.execute_in_sandbox(sandbox.id, "tenant-999", uuid4(), {})


@pytest.mark.asyncio
async def test_execute_in_sandbox_nonexistent(svc: SandboxService) -> None:
    """ValueError raised for a sandbox that doesn't exist."""
    with pytest.raises(ValueError, match="not found or access denied"):
        await svc.execute_in_sandbox(uuid4(), "tenant-1", uuid4(), {})


@pytest.mark.asyncio
async def test_execute_in_sandbox_destroyed(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Executing in a destroyed sandbox raises ValueError."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    await svc.destroy_sandbox(sandbox.id, "tenant-1", user)
    with pytest.raises(ValueError, match="not found"):
        await svc.execute_in_sandbox(sandbox.id, "tenant-1", uuid4(), {})


@pytest.mark.asyncio
async def test_execute_in_sandbox_expired(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """Executing in an expired sandbox raises ValueError."""
    cfg = _make_config(ttl_seconds=60)
    sandbox = await svc.create_sandbox("tenant-1", user, cfg)
    # Force expiry
    sandbox.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
    svc._sandboxes[sandbox.id] = sandbox

    with pytest.raises(ValueError, match="expired"):
        await svc.execute_in_sandbox(sandbox.id, "tenant-1", uuid4(), {})


@pytest.mark.asyncio
async def test_execute_dynamic_credential_issued(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Dynamic credentials are issued and lease tracked."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    sm = _mock_secrets_manager()
    await svc.execute_in_sandbox(
        sandbox.id, "tenant-1", uuid4(), {"x": 1}, user=user, secrets_manager=sm,
    )
    sm.get_dynamic_credential.assert_awaited_once()
    refreshed = await svc.get_sandbox(sandbox.id, "tenant-1")
    assert "lease-abc" in refreshed.credential_lease_ids


@pytest.mark.asyncio
async def test_execute_dynamic_credential_failure_continues(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Execution proceeds even if dynamic credential issuance fails."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    sm = AsyncMock()
    sm.get_dynamic_credential = AsyncMock(side_effect=RuntimeError("vault down"))
    execution = await svc.execute_in_sandbox(
        sandbox.id, "tenant-1", uuid4(), {"a": 1}, user=user, secrets_manager=sm,
    )
    assert execution.status == ExecutionStatus.COMPLETED


# ── Cost guardrails ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_cost_guardrail_exceeded(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """Execution aborted when cost exceeds budget."""
    cfg = _make_config(resource_limits=ResourceLimits(max_cost_usd=0.01))
    sandbox = await svc.create_sandbox("tenant-1", user, cfg)
    big_input = {"data": "x" * 50_000}
    execution = await svc.execute_in_sandbox(
        sandbox.id, "tenant-1", uuid4(), big_input, user=user,
    )
    assert execution.status == ExecutionStatus.COST_LIMIT
    assert "budget exceeded" in execution.output_data["error"]


# ── destroy_sandbox ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_destroy_sandbox_success(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Sandbox is removed after destroy."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    result = await svc.destroy_sandbox(sandbox.id, "tenant-1", user)
    assert result is True
    assert await svc.get_sandbox(sandbox.id, "tenant-1") is None


@pytest.mark.asyncio
async def test_destroy_sandbox_rbac_denied(
    svc: SandboxService, config: SandboxConfig,
) -> None:
    """Users without sandbox:delete permission are rejected."""
    admin = _make_user(roles=["admin"])
    sandbox = await svc.create_sandbox("tenant-1", admin, config)
    viewer = _make_user(roles=["viewer"])
    with pytest.raises(PermissionError, match="sandbox:delete"):
        await svc.destroy_sandbox(sandbox.id, "tenant-1", viewer)


@pytest.mark.asyncio
async def test_destroy_sandbox_wrong_tenant(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Destroy returns False when tenant doesn't match."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    result = await svc.destroy_sandbox(sandbox.id, "tenant-999", user)
    assert result is False


@pytest.mark.asyncio
async def test_destroy_revokes_leases(
    svc: SandboxService, user: AuthenticatedUser, config: SandboxConfig,
) -> None:
    """Destroying a sandbox revokes dynamic credential leases."""
    sandbox = await svc.create_sandbox("tenant-1", user, config)
    sm = _mock_secrets_manager()
    await svc.execute_in_sandbox(
        sandbox.id, "tenant-1", uuid4(), {"k": "v"}, user=user, secrets_manager=sm,
    )
    result = await svc.destroy_sandbox(sandbox.id, "tenant-1", user, secrets_manager=sm)
    assert result is True


# ── Tenant isolation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_list(svc: SandboxService, config: SandboxConfig) -> None:
    """list_sandboxes only returns sandboxes for the requested tenant."""
    u1 = _make_user(tenant_id="t1")
    u2 = _make_user(tenant_id="t2")
    await svc.create_sandbox("t1", u1, config)
    await svc.create_sandbox("t2", u2, config)
    t1_list, t1_total = await svc.list_sandboxes("t1")
    t2_list, t2_total = await svc.list_sandboxes("t2")
    assert t1_total == 1
    assert t2_total == 1
    assert t1_list[0].tenant_id == "t1"
    assert t2_list[0].tenant_id == "t2"


@pytest.mark.asyncio
async def test_tenant_isolation_get(svc: SandboxService, config: SandboxConfig) -> None:
    """get_sandbox denies cross-tenant access."""
    u1 = _make_user(tenant_id="t1")
    sandbox = await svc.create_sandbox("t1", u1, config)
    assert await svc.get_sandbox(sandbox.id, "t2") is None


# ── arena_compare ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_arena_compare_returns_winner(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """Arena comparison returns a winner among agents."""
    agents = [uuid4(), uuid4()]
    cases = [{"name": "case1", "input": "hello"}]
    result = await svc.arena_compare("tenant-1", user, agents, cases)
    assert result.winner in agents
    assert result.confidence_score >= 0
    assert len(result.results_per_agent) == 2


@pytest.mark.asyncio
async def test_arena_compare_requires_two_agents(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """Arena raises ValueError with fewer than 2 agents."""
    with pytest.raises(ValueError, match="at least 2"):
        await svc.arena_compare("tenant-1", user, [uuid4()], [{"name": "c1"}])


@pytest.mark.asyncio
async def test_arena_compare_rbac_denied(svc: SandboxService) -> None:
    """Viewers cannot run arena comparisons."""
    viewer = _make_user(roles=["viewer"])
    with pytest.raises(PermissionError, match="sandbox:execute"):
        await svc.arena_compare("t1", viewer, [uuid4(), uuid4()], [{"n": "c1"}])


@pytest.mark.asyncio
async def test_arena_compare_custom_config(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """Arena respects custom statistical method from config."""
    agents = [uuid4(), uuid4()]
    cases = [{"name": "c1"}, {"name": "c2"}]
    from app.models.sandbox import ArenaTestCase
    cfg = ArenaConfig(
        agent_ids=agents,
        test_cases=[ArenaTestCase(name="t1")],
        statistical_method=StatisticalMethod.BOOTSTRAP,
    )
    result = await svc.arena_compare("tenant-1", user, agents, cases, config=cfg)
    assert result.statistical_method == StatisticalMethod.BOOTSTRAP


# ── run_benchmark ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_benchmark_empty_set(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """Benchmark with empty test set returns zero scores."""
    result = await svc.run_benchmark("tenant-1", user, uuid4(), uuid4())
    assert result.total_cost == 0
    assert result.total_duration_ms == 0
    assert "composite" in result.scores


@pytest.mark.asyncio
async def test_run_benchmark_with_cases(
    svc: SandboxService, user: AuthenticatedUser,
) -> None:
    """Benchmark with test cases produces scored results."""
    bench_id = uuid4()
    bench = BenchmarkSet(
        id=bench_id,
        name="eval-v1",
        test_cases=[
            BenchmarkTestCase(name="tc1", input_data={"q": "hello"}),
            BenchmarkTestCase(name="tc2", input_data={"q": "world"}),
        ],
        scoring_rubric=ScoringRubric(),
    )
    svc._benchmark_sets[bench_id] = bench
    result = await svc.run_benchmark("tenant-1", user, uuid4(), bench_id)
    assert result.total_cost > 0
    assert len(result.test_results) == 2
    assert result.scores["accuracy"] > 0


@pytest.mark.asyncio
async def test_run_benchmark_rbac_denied(svc: SandboxService) -> None:
    """Viewers cannot run benchmarks."""
    viewer = _make_user(roles=["viewer"])
    with pytest.raises(PermissionError, match="sandbox:execute"):
        await svc.run_benchmark("t1", viewer, uuid4(), uuid4())


# ── Legacy session API ──────────────────────────────────────────────


def test_legacy_create_and_get_session(svc: SandboxService) -> None:
    """Legacy create_session/get_session round-trip."""
    session = svc.create_session()
    assert session.status == SandboxStatus.READY
    fetched = svc.get_session(session.id)
    assert fetched is not None
    assert fetched.id == session.id


def test_legacy_destroy_session(svc: SandboxService) -> None:
    """Legacy destroy_session removes the session."""
    session = svc.create_session()
    assert svc.destroy_session(session.id) is True
    assert svc.get_session(session.id) is None


def test_legacy_destroy_nonexistent(svc: SandboxService) -> None:
    """Legacy destroy_session returns False for unknown IDs."""
    assert svc.destroy_session(uuid4()) is False


def test_legacy_list_sessions_paginated(svc: SandboxService) -> None:
    """Legacy list_sessions supports limit/offset pagination."""
    for _ in range(5):
        svc.create_session()
    page, total = svc.list_sessions(limit=2, offset=1)
    assert total == 5
    assert len(page) == 2
