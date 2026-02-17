"""SQLModel database models and Pydantic schemas for multi-tenant isolation, quotas, metering, and billing."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field as PField
from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class Tenant(SQLModel, table=True):
    """Top-level tenant representing an organisation on the platform."""

    __tablename__ = "tenants"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    tier: str = Field(default="free")  # free | individual | team | enterprise
    status: str = Field(default="active")  # active | suspended | deactivated

    # Owner / admin contact
    owner_email: str = Field(index=True)

    # Optional Stripe identifiers
    stripe_customer_id: str | None = Field(default=None, index=True)
    stripe_subscription_id: str | None = Field(default=None)

    # Tenant-level settings
    settings: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False),
    )

    created_at: datetime = Field(default_factory=_utcnow, index=True)
    updated_at: datetime = Field(default_factory=_utcnow)


class TenantQuota(SQLModel, table=True):
    """Per-tenant resource limits derived from tier or custom overrides."""

    __tablename__ = "tenant_quotas"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")

    # Limits
    max_executions_per_month: int = Field(default=100)
    max_agents: int = Field(default=5)
    max_storage_mb: int = Field(default=100)
    max_api_calls_per_month: int = Field(default=1000)

    # Current usage counters (reset monthly)
    used_executions: int = Field(default=0)
    used_storage_mb: int = Field(default=0)
    used_api_calls: int = Field(default=0)

    # Enforcement
    enforcement: str = Field(default="hard")  # hard | soft
    burst_allowance_pct: float = Field(default=0.0)  # e.g. 10.0 = 10% overage OK

    # Period tracking
    period_start: datetime = Field(default_factory=_utcnow)
    period_end: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class UsageMeteringRecord(SQLModel, table=True):
    """Individual usage event for metering — append-only time-series data."""

    __tablename__ = "usage_metering_records"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")

    # What was consumed
    resource_type: str = Field(index=True)  # execution | token | storage | api_call
    quantity: int = Field(default=1)

    # Optional attribution
    agent_id: UUID | None = Field(default=None, index=True)
    user_id: UUID | None = Field(default=None, index=True)
    execution_id: UUID | None = Field(default=None, index=True)

    # Context
    description: str = Field(default="", sa_column=Column(SAText, nullable=False))
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False),
    )

    created_at: datetime = Field(default_factory=_utcnow, index=True)


class BillingRecord(SQLModel, table=True):
    """Billing event — invoices, payments, credits, chargebacks."""

    __tablename__ = "billing_records"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")

    record_type: str = Field(index=True)  # invoice | payment | credit | chargeback
    amount: float = Field(default=0.0)
    currency: str = Field(default="USD")
    status: str = Field(default="pending")  # pending | paid | failed | void

    # Stripe references
    stripe_invoice_id: str | None = Field(default=None, index=True)
    stripe_payment_intent_id: str | None = Field(default=None)

    # Period this record covers
    period_start: datetime | None = Field(default=None)
    period_end: datetime | None = Field(default=None)

    description: str = Field(default="", sa_column=Column(SAText, nullable=False))
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False),
    )

    created_at: datetime = Field(default_factory=_utcnow, index=True)
    updated_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic enums and schemas (non-table) ──────────────────────────


class TenantTier(str, Enum):
    """Subscription tiers with associated resource limits."""

    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


TIER_LIMITS: dict[str, dict[str, int]] = {
    TenantTier.FREE: {
        "max_executions_per_month": 100,
        "max_agents": 5,
        "max_storage_mb": 100,
        "max_api_calls_per_month": 1_000,
        "max_seats": 3,
    },
    TenantTier.STARTER: {
        "max_executions_per_month": 5_000,
        "max_agents": 25,
        "max_storage_mb": 1_024,
        "max_api_calls_per_month": 25_000,
        "max_seats": 10,
    },
    TenantTier.PROFESSIONAL: {
        "max_executions_per_month": 50_000,
        "max_agents": 200,
        "max_storage_mb": 10_240,
        "max_api_calls_per_month": 250_000,
        "max_seats": 50,
    },
    TenantTier.ENTERPRISE: {
        "max_executions_per_month": 1_000_000,
        "max_agents": 10_000,
        "max_storage_mb": 1_048_576,
        "max_api_calls_per_month": 10_000_000,
        "max_seats": 10_000,
    },
}


class TenantCreateRequest(BaseModel):
    """Request payload for self-service tenant onboarding."""

    name: str
    slug: str | None = None
    admin_email: str
    tier: TenantTier = TenantTier.FREE
    custom_domain: str | None = None


class IdPConfiguration(BaseModel):
    """Per-tenant identity provider configuration."""

    id: UUID = PField(default_factory=uuid4)
    tenant_id: UUID | None = None
    protocol: str = PField(description="saml2, oidc, or ldap")
    display_name: str = ""
    priority: int = PField(default=0, description="Lower = higher priority for failover")
    email_domains: list[str] = PField(default_factory=list)
    metadata_url: str = ""
    entity_id: str = ""
    client_id: str = ""
    issuer_url: str = ""
    enabled: bool = True
    vault_secret_path: str = PField(default="", description="Vault path where certs/secrets are stored")
    created_at: datetime = PField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = PField(default_factory=lambda: datetime.now(timezone.utc))


class VaultNamespaceInfo(BaseModel):
    """Information about a tenant's isolated Vault namespace."""

    namespace_path: str
    policies: list[str] = PField(default_factory=list)
    mount_points: list[str] = PField(default_factory=list)
    created_at: datetime = PField(default_factory=lambda: datetime.now(timezone.utc))


class UsageMetrics(BaseModel):
    """Real-time usage metrics for a tenant within a billing period."""

    tenant_id: UUID
    executions: int = 0
    tokens: int = 0
    storage_mb: int = 0
    active_users: int = 0
    api_calls: int = 0
    period_start: datetime
    period_end: datetime


class QuotaCheckResult(BaseModel):
    """Result of a quota/limit check for a specific resource type."""

    allowed: bool
    resource_type: str
    current_usage: int = 0
    limit: int = 0
    remaining: int = 0
    enforcement: str = "hard"
    warning: str | None = None


class InvoiceLineItem(BaseModel):
    """Single line item on an invoice."""

    description: str
    resource_type: str
    quantity: int = 0
    unit_price: float = 0.0
    amount: float = 0.0


class Invoice(BaseModel):
    """Usage-based invoice for a tenant billing period."""

    id: UUID = PField(default_factory=uuid4)
    tenant_id: UUID
    period_start: datetime
    period_end: datetime
    line_items: list[InvoiceLineItem] = PField(default_factory=list)
    subtotal: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    currency: str = "USD"
    status: str = "draft"
    generated_at: datetime = PField(default_factory=lambda: datetime.now(timezone.utc))


class OnboardingStep(BaseModel):
    """A single step in the tenant onboarding checklist."""

    key: str
    label: str
    completed: bool = False
    completed_at: datetime | None = None


class OnboardingStatus(BaseModel):
    """Onboarding checklist status for a tenant."""

    tenant_id: UUID
    steps: list[OnboardingStep] = PField(default_factory=list)
    completed_pct: float = 0.0


__all__ = [
    "BillingRecord",
    "IdPConfiguration",
    "Invoice",
    "InvoiceLineItem",
    "OnboardingStatus",
    "OnboardingStep",
    "QuotaCheckResult",
    "TIER_LIMITS",
    "Tenant",
    "TenantCreateRequest",
    "TenantQuota",
    "TenantTier",
    "UsageMetrics",
    "UsageMeteringRecord",
    "VaultNamespaceInfo",
]
