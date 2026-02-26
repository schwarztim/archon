"""API routes for the Archon open marketplace."""

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
from app.models.marketplace import (
    CreatorProfile,
    MarketplaceInstall,
    MarketplaceListing,
    MarketplaceReview,
    PackageRating,
    PackageSubmission,
    PublisherProfile,
)
from app.secrets.manager import get_secrets_manager, VaultSecretsManager
from app.services.marketplace import MarketplaceService
from app.services.marketplace_service import (
    MarketplaceService as EnterpriseMarketplaceService,
)
from starlette.responses import Response

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ── Request / response schemas ──────────────────────────────────────


class ListingCreate(BaseModel):
    """Payload for creating a marketplace listing."""

    name: str
    description: str | None = None
    category: str
    tags: list[str] = PField(default_factory=list)
    version: str = "0.1.0"
    license: str = "MIT"
    readme: str | None = None
    definition: dict[str, Any] = PField(default_factory=dict)
    screenshots: list[str] = PField(default_factory=list)
    extra_metadata: dict[str, Any] = PField(default_factory=dict)
    creator_id: UUID


class ListingUpdate(BaseModel):
    """Payload for partial-updating a marketplace listing."""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    version: str | None = None
    license: str | None = None
    readme: str | None = None
    definition: dict[str, Any] | None = None
    screenshots: list[str] | None = None
    extra_metadata: dict[str, Any] | None = None
    status: str | None = None


class ReviewCreate(BaseModel):
    """Payload for submitting a review."""

    listing_id: UUID
    user_id: UUID
    rating: int = PField(ge=1, le=5)
    comment: str | None = None


class InstallCreate(BaseModel):
    """Payload for recording an install."""

    listing_id: UUID
    user_id: UUID
    installed_version: str


class CreatorCreate(BaseModel):
    """Payload for registering a creator profile."""

    user_id: UUID
    display_name: str
    bio: str | None = None
    website: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Listing endpoints ───────────────────────────────────────────────


@router.get("/listings")
async def search_listings(
    query: str | None = Query(default=None),
    category: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    status: str | None = Query(default=None),
    creator_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search marketplace listings with filters and pagination."""
    items, total = await MarketplaceService.search_listings(
        session,
        query=query,
        category=category,
        tag=tag,
        status=status,
        creator_id=creator_id,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [i.model_dump(mode="json") for i in items],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/listings", status_code=201)
async def create_listing(
    body: ListingCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new marketplace listing."""
    listing = MarketplaceListing(**body.model_dump())
    created = await MarketplaceService.create_listing(session, listing)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/listings/{listing_id}")
async def get_listing(
    listing_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a marketplace listing by ID."""
    listing = await MarketplaceService.get_listing(session, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"data": listing.model_dump(mode="json"), "meta": _meta()}


@router.put("/listings/{listing_id}")
async def update_listing(
    listing_id: UUID,
    body: ListingUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a marketplace listing."""
    data = body.model_dump(exclude_unset=True)
    listing = await MarketplaceService.update_listing(session, listing_id, data)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"data": listing.model_dump(mode="json"), "meta": _meta()}


@router.delete("/listings/{listing_id}", status_code=204, response_class=Response)
async def delete_listing(
    listing_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a marketplace listing."""
    deleted = await MarketplaceService.delete_listing(session, listing_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Listing not found")
    return Response(status_code=204)


@router.post("/listings/{listing_id}/approve")
async def approve_listing(
    listing_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Approve a marketplace listing for publication."""
    listing = await MarketplaceService.approve_listing(session, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"data": listing.model_dump(mode="json"), "meta": _meta()}


# ── Review endpoints ────────────────────────────────────────────────


@router.get("/listings/{listing_id}/reviews")
async def list_reviews(
    listing_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List reviews for a listing."""
    reviews, total = await MarketplaceService.list_reviews(
        session,
        listing_id,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [r.model_dump(mode="json") for r in reviews],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/reviews", status_code=201)
async def create_review(
    body: ReviewCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Submit a review for a listing."""
    review = MarketplaceReview(**body.model_dump())
    created = await MarketplaceService.create_review(session, review)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


# ── Install endpoints ──────────────────────────────────────────────


@router.post("/installs", status_code=201)
async def install_listing(
    body: InstallCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record a listing install."""
    install = MarketplaceInstall(**body.model_dump())
    created = await MarketplaceService.install_listing(session, install)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


# ── Creator endpoints ──────────────────────────────────────────────


@router.get("/catalog")
async def browse_catalog(
    query: str | None = Query(default=None),
    category: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Browse the public marketplace catalog with search and sorting."""
    items, total = await MarketplaceService.catalog(
        session,
        query=query,
        category=category,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [i.model_dump(mode="json") for i in items],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/{listing_id}/install", status_code=201)
async def install_by_id(
    listing_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Install a marketplace listing — creates an agent in the workspace."""
    user_id = UUID(user.id) if user else UUID("00000000-0000-0000-0000-000000000001")
    install = await MarketplaceService.install_by_id(session, listing_id, user_id)
    if install is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"data": install.model_dump(mode="json"), "meta": _meta()}


@router.post("/creators", status_code=201)
async def create_creator(
    body: CreatorCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a new creator profile."""
    profile = CreatorProfile(**body.model_dump())
    created = await MarketplaceService.create_creator(session, profile)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/creators/{creator_id}")
async def get_creator(
    creator_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a creator profile by ID."""
    profile = await MarketplaceService.get_creator(session, creator_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    return {"data": profile.model_dump(mode="json"), "meta": _meta()}


# ── Enterprise Marketplace Endpoints ────────────────────────────────


def _get_enterprise_svc(
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> EnterpriseMarketplaceService:
    """Build the enterprise marketplace service with secrets manager."""
    return EnterpriseMarketplaceService(secrets_manager=secrets)


@router.post("/publishers", status_code=201)
async def register_publisher(
    body: PublisherProfile,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """Register as a marketplace publisher with identity verification."""
    try:
        publisher = await svc.register_publisher(
            user.tenant_id,
            user,
            body,
            session,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"data": publisher.model_dump(mode="json"), "meta": _meta()}


@router.post("/packages", status_code=201)
async def publish_package(
    body: PackageSubmission,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """Publish a package with GPG signing, security scan, and license check."""
    try:
        package = await svc.publish_package(
            user.tenant_id,
            user,
            body,
            session,
        )
    except (PermissionError, ValueError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return {"data": package.model_dump(mode="json"), "meta": _meta()}


@router.post("/packages/{package_id}/install", status_code=201)
async def install_package(
    package_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """One-click install with RBAC check, credential setup, and dependency resolution."""
    try:
        installation = await svc.install_package(
            user.tenant_id,
            user,
            package_id,
            session,
        )
    except (PermissionError, ValueError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 404
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return {"data": installation.model_dump(mode="json"), "meta": _meta()}


@router.get("/packages/search")
async def search_packages(
    query: str | None = Query(default=None),
    category: str | None = Query(default=None),
    license: str | None = Query(default=None),
    min_rating: float | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """Search packages with category, rating, and license filters."""
    filters: dict[str, Any] = {"limit": limit, "offset": offset}
    if category:
        filters["category"] = category
    if license:
        filters["license"] = license
    if min_rating is not None:
        filters["min_rating"] = min_rating

    result = await svc.search_packages(
        user.tenant_id,
        query,
        filters,
        session,
    )
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(
            pagination={"total": result.total, "limit": limit, "offset": offset},
        ),
    }


@router.post("/packages/{package_id}/rate", status_code=201)
async def rate_package(
    package_id: UUID,
    body: PackageRating,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """Rate and review a marketplace package."""
    try:
        pkg_rating = await svc.rate_package(
            user.tenant_id,
            user,
            package_id,
            body.rating,
            body.review,
            session,
        )
    except (PermissionError, ValueError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 404
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return {"data": pkg_rating.model_dump(mode="json"), "meta": _meta()}


@router.get("/publishers/analytics")
async def get_publisher_analytics(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """Get publisher analytics: installs, ratings, revenue."""
    try:
        analytics = await svc.get_publisher_analytics(
            user.tenant_id,
            user,
            session,
        )
    except (PermissionError, ValueError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 404
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return {"data": analytics.model_dump(mode="json"), "meta": _meta()}


@router.get("/packages/{package_id}/verify")
async def verify_package_signature(
    package_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """Verify GPG/Sigstore signature of a marketplace package."""
    try:
        verification = await svc.verify_package_signature(package_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"data": verification.model_dump(mode="json"), "meta": _meta()}


@router.get("/categories")
async def list_categories(
    user: AuthenticatedUser = Depends(get_current_user),
    svc: EnterpriseMarketplaceService = Depends(_get_enterprise_svc),
) -> dict[str, Any]:
    """List all marketplace categories."""
    categories = svc.list_categories()
    return {
        "data": [c.model_dump(mode="json") for c in categories],
        "meta": _meta(),
    }
