"""Marketplace service — business logic for listings, reviews, and installs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models.marketplace import (
    CreatorProfile,
    MarketplaceInstall,
    MarketplaceListing,
    MarketplaceReview,
)


class MarketplaceService:
    """CRUD and business operations for the open marketplace."""

    # ── Listings ────────────────────────────────────────────────────

    @staticmethod
    async def create_listing(
        session: AsyncSession, listing: MarketplaceListing
    ) -> MarketplaceListing:
        """Create a new marketplace listing (status defaults to 'draft')."""
        session.add(listing)
        await session.commit()
        await session.refresh(listing)
        return listing

    @staticmethod
    async def get_listing(
        session: AsyncSession, listing_id: UUID
    ) -> MarketplaceListing | None:
        """Return a single listing by ID."""
        return await session.get(MarketplaceListing, listing_id)

    @staticmethod
    async def search_listings(
        session: AsyncSession,
        *,
        query: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        creator_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MarketplaceListing], int]:
        """Search and filter listings with pagination.

        Returns a ``(items, total_count)`` tuple.
        """
        base = select(MarketplaceListing)

        if status is not None:
            base = base.where(MarketplaceListing.status == status)
        if category is not None:
            base = base.where(MarketplaceListing.category == category)
        if creator_id is not None:
            base = base.where(MarketplaceListing.creator_id == creator_id)
        if query is not None:
            pattern = f"%{query}%"
            base = base.where(
                MarketplaceListing.name.ilike(pattern)  # type: ignore[union-attr]
                | MarketplaceListing.description.ilike(pattern)  # type: ignore[union-attr]
            )

        # Count before pagination
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await session.exec(count_stmt)  # type: ignore[arg-type]
        total: int = count_result.one()

        # Fetch page
        stmt = base.offset(offset).limit(limit).order_by(
            MarketplaceListing.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        items = list(result.all())

        # In-memory tag filter (JSON column)
        if tag is not None:
            items = [i for i in items if tag in (i.tags or [])]
            total = len(items)

        return items, total

    @staticmethod
    async def update_listing(
        session: AsyncSession,
        listing_id: UUID,
        data: dict[str, Any],
    ) -> MarketplaceListing | None:
        """Partial-update a listing. Returns None if not found."""
        listing = await session.get(MarketplaceListing, listing_id)
        if listing is None:
            return None
        for key, value in data.items():
            if hasattr(listing, key):
                setattr(listing, key, value)
        session.add(listing)
        await session.commit()
        await session.refresh(listing)
        return listing

    @staticmethod
    async def delete_listing(session: AsyncSession, listing_id: UUID) -> bool:
        """Delete a listing. Returns True if deleted."""
        listing = await session.get(MarketplaceListing, listing_id)
        if listing is None:
            return False
        await session.delete(listing)
        await session.commit()
        return True

    @staticmethod
    async def approve_listing(
        session: AsyncSession, listing_id: UUID
    ) -> MarketplaceListing | None:
        """Transition a listing from 'pending_review' to 'approved'."""
        listing = await session.get(MarketplaceListing, listing_id)
        if listing is None:
            return None
        listing.status = "approved"
        session.add(listing)
        await session.commit()
        await session.refresh(listing)
        return listing

    # ── Reviews ─────────────────────────────────────────────────────

    @staticmethod
    async def create_review(
        session: AsyncSession, review: MarketplaceReview
    ) -> MarketplaceReview:
        """Add a review to a listing and update aggregate rating."""
        session.add(review)
        await session.flush()

        # Recompute aggregate on the listing
        listing = await session.get(MarketplaceListing, review.listing_id)
        if listing is not None:
            stmt = select(func.avg(MarketplaceReview.rating)).where(
                MarketplaceReview.listing_id == review.listing_id
            )
            avg_result = await session.exec(stmt)  # type: ignore[arg-type]
            avg_val = avg_result.one()

            count_stmt = select(func.count()).where(
                MarketplaceReview.listing_id == review.listing_id
            )
            count_result = await session.exec(count_stmt)  # type: ignore[arg-type]
            count_val = count_result.one()

            listing.avg_rating = round(float(avg_val or 0), 2)
            listing.review_count = int(count_val)
            session.add(listing)

        await session.commit()
        await session.refresh(review)
        return review

    @staticmethod
    async def list_reviews(
        session: AsyncSession,
        listing_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MarketplaceReview], int]:
        """Return paginated reviews for a listing."""
        base = select(MarketplaceReview).where(
            MarketplaceReview.listing_id == listing_id
        )

        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await session.exec(count_stmt)  # type: ignore[arg-type]
        total: int = count_result.one()

        stmt = base.offset(offset).limit(limit).order_by(
            MarketplaceReview.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        reviews = list(result.all())
        return reviews, total

    # ── Installs ────────────────────────────────────────────────────

    @staticmethod
    async def install_listing(
        session: AsyncSession, install: MarketplaceInstall
    ) -> MarketplaceInstall:
        """Record a listing install and bump the install counter."""
        session.add(install)
        await session.flush()

        listing = await session.get(MarketplaceListing, install.listing_id)
        if listing is not None:
            listing.install_count += 1
            session.add(listing)

        await session.commit()
        await session.refresh(install)
        return install

    # ── Creator Profiles ────────────────────────────────────────────

    @staticmethod
    async def create_creator(
        session: AsyncSession, profile: CreatorProfile
    ) -> CreatorProfile:
        """Register a new creator profile."""
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile

    @staticmethod
    async def get_creator(
        session: AsyncSession, creator_id: UUID
    ) -> CreatorProfile | None:
        """Return a creator profile by ID."""
        return await session.get(CreatorProfile, creator_id)

    @staticmethod
    async def catalog(
        session: AsyncSession,
        *,
        query: str | None = None,
        category: str | None = None,
        sort: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MarketplaceListing], int]:
        """Return browsable catalog of approved listings with search/sort."""
        base = select(MarketplaceListing).where(
            MarketplaceListing.status.in_(["approved", "draft"]),  # type: ignore[union-attr]
        )
        if category is not None:
            base = base.where(MarketplaceListing.category == category)
        if query is not None:
            pattern = f"%{query}%"
            base = base.where(
                MarketplaceListing.name.ilike(pattern)  # type: ignore[union-attr]
                | MarketplaceListing.description.ilike(pattern)  # type: ignore[union-attr]
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await session.exec(count_stmt)  # type: ignore[arg-type]
        total: int = count_result.one()

        order_col = MarketplaceListing.created_at.desc()  # type: ignore[union-attr]
        if sort == "popular":
            order_col = MarketplaceListing.install_count.desc()  # type: ignore[union-attr]
        elif sort == "rating":
            order_col = MarketplaceListing.avg_rating.desc()  # type: ignore[union-attr]
        elif sort == "name":
            order_col = MarketplaceListing.name.asc()  # type: ignore[union-attr]

        stmt = base.offset(offset).limit(limit).order_by(order_col)
        result = await session.exec(stmt)
        items = list(result.all())

        return items, total

    @staticmethod
    async def install_by_id(
        session: AsyncSession,
        listing_id: UUID,
        user_id: UUID,
    ) -> MarketplaceInstall | None:
        """Install a listing by ID — creates install record and bumps counter.

        Returns None if the listing does not exist.
        """
        listing = await session.get(MarketplaceListing, listing_id)
        if listing is None:
            return None

        install = MarketplaceInstall(
            listing_id=listing_id,
            user_id=user_id,
            installed_version=listing.version,
        )
        session.add(install)

        listing.install_count += 1
        session.add(listing)

        await session.commit()
        await session.refresh(install)
        return install


__all__ = [
    "MarketplaceService",
]
