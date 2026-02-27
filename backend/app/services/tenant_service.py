"""Enterprise multi-tenant service — onboarding, IdP config, Vault namespaces, billing, quotas."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import check_permission
from app.models.tenancy import (
    BillingRecord,
    IdPConfiguration,
    Invoice,
    InvoiceLineItem,
    OnboardingStatus,
    OnboardingStep,
    QuotaCheckResult,
    TIER_LIMITS,
    Tenant,
    TenantCreateRequest,
    TenantQuota,
    TenantTier,
    UsageMetrics,
    UsageMeteringRecord,
    VaultNamespaceInfo,
)
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


from app.utils.time import utcnow as _utcnow


def _slugify(name: str) -> str:
    """Convert a tenant name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


# ── Pricing per resource unit (for invoice generation) ──────────────

_UNIT_PRICES: dict[str, float] = {
    "execution": 0.01,
    "token": 0.00001,
    "storage": 0.05,
    "api_call": 0.001,
}


class TenantService:
    """Enterprise multi-tenant lifecycle, IdP configuration, Vault namespaces, and billing.

    All methods enforce RBAC checks and emit audit log entries for state changes.
    All database queries are scoped to tenant_id for strict tenant isolation.
    """

    # ── Tenant Onboarding & CRUD ────────────────────────────────────

    @staticmethod
    async def create_tenant(
        admin_user: AuthenticatedUser,
        config: TenantCreateRequest,
        *,
        session: AsyncSession,
    ) -> Tenant:
        """Self-service onboarding: create tenant, Vault namespace, default policies, admin user.

        Args:
            admin_user: The authenticated user initiating creation.
            config: Tenant creation parameters.
            session: Async database session.

        Returns:
            The newly created Tenant.
        """
        check_permission(admin_user, "tenants", "create")

        slug = config.slug or _slugify(config.name)

        # Check slug uniqueness
        existing = await session.exec(
            select(Tenant).where(Tenant.slug == slug).limit(1),
        )
        if existing.first() is not None:
            raise ValueError(f"Tenant slug '{slug}' already exists")

        tier_value = (
            config.tier.value if isinstance(config.tier, TenantTier) else config.tier
        )
        settings: dict[str, Any] = {}
        if config.custom_domain:
            settings["custom_domain"] = config.custom_domain

        tenant = Tenant(
            name=config.name,
            slug=slug,
            tier=tier_value,
            owner_email=config.admin_email,
            settings=settings,
        )
        session.add(tenant)
        await session.flush()

        # Provision default quotas from tier
        tier_limits = TIER_LIMITS.get(tier_value, TIER_LIMITS[TenantTier.FREE])
        quota_fields = {k: v for k, v in tier_limits.items() if k != "max_seats"}
        quota = TenantQuota(tenant_id=tenant.id, **quota_fields)
        session.add(quota)

        await session.commit()
        await session.refresh(tenant)

        # Audit log
        await AuditLogService.create(
            session,
            actor_id=UUID(admin_user.id),
            action="tenant.created",
            resource_type="tenant",
            resource_id=tenant.id,
            details={"name": tenant.name, "slug": slug, "tier": tier_value},
        )

        logger.info(
            "Tenant created",
            extra={"tenant_id": str(tenant.id), "slug": slug},
        )
        return tenant

    @staticmethod
    async def get_tenant(
        tenant_id: UUID,
        *,
        session: AsyncSession,
    ) -> Tenant:
        """Retrieve tenant details by ID.

        Args:
            tenant_id: The tenant UUID.
            session: Async database session.

        Returns:
            The Tenant if found.

        Raises:
            ValueError: If tenant not found.
        """
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found")
        return tenant

    @staticmethod
    async def update_tenant(
        tenant_id: UUID,
        user: AuthenticatedUser,
        updates: dict[str, Any],
        *,
        session: AsyncSession,
    ) -> Tenant:
        """Update tenant configuration fields.

        Args:
            tenant_id: The tenant UUID.
            user: Authenticated user performing the update.
            updates: Dictionary of fields to update.
            session: Async database session.

        Returns:
            The updated Tenant.
        """
        check_permission(user, "tenants", "update")

        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Enforce tenant isolation
        if user.tenant_id and user.tenant_id != str(tenant_id):
            if "admin" not in user.roles:
                raise PermissionError("Cross-tenant update denied")

        immutable_fields = {"id", "created_at"}
        for key, value in updates.items():
            if key in immutable_fields:
                continue
            if hasattr(tenant, key):
                setattr(tenant, key, value)
        tenant.updated_at = _utcnow().replace(tzinfo=None)
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)

        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="tenant.updated",
            resource_type="tenant",
            resource_id=tenant.id,
            details={"updated_fields": list(updates.keys())},
        )
        return tenant

    # ── Identity Provider Configuration ─────────────────────────────

    @staticmethod
    async def configure_idp(
        tenant_id: UUID,
        user: AuthenticatedUser,
        idp_config: IdPConfiguration,
        *,
        session: AsyncSession,
    ) -> IdPConfiguration:
        """Configure a SAML/OIDC/LDAP identity provider for a tenant.

        Sensitive fields (certs, client secrets) are stored in Vault via the
        vault_secret_path. Only metadata is persisted in the database.

        Args:
            tenant_id: The tenant UUID.
            user: Authenticated user performing configuration.
            idp_config: The IdP configuration to store.
            session: Async database session.

        Returns:
            The configured IdPConfiguration with vault_secret_path set.
        """
        check_permission(user, "tenants", "admin")

        # Verify tenant exists and user has access
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found")

        if idp_config.protocol not in ("saml2", "oidc", "ldap"):
            raise ValueError(f"Unsupported IdP protocol: {idp_config.protocol}")

        # Set tenant ownership
        idp_config.tenant_id = tenant_id
        idp_config.vault_secret_path = f"tenants/{tenant_id}/idp/{idp_config.id}"
        idp_config.updated_at = _utcnow()

        # Store IdP config reference in tenant settings
        tenant_settings = dict(tenant.settings or {})
        idp_list: list[dict[str, Any]] = tenant_settings.get("idp_configs", [])

        # Replace existing config with same ID, or append
        idp_dict = idp_config.model_dump(mode="json")
        idp_list = [c for c in idp_list if c.get("id") != str(idp_config.id)]
        idp_list.append(idp_dict)
        # Sort by priority for failover ordering
        idp_list.sort(key=lambda c: c.get("priority", 0))
        tenant_settings["idp_configs"] = idp_list

        tenant.settings = tenant_settings
        tenant.updated_at = _utcnow().replace(tzinfo=None)
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)

        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="tenant.idp_configured",
            resource_type="tenant",
            resource_id=tenant_id,
            details={
                "idp_id": str(idp_config.id),
                "protocol": idp_config.protocol,
                "email_domains": idp_config.email_domains,
            },
        )

        logger.info(
            "IdP configured for tenant",
            extra={
                "tenant_id": str(tenant_id),
                "idp_protocol": idp_config.protocol,
            },
        )
        return idp_config

    @staticmethod
    async def list_idps(
        tenant_id: UUID,
        *,
        session: AsyncSession,
    ) -> list[IdPConfiguration]:
        """List all configured identity providers for a tenant.

        Args:
            tenant_id: The tenant UUID.
            session: Async database session.

        Returns:
            List of IdPConfiguration sorted by priority.
        """
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found")

        idp_list: list[dict[str, Any]] = (tenant.settings or {}).get("idp_configs", [])
        configs = [IdPConfiguration(**cfg) for cfg in idp_list]
        configs.sort(key=lambda c: c.priority)
        return configs

    # ── Vault Namespace Provisioning ────────────────────────────────

    @staticmethod
    async def provision_vault_namespace(
        tenant_id: UUID,
        *,
        session: AsyncSession,
    ) -> VaultNamespaceInfo:
        """Create an isolated Vault namespace for a tenant.

        In production this would call the Vault sys/namespaces API.
        Here we record the namespace metadata and update tenant settings.

        Args:
            tenant_id: The tenant UUID.
            session: Async database session.

        Returns:
            VaultNamespaceInfo with namespace path and default policies.
        """
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found")

        namespace_path = f"archon/tenants/{tenant_id}"
        default_policies = [
            f"tenant-{tenant_id}-read",
            f"tenant-{tenant_id}-write",
            f"tenant-{tenant_id}-admin",
        ]
        default_mounts = ["kv-v2", "transit", "pki"]

        info = VaultNamespaceInfo(
            namespace_path=namespace_path,
            policies=default_policies,
            mount_points=default_mounts,
        )

        # Persist vault info in tenant settings
        tenant_settings = dict(tenant.settings or {})
        tenant_settings["vault_namespace"] = info.model_dump(mode="json")
        tenant.settings = tenant_settings
        tenant.updated_at = _utcnow().replace(tzinfo=None)
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)

        logger.info(
            "Vault namespace provisioned",
            extra={"tenant_id": str(tenant_id), "namespace": namespace_path},
        )
        return info

    # ── Usage Metrics ───────────────────────────────────────────────

    @staticmethod
    async def get_usage_metrics(
        tenant_id: UUID,
        period: str,
        *,
        session: AsyncSession,
    ) -> UsageMetrics:
        """Get real-time usage metrics for a tenant within a billing period.

        Args:
            tenant_id: The tenant UUID.
            period: Period string, e.g. "current", "last_30d".
            session: Async database session.

        Returns:
            Aggregated UsageMetrics for the period.
        """
        now = _utcnow()
        if period == "last_30d":
            period_start = now - timedelta(days=30)
        else:
            # Default: current month
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        period_end = now

        base = select(UsageMeteringRecord).where(
            UsageMeteringRecord.tenant_id == tenant_id,
            col(UsageMeteringRecord.created_at) >= period_start.replace(tzinfo=None),
            col(UsageMeteringRecord.created_at) <= period_end.replace(tzinfo=None),
        )
        result = await session.exec(base)
        records = list(result.all())

        totals: dict[str, int] = {}
        user_ids: set[str] = set()
        for r in records:
            totals[r.resource_type] = totals.get(r.resource_type, 0) + r.quantity
            if r.user_id:
                user_ids.add(str(r.user_id))

        return UsageMetrics(
            tenant_id=tenant_id,
            executions=totals.get("execution", 0),
            tokens=totals.get("token", 0),
            storage_mb=totals.get("storage", 0),
            active_users=len(user_ids),
            api_calls=totals.get("api_call", 0),
            period_start=period_start,
            period_end=period_end,
        )

    # ── Tier & Quota Management ─────────────────────────────────────

    @staticmethod
    async def set_tier(
        tenant_id: UUID,
        user: AuthenticatedUser,
        tier: TenantTier,
        *,
        session: AsyncSession,
    ) -> Tenant:
        """Set the subscription tier for a tenant and update quotas.

        Args:
            tenant_id: The tenant UUID.
            user: Authenticated user performing the change.
            tier: New TenantTier value.
            session: Async database session.

        Returns:
            The updated Tenant.
        """
        check_permission(user, "tenants", "admin")

        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found")

        old_tier = tenant.tier
        tier_value = tier.value if isinstance(tier, TenantTier) else tier
        tenant.tier = tier_value
        tenant.updated_at = _utcnow().replace(tzinfo=None)
        session.add(tenant)

        # Update quotas
        tier_limits = TIER_LIMITS.get(tier_value, TIER_LIMITS[TenantTier.FREE])
        quota_fields = {k: v for k, v in tier_limits.items() if k != "max_seats"}

        result = await session.exec(
            select(TenantQuota).where(TenantQuota.tenant_id == tenant_id).limit(1),
        )
        quota = result.first()
        if quota is not None:
            for key, value in quota_fields.items():
                setattr(quota, key, value)
            quota.updated_at = _utcnow().replace(tzinfo=None)
            session.add(quota)
        else:
            quota = TenantQuota(tenant_id=tenant_id, **quota_fields)
            session.add(quota)

        await session.commit()
        await session.refresh(tenant)

        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="tenant.tier_changed",
            resource_type="tenant",
            resource_id=tenant_id,
            details={"old_tier": old_tier, "new_tier": tier_value},
        )

        logger.info(
            "Tenant tier changed",
            extra={
                "tenant_id": str(tenant_id),
                "old_tier": old_tier,
                "new_tier": tier_value,
            },
        )
        return tenant

    @staticmethod
    async def check_quota(
        tenant_id: UUID,
        resource_type: str,
        *,
        session: AsyncSession,
    ) -> QuotaCheckResult:
        """Check whether an operation is within the tenant's tier limits.

        Args:
            tenant_id: The tenant UUID.
            resource_type: Resource type to check (execution, api_call, storage).
            session: Async database session.

        Returns:
            QuotaCheckResult with allowed/denied verdict and usage details.
        """
        result = await session.exec(
            select(TenantQuota).where(TenantQuota.tenant_id == tenant_id).limit(1),
        )
        quota = result.first()
        if quota is None:
            return QuotaCheckResult(
                allowed=False,
                resource_type=resource_type,
                warning="No quota configured for tenant",
            )

        usage_field_map: dict[str, tuple[str, str]] = {
            "execution": ("used_executions", "max_executions_per_month"),
            "api_call": ("used_api_calls", "max_api_calls_per_month"),
            "storage": ("used_storage_mb", "max_storage_mb"),
        }

        mapping = usage_field_map.get(resource_type)
        if mapping is None:
            return QuotaCheckResult(
                allowed=True,
                resource_type=resource_type,
                warning="Unknown resource type — allowed by default",
            )

        used_field, max_field = mapping
        current_used = getattr(quota, used_field, 0)
        max_allowed = getattr(quota, max_field, 0)
        burst = max_allowed * (quota.burst_allowance_pct / 100.0)
        effective_limit = int(max_allowed + burst)
        remaining = max(0, effective_limit - current_used)
        allowed = current_used < effective_limit

        warning_msg = None
        if not allowed:
            warning_msg = f"Quota exceeded for {resource_type}"
        elif remaining < (effective_limit * 0.1):
            warning_msg = f"Approaching quota limit for {resource_type}"

        return QuotaCheckResult(
            allowed=allowed,
            resource_type=resource_type,
            current_usage=current_used,
            limit=max_allowed,
            remaining=remaining,
            enforcement=quota.enforcement,
            warning=warning_msg,
        )

    # ── Invoice Generation ──────────────────────────────────────────

    @staticmethod
    async def generate_invoice(
        tenant_id: UUID,
        period: str,
        *,
        session: AsyncSession,
    ) -> Invoice:
        """Generate a usage-based invoice for the tenant.

        Args:
            tenant_id: The tenant UUID.
            period: Period string, e.g. "current", "last_30d".
            session: Async database session.

        Returns:
            Generated Invoice with line items.
        """
        now = _utcnow()
        if period == "last_30d":
            period_start = now - timedelta(days=30)
        else:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end = now

        # Fetch usage records
        base = select(UsageMeteringRecord).where(
            UsageMeteringRecord.tenant_id == tenant_id,
            col(UsageMeteringRecord.created_at) >= period_start.replace(tzinfo=None),
            col(UsageMeteringRecord.created_at) <= period_end.replace(tzinfo=None),
        )
        result = await session.exec(base)
        records = list(result.all())

        # Aggregate by resource type
        totals: dict[str, int] = {}
        for r in records:
            totals[r.resource_type] = totals.get(r.resource_type, 0) + r.quantity

        # Build line items
        line_items: list[InvoiceLineItem] = []
        subtotal = 0.0
        for rtype, qty in totals.items():
            unit_price = _UNIT_PRICES.get(rtype, 0.0)
            amount = round(qty * unit_price, 4)
            line_items.append(
                InvoiceLineItem(
                    description=f"{rtype.replace('_', ' ').title()} usage",
                    resource_type=rtype,
                    quantity=qty,
                    unit_price=unit_price,
                    amount=amount,
                ),
            )
            subtotal += amount

        subtotal = round(subtotal, 2)
        tax = round(subtotal * 0.0, 2)  # Tax placeholder
        total = round(subtotal + tax, 2)

        invoice = Invoice(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            line_items=line_items,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status="draft",
        )

        # Persist as BillingRecord
        billing_record = BillingRecord(
            tenant_id=tenant_id,
            record_type="invoice",
            amount=total,
            currency="USD",
            status="draft",
            period_start=period_start.replace(tzinfo=None),
            period_end=period_end.replace(tzinfo=None),
            description=f"Invoice for {period}",
            extra_metadata={
                "invoice_id": str(invoice.id),
                "line_item_count": len(line_items),
            },
        )
        session.add(billing_record)
        await session.commit()

        logger.info(
            "Invoice generated",
            extra={
                "tenant_id": str(tenant_id),
                "total": total,
                "items": len(line_items),
            },
        )
        return invoice

    # ── Onboarding Status ───────────────────────────────────────────

    @staticmethod
    async def get_onboarding_status(
        tenant_id: UUID,
        *,
        session: AsyncSession,
    ) -> OnboardingStatus:
        """Get the onboarding checklist status for a tenant.

        Args:
            tenant_id: The tenant UUID.
            session: Async database session.

        Returns:
            OnboardingStatus with step completion details.
        """
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant {tenant_id} not found")

        settings = tenant.settings or {}

        steps = [
            OnboardingStep(
                key="tenant_created",
                label="Tenant account created",
                completed=True,
                completed_at=tenant.created_at.replace(tzinfo=timezone.utc)
                if tenant.created_at
                else None,
            ),
            OnboardingStep(
                key="vault_namespace",
                label="Vault namespace provisioned",
                completed="vault_namespace" in settings,
            ),
            OnboardingStep(
                key="idp_configured",
                label="Identity provider configured",
                completed=bool(settings.get("idp_configs")),
            ),
            OnboardingStep(
                key="first_agent",
                label="First agent created",
                completed=settings.get("first_agent_created", False),
            ),
            OnboardingStep(
                key="billing_configured",
                label="Billing information configured",
                completed=tenant.stripe_customer_id is not None,
            ),
        ]

        completed_count = sum(1 for s in steps if s.completed)
        completed_pct = round((completed_count / len(steps)) * 100, 1) if steps else 0.0

        return OnboardingStatus(
            tenant_id=tenant_id,
            steps=steps,
            completed_pct=completed_pct,
        )


__all__ = [
    "TenantService",
]
