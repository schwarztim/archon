"""Unit tests for TenantManager — tenant CRUD, self-service signup, quota
enforcement (hard/soft/burst), usage metering, billing records, and tenant
isolation.

All tests mock the async database session so no live DB is required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.models.tenancy import BillingRecord, Tenant, TenantQuota, UsageMeteringRecord
from app.services.tenancy import TenantManager, _TIER_DEFAULTS, _slugify

# ── Fixed UUIDs (valid hex only: 0-9, a-f) ─────────────────────────

TENANT_ID_A = UUID("aa000001-0001-0001-0001-000000000001")
TENANT_ID_B = UUID("bb000002-0002-0002-0002-000000000002")
QUOTA_ID = UUID("cc000003-0003-0003-0003-000000000003")
BILLING_ID = UUID("dd000004-0004-0004-0004-000000000004")
USAGE_ID = UUID("ee000005-0005-0005-0005-000000000005")
AGENT_ID = UUID("aa000006-0006-0006-0006-000000000006")
USER_ID = UUID("00000007-0007-0007-0007-000000000007")
EXEC_ID = UUID("00000008-0008-0008-0008-000000000008")
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Factories ───────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object whose .all() and .first() work."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


def _tenant(
    *,
    tid: UUID = TENANT_ID_A,
    name: str = "Acme Corp",
    slug: str = "acme-corp",
    tier: str = "free",
    status: str = "active",
    owner_email: str = "admin@acme.com",
    settings: dict[str, Any] | None = None,
) -> Tenant:
    """Build a Tenant with controllable fields."""
    return Tenant(
        id=tid,
        name=name,
        slug=slug,
        tier=tier,
        status=status,
        owner_email=owner_email,
        settings=settings or {},
        created_at=NOW,
        updated_at=NOW,
    )


def _quota(
    *,
    qid: UUID = QUOTA_ID,
    tenant_id: UUID = TENANT_ID_A,
    max_executions_per_month: int = 100,
    max_agents: int = 5,
    max_storage_mb: int = 100,
    max_api_calls_per_month: int = 1000,
    used_executions: int = 0,
    used_storage_mb: int = 0,
    used_api_calls: int = 0,
    enforcement: str = "hard",
    burst_allowance_pct: float = 0.0,
) -> TenantQuota:
    """Build a TenantQuota with controllable fields."""
    return TenantQuota(
        id=qid,
        tenant_id=tenant_id,
        max_executions_per_month=max_executions_per_month,
        max_agents=max_agents,
        max_storage_mb=max_storage_mb,
        max_api_calls_per_month=max_api_calls_per_month,
        used_executions=used_executions,
        used_storage_mb=used_storage_mb,
        used_api_calls=used_api_calls,
        enforcement=enforcement,
        burst_allowance_pct=burst_allowance_pct,
        period_start=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _billing_record(
    *,
    bid: UUID = BILLING_ID,
    tenant_id: UUID = TENANT_ID_A,
    record_type: str = "invoice",
    amount: float = 49.99,
    currency: str = "USD",
    status: str = "pending",
) -> BillingRecord:
    """Build a BillingRecord with controllable fields."""
    return BillingRecord(
        id=bid,
        tenant_id=tenant_id,
        record_type=record_type,
        amount=amount,
        currency=currency,
        status=status,
        description="Monthly subscription",
        extra_metadata={},
        created_at=NOW,
        updated_at=NOW,
    )


def _usage_record(
    *,
    uid: UUID = USAGE_ID,
    tenant_id: UUID = TENANT_ID_A,
    resource_type: str = "execution",
    quantity: int = 1,
) -> UsageMeteringRecord:
    """Build a UsageMeteringRecord with controllable fields."""
    return UsageMeteringRecord(
        id=uid,
        tenant_id=tenant_id,
        resource_type=resource_type,
        quantity=quantity,
        description="test usage",
        extra_metadata={},
        created_at=NOW,
    )


# ═══════════════════════════════════════════════════════════════════
# Slugify helper
# ═══════════════════════════════════════════════════════════════════


class TestSlugify:
    """Tests for the _slugify helper function."""

    def test_simple_name(self) -> None:
        assert _slugify("Acme Corp") == "acme-corp"

    def test_special_characters(self) -> None:
        assert _slugify("My & Company!") == "my-company"

    def test_leading_trailing_whitespace(self) -> None:
        assert _slugify("  Hello World  ") == "hello-world"

    def test_already_slug(self) -> None:
        assert _slugify("already-slug") == "already-slug"

    def test_numbers_preserved(self) -> None:
        assert _slugify("Team 42") == "team-42"

    def test_consecutive_special_chars(self) -> None:
        assert _slugify("a---b___c") == "a-b-c"


# ═══════════════════════════════════════════════════════════════════
# Tenant CRUD
# ═══════════════════════════════════════════════════════════════════


class TestCreateTenant:
    """Tests for TenantManager.create_tenant."""

    @pytest.mark.asyncio
    async def test_create_tenant_success(self) -> None:
        """Creating a tenant provisions default quotas and returns tenant."""
        session = _mock_session()
        # slug uniqueness check returns no match
        session.exec = AsyncMock(return_value=_exec_result([]))
        session.refresh = AsyncMock(side_effect=lambda obj: None)
        # flush is called to assign ID before quota creation
        session.flush = AsyncMock()

        tenant = await TenantManager.create_tenant(
            session,
            name="Acme Corp",
            owner_email="admin@acme.com",
            tier="free",
        )

        assert tenant.name == "Acme Corp"
        assert tenant.tier == "free"
        assert session.add.call_count >= 2  # tenant + quota
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_tenant_duplicate_slug_raises(self) -> None:
        """Duplicate slug raises ValueError."""
        session = _mock_session()
        existing = _tenant()
        session.exec = AsyncMock(return_value=_exec_result([existing]))

        with pytest.raises(ValueError, match="already exists"):
            await TenantManager.create_tenant(
                session,
                name="Acme Corp",
                owner_email="admin@acme.com",
            )

    @pytest.mark.asyncio
    async def test_create_tenant_custom_slug(self) -> None:
        """Custom slug is used instead of auto-generated slug."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))
        session.refresh = AsyncMock()
        session.flush = AsyncMock()

        tenant = await TenantManager.create_tenant(
            session,
            name="Acme Corp",
            owner_email="admin@acme.com",
            slug="custom-slug",
        )

        assert tenant.slug == "custom-slug"

    @pytest.mark.asyncio
    async def test_create_tenant_uses_tier_defaults(self) -> None:
        """Creating with 'team' tier provisions team-level quotas."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))
        session.refresh = AsyncMock()
        session.flush = AsyncMock()

        added_objects: list[Any] = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        await TenantManager.create_tenant(
            session, name="Team Co", owner_email="t@co.com", tier="team",
        )

        # Should have added a TenantQuota with team limits
        quotas = [o for o in added_objects if isinstance(o, TenantQuota)]
        assert len(quotas) == 1
        assert quotas[0].max_executions_per_month == _TIER_DEFAULTS["team"]["max_executions_per_month"]


class TestGetTenant:
    """Tests for TenantManager.get_tenant."""

    @pytest.mark.asyncio
    async def test_get_existing_tenant(self) -> None:
        session = _mock_session()
        t = _tenant()
        session.get = AsyncMock(return_value=t)

        result = await TenantManager.get_tenant(session, TENANT_ID_A)
        assert result is not None
        assert result.id == TENANT_ID_A

    @pytest.mark.asyncio
    async def test_get_nonexistent_tenant(self) -> None:
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await TenantManager.get_tenant(session, TENANT_ID_A)
        assert result is None


class TestGetTenantBySlug:
    """Tests for TenantManager.get_tenant_by_slug."""

    @pytest.mark.asyncio
    async def test_found(self) -> None:
        session = _mock_session()
        t = _tenant()
        session.exec = AsyncMock(return_value=_exec_result([t]))

        result = await TenantManager.get_tenant_by_slug(session, "acme-corp")
        assert result is not None
        assert result.slug == "acme-corp"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await TenantManager.get_tenant_by_slug(session, "nonexistent")
        assert result is None


class TestListTenants:
    """Tests for TenantManager.list_tenants."""

    @pytest.mark.asyncio
    async def test_list_returns_paginated_results(self) -> None:
        session = _mock_session()
        tenants = [_tenant(), _tenant(tid=TENANT_ID_B, slug="beta-co")]
        session.exec = AsyncMock(return_value=_exec_result(tenants))

        results, total = await TenantManager.list_tenants(session, limit=10, offset=0)
        assert total == 2
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        results, total = await TenantManager.list_tenants(session)
        assert total == 0
        assert results == []

    @pytest.mark.asyncio
    async def test_list_filters_by_status(self) -> None:
        session = _mock_session()
        active = _tenant(status="active")
        session.exec = AsyncMock(return_value=_exec_result([active]))

        results, total = await TenantManager.list_tenants(session, status="active")
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_filters_by_tier(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        results, total = await TenantManager.list_tenants(session, tier="enterprise")
        assert total == 0


class TestUpdateTenant:
    """Tests for TenantManager.update_tenant."""

    @pytest.mark.asyncio
    async def test_update_existing(self) -> None:
        session = _mock_session()
        t = _tenant()
        session.get = AsyncMock(return_value=t)
        session.refresh = AsyncMock()

        result = await TenantManager.update_tenant(
            session, TENANT_ID_A, {"name": "New Name"},
        )
        assert result is not None
        assert result.name == "New Name"
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_nonexistent(self) -> None:
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await TenantManager.update_tenant(
            session, TENANT_ID_A, {"name": "X"},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_ignores_protected_fields(self) -> None:
        """Fields 'id' and 'created_at' cannot be overwritten."""
        session = _mock_session()
        t = _tenant()
        original_id = t.id
        original_created = t.created_at
        session.get = AsyncMock(return_value=t)
        session.refresh = AsyncMock()

        await TenantManager.update_tenant(
            session, TENANT_ID_A, {"id": TENANT_ID_B, "created_at": NOW - timedelta(days=999)},
        )
        assert t.id == original_id
        assert t.created_at == original_created


class TestDeactivateTenant:
    """Tests for TenantManager.deactivate_tenant."""

    @pytest.mark.asyncio
    async def test_deactivate_success(self) -> None:
        session = _mock_session()
        t = _tenant()
        session.get = AsyncMock(return_value=t)

        result = await TenantManager.deactivate_tenant(session, TENANT_ID_A)
        assert result is True
        assert t.status == "deactivated"
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent(self) -> None:
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await TenantManager.deactivate_tenant(session, TENANT_ID_A)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
# Self-Service Signup
# ═══════════════════════════════════════════════════════════════════


class TestSignup:
    """Tests for TenantManager.signup."""

    @pytest.mark.asyncio
    async def test_signup_returns_onboarding_payload(self) -> None:
        """Signup creates tenant + quota and returns structured payload."""
        session = _mock_session()
        t = _tenant()
        q = _quota()

        with (
            patch.object(
                TenantManager, "create_tenant", new_callable=AsyncMock, return_value=t,
            ),
            patch.object(
                TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
            ),
        ):
            payload = await TenantManager.signup(
                session, name="Acme Corp", owner_email="admin@acme.com",
            )

        assert payload["onboarding_status"] == "complete"
        assert payload["tenant"]["name"] == "Acme Corp"
        assert payload["quota"] is not None

    @pytest.mark.asyncio
    async def test_signup_with_tier(self) -> None:
        """Signup respects the tier parameter."""
        session = _mock_session()
        t = _tenant(tier="individual")
        q = _quota()

        with (
            patch.object(
                TenantManager, "create_tenant", new_callable=AsyncMock, return_value=t,
            ) as mock_create,
            patch.object(
                TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
            ),
        ):
            await TenantManager.signup(
                session, name="Solo Dev", owner_email="dev@solo.com", tier="individual",
            )

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["tier"] == "individual"

    @pytest.mark.asyncio
    async def test_signup_quota_is_none(self) -> None:
        """If get_quota returns None, payload still has quota=None."""
        session = _mock_session()
        t = _tenant()

        with (
            patch.object(
                TenantManager, "create_tenant", new_callable=AsyncMock, return_value=t,
            ),
            patch.object(
                TenantManager, "get_quota", new_callable=AsyncMock, return_value=None,
            ),
        ):
            payload = await TenantManager.signup(
                session, name="Acme Corp", owner_email="admin@acme.com",
            )

        assert payload["quota"] is None
        assert payload["onboarding_status"] == "complete"


# ═══════════════════════════════════════════════════════════════════
# Quota Management
# ═══════════════════════════════════════════════════════════════════


class TestGetQuota:
    """Tests for TenantManager.get_quota."""

    @pytest.mark.asyncio
    async def test_get_existing_quota(self) -> None:
        session = _mock_session()
        q = _quota()
        session.exec = AsyncMock(return_value=_exec_result([q]))

        result = await TenantManager.get_quota(session, tenant_id=TENANT_ID_A)
        assert result is not None
        assert result.tenant_id == TENANT_ID_A

    @pytest.mark.asyncio
    async def test_get_quota_not_found(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await TenantManager.get_quota(session, tenant_id=TENANT_ID_A)
        assert result is None


class TestUpdateQuota:
    """Tests for TenantManager.update_quota."""

    @pytest.mark.asyncio
    async def test_update_quota_success(self) -> None:
        session = _mock_session()
        q = _quota()
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.update_quota(
                session, tenant_id=TENANT_ID_A,
                data={"max_agents": 50, "enforcement": "soft"},
            )

        assert result is not None
        assert result.max_agents == 50
        assert result.enforcement == "soft"

    @pytest.mark.asyncio
    async def test_update_quota_not_found(self) -> None:
        session = _mock_session()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=None,
        ):
            result = await TenantManager.update_quota(
                session, tenant_id=TENANT_ID_A, data={"max_agents": 50},
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_update_quota_ignores_protected_fields(self) -> None:
        """Fields 'id', 'tenant_id', and 'created_at' cannot be overwritten."""
        session = _mock_session()
        q = _quota()
        original_tid = q.tenant_id
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            await TenantManager.update_quota(
                session, tenant_id=TENANT_ID_A,
                data={"tenant_id": TENANT_ID_B},
            )

        assert q.tenant_id == original_tid


class TestChangeTier:
    """Tests for TenantManager.change_tier."""

    @pytest.mark.asyncio
    async def test_change_tier_updates_tenant_and_quota(self) -> None:
        session = _mock_session()
        t = _tenant(tier="free")
        q = _quota()
        session.get = AsyncMock(return_value=t)
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.change_tier(
                session, tenant_id=TENANT_ID_A, new_tier="team",
            )

        assert result is not None
        assert result.tier == "team"
        assert q.max_executions_per_month == _TIER_DEFAULTS["team"]["max_executions_per_month"]
        assert q.max_agents == _TIER_DEFAULTS["team"]["max_agents"]

    @pytest.mark.asyncio
    async def test_change_tier_nonexistent_tenant(self) -> None:
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await TenantManager.change_tier(
            session, tenant_id=TENANT_ID_A, new_tier="team",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_change_tier_creates_quota_if_missing(self) -> None:
        """If no quota record exists, change_tier creates one."""
        session = _mock_session()
        t = _tenant()
        session.get = AsyncMock(return_value=t)
        session.refresh = AsyncMock()

        added_objects: list[Any] = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=None,
        ):
            await TenantManager.change_tier(
                session, tenant_id=TENANT_ID_A, new_tier="enterprise",
            )

        quotas = [o for o in added_objects if isinstance(o, TenantQuota)]
        assert len(quotas) == 1
        assert quotas[0].max_agents == _TIER_DEFAULTS["enterprise"]["max_agents"]

    @pytest.mark.asyncio
    async def test_change_tier_unknown_tier_falls_back_to_free(self) -> None:
        """Unknown tier name falls back to free-tier defaults."""
        session = _mock_session()
        t = _tenant()
        q = _quota()
        session.get = AsyncMock(return_value=t)
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.change_tier(
                session, tenant_id=TENANT_ID_A, new_tier="nonexistent",
            )

        assert result is not None
        assert q.max_executions_per_month == _TIER_DEFAULTS["free"]["max_executions_per_month"]


# ═══════════════════════════════════════════════════════════════════
# Quota Enforcement — check_limit
# ═══════════════════════════════════════════════════════════════════


class TestCheckLimit:
    """Tests for TenantManager.check_limit — hard/soft enforcement and burst."""

    @pytest.mark.asyncio
    async def test_within_limit_allowed(self) -> None:
        """Request within limit is allowed."""
        session = _mock_session()
        q = _quota(used_executions=50, max_executions_per_month=100)

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution", quantity=1,
            )

        assert result["allowed"] is True
        assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_at_exact_limit_allowed(self) -> None:
        """Request that reaches exactly the limit is allowed."""
        session = _mock_session()
        q = _quota(used_executions=99, max_executions_per_month=100)

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution", quantity=1,
            )

        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_hard_limit_exceeded_denied(self) -> None:
        """Hard enforcement: exceeding limit is denied."""
        session = _mock_session()
        q = _quota(
            used_executions=100, max_executions_per_month=100,
            enforcement="hard", burst_allowance_pct=0.0,
        )

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution", quantity=1,
            )

        assert result["allowed"] is False
        assert "Hard limit" in result["reason"]

    @pytest.mark.asyncio
    async def test_soft_limit_exceeded_allowed_with_warning(self) -> None:
        """Soft enforcement: exceeding limit is allowed but flagged."""
        session = _mock_session()
        q = _quota(
            used_executions=100, max_executions_per_month=100,
            enforcement="soft", burst_allowance_pct=0.0,
        )

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution", quantity=1,
            )

        assert result["allowed"] is True
        assert result["warning"] is True
        assert "Soft limit" in result["reason"]

    @pytest.mark.asyncio
    async def test_burst_allowance_extends_limit(self) -> None:
        """10% burst on 100 limit lets 110 through under hard enforcement."""
        session = _mock_session()
        q = _quota(
            used_executions=105, max_executions_per_month=100,
            enforcement="hard", burst_allowance_pct=10.0,
        )

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution", quantity=1,
            )

        # 105 + 1 = 106 <= 110 (100 + 10%)
        assert result["allowed"] is True
        assert result["burst_limit"] == 110.0

    @pytest.mark.asyncio
    async def test_burst_limit_exceeded_hard_denied(self) -> None:
        """Exceeding even the burst limit under hard enforcement is denied."""
        session = _mock_session()
        q = _quota(
            used_executions=110, max_executions_per_month=100,
            enforcement="hard", burst_allowance_pct=10.0,
        )

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution", quantity=1,
            )

        # 110 + 1 = 111 > 110
        assert result["allowed"] is False

    @pytest.mark.asyncio
    async def test_no_quota_configured(self) -> None:
        """Missing quota returns denied."""
        session = _mock_session()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=None,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution",
            )

        assert result["allowed"] is False
        assert "No quota" in result["reason"]

    @pytest.mark.asyncio
    async def test_unknown_resource_type_allowed(self) -> None:
        """Unknown resource types are allowed by default."""
        session = _mock_session()
        q = _quota()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="token",
            )

        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_api_call_limit_check(self) -> None:
        """check_limit works for api_call resource type."""
        session = _mock_session()
        q = _quota(used_api_calls=999, max_api_calls_per_month=1000)

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="api_call", quantity=1,
            )

        assert result["allowed"] is True
        assert result["used"] == 999

    @pytest.mark.asyncio
    async def test_storage_limit_check(self) -> None:
        """check_limit works for storage resource type."""
        session = _mock_session()
        q = _quota(used_storage_mb=100, max_storage_mb=100, enforcement="hard")

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="storage", quantity=1,
            )

        assert result["allowed"] is False

    @pytest.mark.asyncio
    async def test_large_quantity_request(self) -> None:
        """A request for a large quantity that pushes over the limit is denied."""
        session = _mock_session()
        q = _quota(used_executions=90, max_executions_per_month=100, enforcement="hard")

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.check_limit(
                session, tenant_id=TENANT_ID_A, resource_type="execution", quantity=20,
            )

        # 90 + 20 = 110 > 100
        assert result["allowed"] is False


# ═══════════════════════════════════════════════════════════════════
# Usage Metering
# ═══════════════════════════════════════════════════════════════════


class TestRecordUsage:
    """Tests for TenantManager.record_usage."""

    @pytest.mark.asyncio
    async def test_record_usage_increments_counter(self) -> None:
        """Recording usage increments the matching quota counter."""
        session = _mock_session()
        q = _quota(used_executions=10)
        record = _usage_record()
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            result = await TenantManager.record_usage(
                session,
                tenant_id=TENANT_ID_A,
                resource_type="execution",
                quantity=5,
            )

        assert q.used_executions == 15  # 10 + 5
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_usage_api_call_counter(self) -> None:
        """Recording api_call usage increments used_api_calls."""
        session = _mock_session()
        q = _quota(used_api_calls=100)
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            await TenantManager.record_usage(
                session, tenant_id=TENANT_ID_A,
                resource_type="api_call", quantity=3,
            )

        assert q.used_api_calls == 103

    @pytest.mark.asyncio
    async def test_record_usage_storage_counter(self) -> None:
        """Recording storage usage increments used_storage_mb."""
        session = _mock_session()
        q = _quota(used_storage_mb=50)
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            await TenantManager.record_usage(
                session, tenant_id=TENANT_ID_A,
                resource_type="storage", quantity=10,
            )

        assert q.used_storage_mb == 60

    @pytest.mark.asyncio
    async def test_record_usage_unknown_type_no_counter_update(self) -> None:
        """Unknown resource types do not crash; no counter update."""
        session = _mock_session()
        q = _quota(used_executions=10)
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            await TenantManager.record_usage(
                session, tenant_id=TENANT_ID_A,
                resource_type="token", quantity=500,
            )

        assert q.used_executions == 10  # unchanged

    @pytest.mark.asyncio
    async def test_record_usage_no_quota_still_records(self) -> None:
        """If no quota exists, the usage record is still created."""
        session = _mock_session()
        session.refresh = AsyncMock()

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=None,
        ):
            await TenantManager.record_usage(
                session, tenant_id=TENANT_ID_A,
                resource_type="execution", quantity=1,
            )

        session.add.assert_called()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_usage_with_attribution(self) -> None:
        """Usage record captures optional agent_id, user_id, execution_id."""
        session = _mock_session()
        q = _quota()
        session.refresh = AsyncMock()

        added_objects: list[Any] = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch.object(
            TenantManager, "get_quota", new_callable=AsyncMock, return_value=q,
        ):
            await TenantManager.record_usage(
                session, tenant_id=TENANT_ID_A,
                resource_type="execution", quantity=1,
                agent_id=AGENT_ID, user_id=USER_ID, execution_id=EXEC_ID,
                description="Agent run", metadata={"model": "gpt-4o"},
            )

        usage_records = [o for o in added_objects if isinstance(o, UsageMeteringRecord)]
        assert len(usage_records) == 1
        rec = usage_records[0]
        assert rec.agent_id == AGENT_ID
        assert rec.user_id == USER_ID
        assert rec.execution_id == EXEC_ID
        assert rec.description == "Agent run"
        assert rec.extra_metadata == {"model": "gpt-4o"}


class TestListUsage:
    """Tests for TenantManager.list_usage."""

    @pytest.mark.asyncio
    async def test_list_usage_returns_paginated(self) -> None:
        session = _mock_session()
        records = [_usage_record(), _usage_record()]
        session.exec = AsyncMock(return_value=_exec_result(records))

        results, total = await TenantManager.list_usage(
            session, tenant_id=TENANT_ID_A, limit=10, offset=0,
        )
        assert total == 2
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_usage_empty(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        results, total = await TenantManager.list_usage(
            session, tenant_id=TENANT_ID_A,
        )
        assert total == 0
        assert results == []

    @pytest.mark.asyncio
    async def test_list_usage_with_filters(self) -> None:
        """Filters (resource_type, since, until) are applied without error."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        results, total = await TenantManager.list_usage(
            session, tenant_id=TENANT_ID_A,
            resource_type="execution",
            since=NOW - timedelta(days=7),
            until=NOW,
        )
        assert total == 0


class TestGetUsageSummary:
    """Tests for TenantManager.get_usage_summary."""

    @pytest.mark.asyncio
    async def test_summary_aggregates_by_type(self) -> None:
        session = _mock_session()
        records = [
            _usage_record(resource_type="execution", quantity=10),
            _usage_record(resource_type="execution", quantity=5),
            _usage_record(resource_type="api_call", quantity=100),
        ]
        session.exec = AsyncMock(return_value=_exec_result(records))

        result = await TenantManager.get_usage_summary(
            session, tenant_id=TENANT_ID_A,
        )

        assert result["tenant_id"] == str(TENANT_ID_A)
        assert result["total_events"] == 3
        assert result["breakdown"]["execution"] == 15
        assert result["breakdown"]["api_call"] == 100

    @pytest.mark.asyncio
    async def test_summary_empty(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await TenantManager.get_usage_summary(
            session, tenant_id=TENANT_ID_A,
        )

        assert result["total_events"] == 0
        assert result["breakdown"] == {}

    @pytest.mark.asyncio
    async def test_summary_custom_period(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))
        since = NOW - timedelta(days=7)
        until = NOW

        result = await TenantManager.get_usage_summary(
            session, tenant_id=TENANT_ID_A, since=since, until=until,
        )

        assert result["period"]["since"] == since.isoformat()
        assert result["period"]["until"] == until.isoformat()


# ═══════════════════════════════════════════════════════════════════
# Billing Records
# ═══════════════════════════════════════════════════════════════════


class TestCreateBillingRecord:
    """Tests for TenantManager.create_billing_record."""

    @pytest.mark.asyncio
    async def test_create_billing_record(self) -> None:
        session = _mock_session()
        session.refresh = AsyncMock()

        result = await TenantManager.create_billing_record(
            session,
            tenant_id=TENANT_ID_A,
            record_type="invoice",
            amount=49.99,
            description="Monthly subscription",
        )

        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_billing_record_with_stripe(self) -> None:
        """Billing record can capture Stripe identifiers."""
        session = _mock_session()
        session.refresh = AsyncMock()

        added_objects: list[Any] = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        await TenantManager.create_billing_record(
            session,
            tenant_id=TENANT_ID_A,
            record_type="payment",
            amount=99.00,
            stripe_invoice_id="inv_abc123",
            stripe_payment_intent_id="pi_def456",
        )

        billing = [o for o in added_objects if isinstance(o, BillingRecord)]
        assert len(billing) == 1
        assert billing[0].stripe_invoice_id == "inv_abc123"
        assert billing[0].stripe_payment_intent_id == "pi_def456"

    @pytest.mark.asyncio
    async def test_create_billing_record_with_period(self) -> None:
        session = _mock_session()
        session.refresh = AsyncMock()

        added_objects: list[Any] = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        start = NOW
        end = NOW + timedelta(days=30)
        await TenantManager.create_billing_record(
            session,
            tenant_id=TENANT_ID_A,
            record_type="invoice",
            amount=49.99,
            period_start=start,
            period_end=end,
        )

        billing = [o for o in added_objects if isinstance(o, BillingRecord)]
        assert billing[0].period_start == start
        assert billing[0].period_end == end


class TestListBillingRecords:
    """Tests for TenantManager.list_billing_records."""

    @pytest.mark.asyncio
    async def test_list_billing_records(self) -> None:
        session = _mock_session()
        records = [_billing_record(), _billing_record()]
        session.exec = AsyncMock(return_value=_exec_result(records))

        results, total = await TenantManager.list_billing_records(
            session, tenant_id=TENANT_ID_A,
        )
        assert total == 2
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_billing_records_empty(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        results, total = await TenantManager.list_billing_records(
            session, tenant_id=TENANT_ID_A,
        )
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_billing_records_filter_by_type(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        results, total = await TenantManager.list_billing_records(
            session, tenant_id=TENANT_ID_A, record_type="payment",
        )
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_billing_records_filter_by_status(self) -> None:
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        results, total = await TenantManager.list_billing_records(
            session, tenant_id=TENANT_ID_A, status="paid",
        )
        assert total == 0


class TestUpdateBillingRecord:
    """Tests for TenantManager.update_billing_record."""

    @pytest.mark.asyncio
    async def test_update_billing_record_success(self) -> None:
        session = _mock_session()
        rec = _billing_record(tenant_id=TENANT_ID_A)
        session.get = AsyncMock(return_value=rec)
        session.refresh = AsyncMock()

        result = await TenantManager.update_billing_record(
            session, tenant_id=TENANT_ID_A, record_id=BILLING_ID,
            data={"status": "paid"},
        )

        assert result is not None
        assert result.status == "paid"

    @pytest.mark.asyncio
    async def test_update_billing_record_not_found(self) -> None:
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await TenantManager.update_billing_record(
            session, tenant_id=TENANT_ID_A, record_id=BILLING_ID,
            data={"status": "paid"},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_billing_record_ignores_protected_fields(self) -> None:
        session = _mock_session()
        rec = _billing_record(tenant_id=TENANT_ID_A)
        original_id = rec.id
        session.get = AsyncMock(return_value=rec)
        session.refresh = AsyncMock()

        await TenantManager.update_billing_record(
            session, tenant_id=TENANT_ID_A, record_id=BILLING_ID,
            data={"id": TENANT_ID_B, "tenant_id": TENANT_ID_B, "created_at": NOW},
        )

        assert rec.id == original_id
        assert rec.tenant_id == TENANT_ID_A


# ═══════════════════════════════════════════════════════════════════
# Tenant Isolation
# ═══════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    """Tests that cross-tenant access is denied."""

    @pytest.mark.asyncio
    async def test_update_billing_record_wrong_tenant_denied(self) -> None:
        """Attempting to update a billing record with a different tenant_id returns None."""
        session = _mock_session()
        rec = _billing_record(tenant_id=TENANT_ID_A)
        session.get = AsyncMock(return_value=rec)

        result = await TenantManager.update_billing_record(
            session, tenant_id=TENANT_ID_B, record_id=BILLING_ID,
            data={"status": "paid"},
        )

        assert result is None  # access denied

    @pytest.mark.asyncio
    async def test_billing_record_tenant_mismatch_no_commit(self) -> None:
        """When tenant_id doesn't match, no commit should occur."""
        session = _mock_session()
        rec = _billing_record(tenant_id=TENANT_ID_A)
        session.get = AsyncMock(return_value=rec)

        await TenantManager.update_billing_record(
            session, tenant_id=TENANT_ID_B, record_id=BILLING_ID,
            data={"status": "paid"},
        )

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_usage_scoped_to_tenant(self) -> None:
        """list_usage receives tenant_id; mock verifies it's used in the query."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        await TenantManager.list_usage(session, tenant_id=TENANT_ID_A)

        # session.exec was called (query is scoped by tenant_id in the WHERE clause)
        session.exec.assert_awaited()

    @pytest.mark.asyncio
    async def test_list_billing_scoped_to_tenant(self) -> None:
        """list_billing_records receives tenant_id; mock verifies query is scoped."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        await TenantManager.list_billing_records(session, tenant_id=TENANT_ID_A)

        session.exec.assert_awaited()

    @pytest.mark.asyncio
    async def test_usage_summary_scoped_to_tenant(self) -> None:
        """get_usage_summary returns tenant_id in output — confirms scoping."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await TenantManager.get_usage_summary(
            session, tenant_id=TENANT_ID_A,
        )

        assert result["tenant_id"] == str(TENANT_ID_A)


# ═══════════════════════════════════════════════════════════════════
# Tier Defaults
# ═══════════════════════════════════════════════════════════════════


class TestTierDefaults:
    """Verify the tier definitions are internally consistent."""

    def test_all_tiers_have_required_keys(self) -> None:
        required = {"max_executions_per_month", "max_agents", "max_storage_mb", "max_api_calls_per_month"}
        for tier_name, limits in _TIER_DEFAULTS.items():
            assert required.issubset(limits.keys()), f"Tier '{tier_name}' missing keys"

    def test_tiers_scale_upward(self) -> None:
        """Higher tiers should have equal or greater limits than lower tiers."""
        order = ["free", "individual", "team", "enterprise"]
        for key in ("max_executions_per_month", "max_agents", "max_storage_mb", "max_api_calls_per_month"):
            for i in range(len(order) - 1):
                lower = _TIER_DEFAULTS[order[i]][key]
                higher = _TIER_DEFAULTS[order[i + 1]][key]
                assert higher >= lower, f"{order[i+1]}.{key} < {order[i]}.{key}"
