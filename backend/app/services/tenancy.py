"""Multi-tenant manager — tenant lifecycle, quota enforcement, usage metering, and billing."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.tenancy import BillingRecord, Tenant, TenantQuota, UsageMeteringRecord
from app.utils.time import utcnow as _utcnow


# ── Default tier definitions ────────────────────────────────────────

_TIER_DEFAULTS: dict[str, dict[str, int]] = {
    "free": {
        "max_executions_per_month": 100,
        "max_agents": 5,
        "max_storage_mb": 100,
        "max_api_calls_per_month": 1_000,
    },
    "individual": {
        "max_executions_per_month": 1_000,
        "max_agents": 25,
        "max_storage_mb": 1_024,
        "max_api_calls_per_month": 10_000,
    },
    "team": {
        "max_executions_per_month": 10_000,
        "max_agents": 100,
        "max_storage_mb": 10_240,
        "max_api_calls_per_month": 100_000,
    },
    "enterprise": {
        "max_executions_per_month": 1_000_000,
        "max_agents": 10_000,
        "max_storage_mb": 1_048_576,
        "max_api_calls_per_month": 10_000_000,
    },
}


def _slugify(name: str) -> str:
    """Convert a tenant name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


class TenantManager:
    """Manages tenant lifecycle, quotas, usage metering, and billing.

    All methods are async-safe static methods following the CostEngine pattern.
    Tenant isolation is enforced by requiring tenant_id on every operation.
    """

    # ── Tenant CRUD ─────────────────────────────────────────────────

    @staticmethod
    async def create_tenant(
        session: AsyncSession,
        *,
        name: str,
        owner_email: str,
        tier: str = "free",
        slug: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Tenant:
        """Create a new tenant with default quotas for the chosen tier."""
        if slug is None:
            slug = _slugify(name)

        # Check slug uniqueness
        existing = await session.exec(
            select(Tenant).where(Tenant.slug == slug).limit(1)
        )
        if existing.first() is not None:
            raise ValueError(f"Tenant slug '{slug}' already exists")

        tenant = Tenant(
            name=name,
            slug=slug,
            tier=tier,
            owner_email=owner_email,
            settings=settings or {},
        )
        session.add(tenant)
        await session.flush()

        # Provision default quotas from tier
        tier_limits = _TIER_DEFAULTS.get(tier, _TIER_DEFAULTS["free"])
        quota = TenantQuota(tenant_id=tenant.id, **tier_limits)
        session.add(quota)

        await session.commit()
        await session.refresh(tenant)
        return tenant

    @staticmethod
    async def signup(
        session: AsyncSession,
        *,
        name: str,
        owner_email: str,
        tier: str = "free",
    ) -> dict[str, Any]:
        """Self-service signup: create tenant + quotas and return onboarding payload."""
        tenant = await TenantManager.create_tenant(
            session,
            name=name,
            owner_email=owner_email,
            tier=tier,
        )
        quota = await TenantManager.get_quota(session, tenant_id=tenant.id)
        return {
            "tenant": tenant.model_dump(mode="json"),
            "quota": quota.model_dump(mode="json") if quota else None,
            "onboarding_status": "complete",
        }

    @staticmethod
    async def get_tenant(session: AsyncSession, tenant_id: UUID) -> Tenant | None:
        """Return a single tenant by ID."""
        return await session.get(Tenant, tenant_id)

    @staticmethod
    async def get_tenant_by_slug(session: AsyncSession, slug: str) -> Tenant | None:
        """Return a tenant by its unique slug."""
        result = await session.exec(select(Tenant).where(Tenant.slug == slug).limit(1))
        return result.first()

    @staticmethod
    async def list_tenants(
        session: AsyncSession,
        *,
        status: str | None = None,
        tier: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Tenant], int]:
        """Return paginated tenants with optional filters and total count."""
        base = select(Tenant)
        if status is not None:
            base = base.where(Tenant.status == status)
        if tier is not None:
            base = base.where(Tenant.tier == tier)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                col(Tenant.created_at).desc(),
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update_tenant(
        session: AsyncSession,
        tenant_id: UUID,
        data: dict[str, Any],
    ) -> Tenant | None:
        """Partial-update a tenant. Returns None if not found."""
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            return None
        for key, value in data.items():
            if hasattr(tenant, key) and key not in ("id", "created_at"):
                setattr(tenant, key, value)
        tenant.updated_at = _utcnow()
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        return tenant

    @staticmethod
    async def deactivate_tenant(session: AsyncSession, tenant_id: UUID) -> bool:
        """Soft-deactivate a tenant. Returns True if deactivated."""
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            return False
        tenant.status = "deactivated"
        tenant.updated_at = _utcnow()
        session.add(tenant)
        await session.commit()
        return True

    # ── Quota Management ────────────────────────────────────────────

    @staticmethod
    async def get_quota(
        session: AsyncSession, *, tenant_id: UUID
    ) -> TenantQuota | None:
        """Return the quota record for a tenant."""
        result = await session.exec(
            select(TenantQuota).where(TenantQuota.tenant_id == tenant_id).limit(1)
        )
        return result.first()

    @staticmethod
    async def update_quota(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        data: dict[str, Any],
    ) -> TenantQuota | None:
        """Update quota limits for a tenant. Returns None if not found."""
        quota = await TenantManager.get_quota(session, tenant_id=tenant_id)
        if quota is None:
            return None
        for key, value in data.items():
            if hasattr(quota, key) and key not in ("id", "tenant_id", "created_at"):
                setattr(quota, key, value)
        quota.updated_at = _utcnow()
        session.add(quota)
        await session.commit()
        await session.refresh(quota)
        return quota

    @staticmethod
    async def change_tier(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        new_tier: str,
    ) -> Tenant | None:
        """Change a tenant's tier and update quotas to match new tier defaults."""
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            return None

        tenant.tier = new_tier
        tenant.updated_at = _utcnow()
        session.add(tenant)

        # Update quotas to new tier defaults
        tier_limits = _TIER_DEFAULTS.get(new_tier, _TIER_DEFAULTS["free"])
        quota = await TenantManager.get_quota(session, tenant_id=tenant_id)
        if quota is not None:
            for key, value in tier_limits.items():
                setattr(quota, key, value)
            quota.updated_at = _utcnow()
            session.add(quota)
        else:
            quota = TenantQuota(tenant_id=tenant_id, **tier_limits)
            session.add(quota)

        await session.commit()
        await session.refresh(tenant)
        return tenant

    @staticmethod
    async def check_limit(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        resource_type: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        """Check whether a tenant can consume the requested resource.

        Returns an allow/deny verdict with current usage details.
        """
        quota = await TenantManager.get_quota(session, tenant_id=tenant_id)
        if quota is None:
            return {"allowed": False, "reason": "No quota configured for tenant"}

        usage_field_map: dict[str, tuple[str, str]] = {
            "execution": ("used_executions", "max_executions_per_month"),
            "api_call": ("used_api_calls", "max_api_calls_per_month"),
            "storage": ("used_storage_mb", "max_storage_mb"),
        }

        mapping = usage_field_map.get(resource_type)
        if mapping is None:
            # Unknown resource type — allow by default (e.g. token sub-metering)
            return {"allowed": True, "reason": None, "resource_type": resource_type}

        used_field, max_field = mapping
        current_used = getattr(quota, used_field, 0)
        max_allowed = getattr(quota, max_field, 0)
        burst = max_allowed * (quota.burst_allowance_pct / 100.0)
        effective_limit = max_allowed + burst

        would_use = current_used + quantity
        allowed = would_use <= effective_limit

        if not allowed and quota.enforcement == "soft":
            # Soft enforcement — allow but flag warning
            return {
                "allowed": True,
                "warning": True,
                "reason": f"Soft limit exceeded for {resource_type}",
                "resource_type": resource_type,
                "used": current_used,
                "limit": max_allowed,
                "burst_limit": effective_limit,
            }

        return {
            "allowed": allowed,
            "reason": f"Hard limit exceeded for {resource_type}"
            if not allowed
            else None,
            "resource_type": resource_type,
            "used": current_used,
            "limit": max_allowed,
            "burst_limit": effective_limit,
        }

    # ── Usage Metering ──────────────────────────────────────────────

    @staticmethod
    async def record_usage(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        resource_type: str,
        quantity: int = 1,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        execution_id: UUID | None = None,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> UsageMeteringRecord:
        """Record a usage event and increment the tenant's quota counters."""
        record = UsageMeteringRecord(
            tenant_id=tenant_id,
            resource_type=resource_type,
            quantity=quantity,
            agent_id=agent_id,
            user_id=user_id,
            execution_id=execution_id,
            description=description,
            extra_metadata=metadata or {},
        )
        session.add(record)

        # Increment quota counters
        quota = await TenantManager.get_quota(session, tenant_id=tenant_id)
        if quota is not None:
            counter_map: dict[str, str] = {
                "execution": "used_executions",
                "api_call": "used_api_calls",
                "storage": "used_storage_mb",
            }
            counter_field = counter_map.get(resource_type)
            if counter_field is not None:
                current = getattr(quota, counter_field, 0)
                setattr(quota, counter_field, current + quantity)
                quota.updated_at = _utcnow()
                session.add(quota)

        await session.commit()
        await session.refresh(record)
        return record

    @staticmethod
    async def list_usage(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[UsageMeteringRecord], int]:
        """Return paginated usage records for a tenant."""
        base = select(UsageMeteringRecord).where(
            UsageMeteringRecord.tenant_id == tenant_id,
        )
        if resource_type is not None:
            base = base.where(UsageMeteringRecord.resource_type == resource_type)
        if since is not None:
            base = base.where(col(UsageMeteringRecord.created_at) >= since)
        if until is not None:
            base = base.where(col(UsageMeteringRecord.created_at) <= until)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                col(UsageMeteringRecord.created_at).desc(),
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def get_usage_summary(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        """Aggregate usage by resource type for a tenant over a period."""
        if since is None:
            since = _utcnow() - timedelta(days=30)
        if until is None:
            until = _utcnow()

        base = select(UsageMeteringRecord).where(
            UsageMeteringRecord.tenant_id == tenant_id,
            col(UsageMeteringRecord.created_at) >= since,
            col(UsageMeteringRecord.created_at) <= until,
        )
        result = await session.exec(base)
        records = list(result.all())

        breakdown: dict[str, int] = {}
        for r in records:
            breakdown[r.resource_type] = breakdown.get(r.resource_type, 0) + r.quantity

        return {
            "tenant_id": str(tenant_id),
            "period": {"since": since.isoformat(), "until": until.isoformat()},
            "total_events": len(records),
            "breakdown": breakdown,
        }

    # ── Billing Records ─────────────────────────────────────────────

    @staticmethod
    async def create_billing_record(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        record_type: str,
        amount: float,
        currency: str = "USD",
        status: str = "pending",
        stripe_invoice_id: str | None = None,
        stripe_payment_intent_id: str | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> BillingRecord:
        """Create a billing record for a tenant."""
        record = BillingRecord(
            tenant_id=tenant_id,
            record_type=record_type,
            amount=amount,
            currency=currency,
            status=status,
            stripe_invoice_id=stripe_invoice_id,
            stripe_payment_intent_id=stripe_payment_intent_id,
            period_start=period_start,
            period_end=period_end,
            description=description,
            extra_metadata=metadata or {},
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    @staticmethod
    async def list_billing_records(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        record_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[BillingRecord], int]:
        """Return paginated billing records for a tenant."""
        base = select(BillingRecord).where(BillingRecord.tenant_id == tenant_id)
        if record_type is not None:
            base = base.where(BillingRecord.record_type == record_type)
        if status is not None:
            base = base.where(BillingRecord.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                col(BillingRecord.created_at).desc(),
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update_billing_record(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        record_id: UUID,
        data: dict[str, Any],
    ) -> BillingRecord | None:
        """Update a billing record. Enforces tenant isolation."""
        record = await session.get(BillingRecord, record_id)
        if record is None or record.tenant_id != tenant_id:
            return None
        for key, value in data.items():
            if hasattr(record, key) and key not in ("id", "tenant_id", "created_at"):
                setattr(record, key, value)
        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


__all__ = [
    "TenantManager",
]
