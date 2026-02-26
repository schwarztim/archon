"""SQLModel database models for the Archon open marketplace."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class CreatorProfile(SQLModel, table=True):
    """Marketplace creator / publisher profile."""

    __tablename__ = "marketplace_creators"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True, unique=True)
    display_name: str = Field(index=True)
    bio: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    website: str | None = Field(default=None)
    is_verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MarketplaceListing(SQLModel, table=True):
    """A published item in the marketplace (agent, template, connector, etc.)."""

    __tablename__ = "marketplace_listings"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    category: str = Field(index=True)  # agents | templates | connectors | policies | workflows
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    version: str = Field(default="0.1.0")
    license: str = Field(default="MIT")
    readme: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    definition: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    screenshots: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    # Status workflow: draft → pending_review → approved → rejected
    status: str = Field(default="draft", index=True)

    # Ownership
    creator_id: UUID = Field(foreign_key="marketplace_creators.id", index=True)

    # Aggregates (denormalised for fast queries)
    install_count: int = Field(default=0)
    avg_rating: float = Field(default=0.0)
    review_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MarketplaceReview(SQLModel, table=True):
    """User review / rating for a marketplace listing."""

    __tablename__ = "marketplace_reviews"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    listing_id: UUID = Field(foreign_key="marketplace_listings.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MarketplaceInstall(SQLModel, table=True):
    """Record of a listing being installed into a workspace."""

    __tablename__ = "marketplace_installs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    listing_id: UUID = Field(foreign_key="marketplace_listings.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    installed_version: str
    created_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic API schemas (non-table) ─────────────────────────────────

from pydantic import BaseModel, Field as PField  # noqa: E402


class PublisherProfile(BaseModel):
    """Request schema for publisher registration."""

    display_name: str
    email: str
    bio: str | None = None
    github_url: str | None = None


class Publisher(BaseModel):
    """Publisher public profile."""

    id: UUID
    display_name: str
    verified: bool = False
    packages_count: int = 0
    total_installs: int = 0


class PackageSubmission(BaseModel):
    """Request schema for publishing a package."""

    name: str
    description: str | None = None
    category: str
    license: str = "MIT"
    source_url: str | None = None
    version: str = "0.1.0"


class MarketplacePackage(BaseModel):
    """Read-only representation of a marketplace package."""

    id: UUID
    name: str
    publisher: Publisher
    version: str
    category: str
    license: str
    rating: float = 0.0
    installs: int = 0
    verified_signature: bool = False


class Installation(BaseModel):
    """Record of a package installation."""

    package_id: UUID
    tenant_id: str
    installed_version: str
    credential_status: str = "pending"


class PackageSearchResult(BaseModel):
    """Paginated search result container."""

    packages: list[MarketplacePackage] = PField(default_factory=list)
    total: int = 0
    page: int = 1
    filters_applied: dict[str, Any] = PField(default_factory=dict)


class PackageRating(BaseModel):
    """A user rating and review."""

    user_id: UUID
    rating: int = PField(ge=1, le=5)
    review: str | None = None
    created_at: datetime | None = None


class PublisherAnalytics(BaseModel):
    """Aggregate analytics for a publisher."""

    total_installs: int = 0
    total_ratings: int = 0
    avg_rating: float = 0.0
    revenue: float = 0.0


class ReviewResult(BaseModel):
    """Result of the automated review pipeline."""

    passed: bool
    security_score: float = 0.0
    findings: list[str] = PField(default_factory=list)
    license_compatible: bool = True


class SignatureVerification(BaseModel):
    """Result of GPG / Sigstore signature verification."""

    valid: bool
    signer: str | None = None
    signed_at: datetime | None = None
    algorithm: str | None = None


class MarketplaceCategory(BaseModel):
    """A marketplace category."""

    name: str
    slug: str
    package_count: int = 0
    icon: str | None = None


__all__ = [
    "CreatorProfile",
    "MarketplaceInstall",
    "MarketplaceListing",
    "MarketplaceReview",
    "PublisherProfile",
    "Publisher",
    "PackageSubmission",
    "MarketplacePackage",
    "Installation",
    "PackageSearchResult",
    "PackageRating",
    "PublisherAnalytics",
    "ReviewResult",
    "SignatureVerification",
    "MarketplaceCategory",
]
