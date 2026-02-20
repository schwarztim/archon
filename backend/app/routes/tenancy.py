"""API routes for multi-tenant management — tenants, quotas, usage metering, and billing.

Includes enterprise routes for self-service onboarding, IdP configuration,
Vault namespaces, tier management, quota checks, invoice generation, and
onboarding status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models.tenancy import (
    IdPConfiguration,
    TenantCreateRequest,
    TenantTier,
)
from app.services.tenant_service import TenantService
from app.services.tenancy import TenantManager
from starlette.responses import Response

router = APIRouter(prefix="/tenants", tags=["tenants"])


# ── Request / response schemas ──────────────────────────────────────


class TenantCreate(BaseModel):
    """Payload for creating a new tenant."""

    name: str
    owner_email: str
    tier: str = "free"
    slug: str | None = None
    settings: dict[str, Any] = PField(default_factory=dict)


class TenantUpdate(BaseModel):
    """Payload for partial-updating a tenant."""

    name: str | None = None
    tier: str | None = None
    status: str | None = None
    settings: dict[str, Any] | None = None


class SignupRequest(BaseModel):
    """Payload for self-service tenant signup."""

    name: str
    owner_email: str
    tier: str = "free"


class QuotaUpdate(BaseModel):
    """Payload for updating tenant quotas."""

    max_executions_per_month: int | None = PField(default=None, ge=0)
    max_agents: int | None = PField(default=None, ge=0)
    max_storage_mb: int | None = PField(default=None, ge=0)
    max_api_calls_per_month: int | None = PField(default=None, ge=0)
    enforcement: str | None = None
    burst_allowance_pct: float | None = PField(default=None, ge=0.0)


class ChangeTierRequest(BaseModel):
    """Payload for changing a tenant's tier."""

    tier: str


class RecordUsageRequest(BaseModel):
    """Payload for recording a usage event."""

    resource_type: str
    quantity: int = PField(default=1, ge=1)
    agent_id: UUID | None = None
    user_id: UUID | None = None
    execution_id: UUID | None = None
    description: str = ""
    metadata: dict[str, Any] = PField(default_factory=dict)


class CheckLimitRequest(BaseModel):
    """Payload for checking a resource limit."""

    resource_type: str
    quantity: int = PField(default=1, ge=1)


class BillingRecordCreate(BaseModel):
    """Payload for creating a billing record."""

    record_type: str
    amount: float = PField(ge=0.0)
    currency: str = "USD"
    status: str = "pending"
    stripe_invoice_id: str | None = None
    stripe_payment_intent_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    description: str = ""
    metadata: dict[str, Any] = PField(default_factory=dict)


class BillingRecordUpdate(BaseModel):
    """Payload for updating a billing record."""

    status: str | None = None
    amount: float | None = PField(default=None, ge=0.0)
    description: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Tenant CRUD ─────────────────────────────────────────────────────


@router.post("", status_code=201)
async def create_tenant(
    body: TenantCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new tenant with default quotas."""
    try:
        tenant = await TenantManager.create_tenant(
            session,
            name=body.name,
            owner_email=body.owner_email,
            tier=body.tier,
            slug=body.slug,
            settings=body.settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


@router.post("/signup", status_code=201)
async def signup(
    body: SignupRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Self-service tenant signup."""
    try:
        result = await TenantManager.signup(
            session, name=body.name, owner_email=body.owner_email, tier=body.tier,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"data": result, "meta": _meta()}


@router.get("")
async def list_tenants(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List tenants with pagination."""
    tenants, total = await TenantManager.list_tenants(
        session, status=status, tier=tier, limit=limit, offset=offset,
    )
    return {
        "data": [t.model_dump(mode="json") for t in tenants],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a tenant by ID."""
    tenant = await TenantManager.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


@router.put("/{tenant_id}")
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a tenant."""
    data = body.model_dump(exclude_unset=True)
    tenant = await TenantManager.update_tenant(session, tenant_id, data)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


@router.delete("/{tenant_id}", status_code=204, response_class=Response)
async def deactivate_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Deactivate a tenant (soft delete)."""
    deactivated = await TenantManager.deactivate_tenant(session, tenant_id)
    if not deactivated:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return Response(status_code=204)


@router.post("/{tenant_id}/change-tier")
async def change_tier(
    tenant_id: UUID,
    body: ChangeTierRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Change a tenant's tier and update quotas."""
    tenant = await TenantManager.change_tier(
        session, tenant_id=tenant_id, new_tier=body.tier,
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


# ── Quotas ──────────────────────────────────────────────────────────


@router.get("/{tenant_id}/quota")
async def get_quota(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get quota for a tenant."""
    quota = await TenantManager.get_quota(session, tenant_id=tenant_id)
    if quota is None:
        raise HTTPException(status_code=404, detail="Quota not found for tenant")
    return {"data": quota.model_dump(mode="json"), "meta": _meta()}


@router.put("/{tenant_id}/quota")
async def update_quota(
    tenant_id: UUID,
    body: QuotaUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update quota limits for a tenant."""
    data = body.model_dump(exclude_unset=True)
    quota = await TenantManager.update_quota(session, tenant_id=tenant_id, data=data)
    if quota is None:
        raise HTTPException(status_code=404, detail="Quota not found for tenant")
    return {"data": quota.model_dump(mode="json"), "meta": _meta()}


@router.post("/{tenant_id}/check-limit")
async def check_limit(
    tenant_id: UUID,
    body: CheckLimitRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Check if a tenant can consume a resource."""
    result = await TenantManager.check_limit(
        session,
        tenant_id=tenant_id,
        resource_type=body.resource_type,
        quantity=body.quantity,
    )
    return {"data": result, "meta": _meta()}


# ── Usage Metering ──────────────────────────────────────────────────


@router.post("/{tenant_id}/usage", status_code=201)
async def record_usage(
    tenant_id: UUID,
    body: RecordUsageRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record a usage event for a tenant."""
    record = await TenantManager.record_usage(
        session,
        tenant_id=tenant_id,
        resource_type=body.resource_type,
        quantity=body.quantity,
        agent_id=body.agent_id,
        user_id=body.user_id,
        execution_id=body.execution_id,
        description=body.description,
        metadata=body.metadata,
    )
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.get("/{tenant_id}/usage")
async def list_usage(
    tenant_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    resource_type: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List usage records for a tenant."""
    records, total = await TenantManager.list_usage(
        session,
        tenant_id=tenant_id,
        resource_type=resource_type,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [r.model_dump(mode="json") for r in records],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/{tenant_id}/usage/summary")
async def usage_summary(
    tenant_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get aggregated usage summary for a tenant."""
    summary = await TenantManager.get_usage_summary(
        session, tenant_id=tenant_id, since=since, until=until,
    )
    return {"data": summary, "meta": _meta()}


# ── Billing ─────────────────────────────────────────────────────────


@router.post("/{tenant_id}/billing", status_code=201)
async def create_billing_record(
    tenant_id: UUID,
    body: BillingRecordCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a billing record for a tenant."""
    record = await TenantManager.create_billing_record(
        session,
        tenant_id=tenant_id,
        record_type=body.record_type,
        amount=body.amount,
        currency=body.currency,
        status=body.status,
        stripe_invoice_id=body.stripe_invoice_id,
        stripe_payment_intent_id=body.stripe_payment_intent_id,
        period_start=body.period_start,
        period_end=body.period_end,
        description=body.description,
        metadata=body.metadata,
    )
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.get("/{tenant_id}/billing")
async def list_billing_records(
    tenant_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    record_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List billing records for a tenant."""
    records, total = await TenantManager.list_billing_records(
        session,
        tenant_id=tenant_id,
        record_type=record_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [r.model_dump(mode="json") for r in records],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.put("/{tenant_id}/billing/{record_id}")
async def update_billing_record(
    tenant_id: UUID,
    record_id: UUID,
    body: BillingRecordUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a billing record (enforces tenant isolation)."""
    data = body.model_dump(exclude_unset=True)
    record = await TenantManager.update_billing_record(
        session, tenant_id=tenant_id, record_id=record_id, data=data,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Billing record not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


# ══════════════════════════════════════════════════════════════════════
# Enterprise tenant routes — self-service onboarding, IdP, Vault, billing
# ══════════════════════════════════════════════════════════════════════


class TenantUpdateRequest(BaseModel):
    """Payload for partial-updating a tenant via enterprise route."""

    name: str | None = None
    tier: str | None = None
    status: str | None = None
    settings: dict[str, Any] | None = None
    custom_domain: str | None = None


class SetTierRequest(BaseModel):
    """Payload for setting a tenant's subscription tier."""

    tier: TenantTier


class QuotaCheckRequest(BaseModel):
    """Payload for checking a resource quota."""

    resource_type: str


class InvoiceRequest(BaseModel):
    """Payload for generating an invoice."""

    period: str = "current"


# ── POST /api/v1/tenants — Create tenant (self-service onboarding) ──


enterprise_router = APIRouter(prefix="/api/v1/tenants", tags=["enterprise-tenants"])


@enterprise_router.post("", status_code=201)
async def enterprise_create_tenant(
    body: TenantCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Self-service tenant onboarding: create tenant, Vault namespace, default policies."""
    try:
        tenant = await TenantService.create_tenant(user, body, session=session)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


# ── GET /api/v1/tenants/{id} — Get tenant ───────────────────────────


@enterprise_router.get("/{tenant_id}")
async def enterprise_get_tenant(
    tenant_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get tenant details (authenticated, tenant-scoped)."""
    try:
        tenant = await TenantService.get_tenant(tenant_id, session=session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


# ── PATCH /api/v1/tenants/{id} — Update tenant ──────────────────────


@enterprise_router.patch("/{tenant_id}")
async def enterprise_update_tenant(
    tenant_id: UUID,
    body: TenantUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update tenant configuration (RBAC enforced, audit logged)."""
    updates = body.model_dump(exclude_unset=True)
    try:
        tenant = await TenantService.update_tenant(
            tenant_id, user, updates, session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


# ── POST /api/v1/tenants/{id}/idp — Configure IdP ───────────────────


@enterprise_router.post("/{tenant_id}/idp", status_code=201)
async def enterprise_configure_idp(
    tenant_id: UUID,
    body: IdPConfiguration,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Configure SAML/OIDC/LDAP identity provider for tenant (certs in Vault)."""
    try:
        idp = await TenantService.configure_idp(
            tenant_id, user, body, session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"data": idp.model_dump(mode="json"), "meta": _meta()}


# ── GET /api/v1/tenants/{id}/idps — List IdPs ───────────────────────


@enterprise_router.get("/{tenant_id}/idps")
async def enterprise_list_idps(
    tenant_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List configured identity providers for tenant."""
    try:
        idps = await TenantService.list_idps(tenant_id, session=session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "data": [idp.model_dump(mode="json") for idp in idps],
        "meta": _meta(),
    }


# ── GET /api/v1/tenants/{id}/usage — Usage metrics ──────────────────


@enterprise_router.get("/{tenant_id}/usage")
async def enterprise_usage_metrics(
    tenant_id: UUID,
    period: str = Query(default="current", description="current or last_30d"),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get real-time usage metrics for tenant (executions, tokens, storage, seats)."""
    metrics = await TenantService.get_usage_metrics(
        tenant_id, period, session=session,
    )
    return {"data": metrics.model_dump(mode="json"), "meta": _meta()}


# ── PUT /api/v1/tenants/{id}/tier — Set tier ────────────────────────


@enterprise_router.put("/{tenant_id}/tier")
async def enterprise_set_tier(
    tenant_id: UUID,
    body: SetTierRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Set subscription tier for tenant with associated limits."""
    try:
        tenant = await TenantService.set_tier(
            tenant_id, user, body.tier, session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"data": tenant.model_dump(mode="json"), "meta": _meta()}


# ── POST /api/v1/tenants/{id}/quota-check — Check quota ─────────────


@enterprise_router.post("/{tenant_id}/quota-check")
async def enterprise_check_quota(
    tenant_id: UUID,
    body: QuotaCheckRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Check if an operation is within tenant tier limits."""
    result = await TenantService.check_quota(
        tenant_id, body.resource_type, session=session,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── POST /api/v1/tenants/{id}/invoice — Generate invoice ────────────


@enterprise_router.post("/{tenant_id}/invoice", status_code=201)
async def enterprise_generate_invoice(
    tenant_id: UUID,
    body: InvoiceRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate usage-based invoice for tenant billing period."""
    check_permission(user, "tenants", "admin")
    invoice = await TenantService.generate_invoice(
        tenant_id, body.period, session=session,
    )
    return {"data": invoice.model_dump(mode="json"), "meta": _meta()}


# ── GET /api/v1/tenants/{id}/onboarding — Onboarding status ─────────


@enterprise_router.get("/{tenant_id}/onboarding")
async def enterprise_onboarding_status(
    tenant_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get onboarding checklist status for tenant."""
    try:
        status = await TenantService.get_onboarding_status(
            tenant_id, session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": status.model_dump(mode="json"), "meta": _meta()}
