"""Unit tests for MarketplaceService — listings CRUD, search, approval,
reviews, installs, and creator profile operations.

All tests mock the async database session so no live DB is required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.models.marketplace import (
    CreatorProfile,
    MarketplaceInstall,
    MarketplaceListing,
    MarketplaceReview,
)
from app.services.marketplace import MarketplaceService

# ── Fixed UUIDs (valid hex only: 0-9, a-f) ─────────────────────────

CREATOR_ID = UUID("aa000001-0001-0001-0001-000000000001")
LISTING_ID = UUID("bb000001-0001-0001-0001-000000000001")
USER_ID = UUID("cc000001-0001-0001-0001-000000000001")
REVIEW_ID = UUID("dd000001-0001-0001-0001-000000000001")
INSTALL_ID = UUID("ee000001-0001-0001-0001-000000000001")
LISTING_ID_2 = UUID("bb000002-0002-0002-0002-000000000002")
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Factories ───────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _creator(
    *,
    cid: UUID = CREATOR_ID,
    user_id: UUID = USER_ID,
    display_name: str = "Test Creator",
    bio: str | None = "A test creator bio",
    is_verified: bool = False,
) -> CreatorProfile:
    """Build a CreatorProfile with controllable fields."""
    return CreatorProfile(
        id=cid,
        user_id=user_id,
        display_name=display_name,
        bio=bio,
        is_verified=is_verified,
        created_at=NOW,
        updated_at=NOW,
    )


def _listing(
    *,
    lid: UUID = LISTING_ID,
    name: str = "Test Agent",
    description: str | None = "An agent for testing",
    category: str = "agents",
    tags: list[str] | None = None,
    status: str = "draft",
    creator_id: UUID = CREATOR_ID,
    install_count: int = 0,
    avg_rating: float = 0.0,
    review_count: int = 0,
) -> MarketplaceListing:
    """Build a MarketplaceListing with controllable fields."""
    return MarketplaceListing(
        id=lid,
        name=name,
        description=description,
        category=category,
        tags=tags if tags is not None else ["test", "ai"],
        status=status,
        creator_id=creator_id,
        install_count=install_count,
        avg_rating=avg_rating,
        review_count=review_count,
        version="0.1.0",
        license="MIT",
        definition={},
        screenshots=[],
        extra_metadata={},
        created_at=NOW,
        updated_at=NOW,
    )


def _review(
    *,
    rid: UUID = REVIEW_ID,
    listing_id: UUID = LISTING_ID,
    user_id: UUID = USER_ID,
    rating: int = 4,
    comment: str | None = "Great agent!",
) -> MarketplaceReview:
    """Build a MarketplaceReview with controllable fields."""
    return MarketplaceReview(
        id=rid,
        listing_id=listing_id,
        user_id=user_id,
        rating=rating,
        comment=comment,
        created_at=NOW,
        updated_at=NOW,
    )


def _install(
    *,
    iid: UUID = INSTALL_ID,
    listing_id: UUID = LISTING_ID,
    user_id: UUID = USER_ID,
    installed_version: str = "0.1.0",
) -> MarketplaceInstall:
    """Build a MarketplaceInstall with controllable fields."""
    return MarketplaceInstall(
        id=iid,
        listing_id=listing_id,
        user_id=user_id,
        installed_version=installed_version,
        created_at=NOW,
    )


def _exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object whose .all() and .one() work."""
    result = MagicMock()
    result.all.return_value = rows
    result.one.return_value = rows[0] if rows else 0
    return result


def _scalar_result(value: Any) -> MagicMock:
    """Create a mock result returning a single scalar via .one()."""
    result = MagicMock()
    result.one.return_value = value
    return result


# ═══════════════════════════════════════════════════════════════════
# Listing CRUD
# ═══════════════════════════════════════════════════════════════════


class TestCreateListing:
    """Tests for MarketplaceService.create_listing."""

    @pytest.mark.asyncio
    async def test_create_listing_adds_and_commits(self) -> None:
        """Listing is added, committed, and refreshed."""
        session = _mock_session()
        listing = _listing()

        result = await MarketplaceService.create_listing(session, listing)

        session.add.assert_called_once_with(listing)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(listing)
        assert result is listing

    @pytest.mark.asyncio
    async def test_create_listing_preserves_default_status(self) -> None:
        """New listings default to 'draft' status."""
        session = _mock_session()
        listing = _listing()

        result = await MarketplaceService.create_listing(session, listing)

        assert result.status == "draft"

    @pytest.mark.asyncio
    async def test_create_listing_with_custom_category(self) -> None:
        """Listings can be created with any valid category."""
        session = _mock_session()
        listing = _listing(category="templates")

        result = await MarketplaceService.create_listing(session, listing)

        assert result.category == "templates"


class TestGetListing:
    """Tests for MarketplaceService.get_listing."""

    @pytest.mark.asyncio
    async def test_get_listing_found(self) -> None:
        """Returns listing when found by ID."""
        session = _mock_session()
        listing = _listing()
        session.get = AsyncMock(return_value=listing)

        result = await MarketplaceService.get_listing(session, LISTING_ID)

        session.get.assert_awaited_once_with(MarketplaceListing, LISTING_ID)
        assert result is listing

    @pytest.mark.asyncio
    async def test_get_listing_not_found(self) -> None:
        """Returns None when listing does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await MarketplaceService.get_listing(session, LISTING_ID)

        assert result is None


class TestUpdateListing:
    """Tests for MarketplaceService.update_listing."""

    @pytest.mark.asyncio
    async def test_update_listing_applies_fields(self) -> None:
        """Valid fields are applied to the listing."""
        session = _mock_session()
        listing = _listing()
        session.get = AsyncMock(return_value=listing)

        result = await MarketplaceService.update_listing(
            session, LISTING_ID, {"name": "Updated Name", "description": "New desc"}
        )

        assert result is not None
        assert result.name == "Updated Name"
        assert result.description == "New desc"
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(listing)

    @pytest.mark.asyncio
    async def test_update_listing_ignores_unknown_fields(self) -> None:
        """Fields not on the model are silently ignored."""
        session = _mock_session()
        listing = _listing()
        session.get = AsyncMock(return_value=listing)

        result = await MarketplaceService.update_listing(
            session, LISTING_ID, {"nonexistent_field": "value"}
        )

        assert result is not None
        assert result.name == "Test Agent"  # unchanged

    @pytest.mark.asyncio
    async def test_update_listing_not_found(self) -> None:
        """Returns None when listing does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await MarketplaceService.update_listing(
            session, LISTING_ID, {"name": "Updated"}
        )

        assert result is None
        session.commit.assert_not_awaited()


class TestDeleteListing:
    """Tests for MarketplaceService.delete_listing."""

    @pytest.mark.asyncio
    async def test_delete_listing_success(self) -> None:
        """Returns True and deletes when listing exists."""
        session = _mock_session()
        listing = _listing()
        session.get = AsyncMock(return_value=listing)

        result = await MarketplaceService.delete_listing(session, LISTING_ID)

        assert result is True
        session.delete.assert_awaited_once_with(listing)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_listing_not_found(self) -> None:
        """Returns False when listing does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await MarketplaceService.delete_listing(session, LISTING_ID)

        assert result is False
        session.delete.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════
# Search Listings
# ═══════════════════════════════════════════════════════════════════


class TestSearchListings:
    """Tests for MarketplaceService.search_listings."""

    @pytest.mark.asyncio
    async def test_search_returns_items_and_count(self) -> None:
        """Basic search returns tuple of (items, total)."""
        session = _mock_session()
        listing = _listing()
        # First exec call: count query; second: items query
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([listing])]
        )

        items, total = await MarketplaceService.search_listings(session)

        assert total == 1
        assert len(items) == 1
        assert items[0] is listing

    @pytest.mark.asyncio
    async def test_search_empty_results(self) -> None:
        """Search with no matches returns empty list and zero count."""
        session = _mock_session()
        session.exec = AsyncMock(
            side_effect=[_scalar_result(0), _exec_result([])]
        )

        items, total = await MarketplaceService.search_listings(session)

        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_search_with_status_filter(self) -> None:
        """Status filter is applied to the query."""
        session = _mock_session()
        listing = _listing(status="approved")
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([listing])]
        )

        items, total = await MarketplaceService.search_listings(
            session, status="approved"
        )

        assert total == 1
        assert items[0].status == "approved"

    @pytest.mark.asyncio
    async def test_search_with_category_filter(self) -> None:
        """Category filter narrows results."""
        session = _mock_session()
        listing = _listing(category="templates")
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([listing])]
        )

        items, total = await MarketplaceService.search_listings(
            session, category="templates"
        )

        assert total == 1
        assert items[0].category == "templates"

    @pytest.mark.asyncio
    async def test_search_with_creator_id_filter(self) -> None:
        """Creator ID filter narrows results."""
        session = _mock_session()
        listing = _listing(creator_id=CREATOR_ID)
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([listing])]
        )

        items, total = await MarketplaceService.search_listings(
            session, creator_id=CREATOR_ID
        )

        assert total == 1
        assert items[0].creator_id == CREATOR_ID

    @pytest.mark.asyncio
    async def test_search_with_query_text(self) -> None:
        """Text query filters by name/description ilike."""
        session = _mock_session()
        listing = _listing(name="Smart Agent")
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([listing])]
        )

        items, total = await MarketplaceService.search_listings(
            session, query="Smart"
        )

        assert total == 1
        assert items[0].name == "Smart Agent"

    @pytest.mark.asyncio
    async def test_search_with_tag_filter(self) -> None:
        """Tag filter is applied in-memory after DB query."""
        session = _mock_session()
        matching = _listing(tags=["ai", "nlp"])
        non_matching = _listing(lid=LISTING_ID_2, tags=["data"])
        session.exec = AsyncMock(
            side_effect=[
                _scalar_result(2),
                _exec_result([matching, non_matching]),
            ]
        )

        items, total = await MarketplaceService.search_listings(
            session, tag="ai"
        )

        assert total == 1
        assert len(items) == 1
        assert "ai" in items[0].tags

    @pytest.mark.asyncio
    async def test_search_tag_filter_no_match(self) -> None:
        """Tag filter that matches nothing returns empty."""
        session = _mock_session()
        listing = _listing(tags=["data"])
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([listing])]
        )

        items, total = await MarketplaceService.search_listings(
            session, tag="nonexistent"
        )

        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_search_pagination_params_forwarded(self) -> None:
        """Limit and offset parameters are accepted."""
        session = _mock_session()
        session.exec = AsyncMock(
            side_effect=[_scalar_result(0), _exec_result([])]
        )

        items, total = await MarketplaceService.search_listings(
            session, limit=5, offset=10
        )

        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_search_tag_filter_with_none_tags(self) -> None:
        """Listings with None tags are excluded by tag filter."""
        session = _mock_session()
        listing = _listing()
        listing.tags = None  # type: ignore[assignment]
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([listing])]
        )

        items, total = await MarketplaceService.search_listings(
            session, tag="ai"
        )

        assert total == 0
        assert items == []


# ═══════════════════════════════════════════════════════════════════
# Approve Listing
# ═══════════════════════════════════════════════════════════════════


class TestApproveListing:
    """Tests for MarketplaceService.approve_listing."""

    @pytest.mark.asyncio
    async def test_approve_listing_success(self) -> None:
        """Transitions status to 'approved'."""
        session = _mock_session()
        listing = _listing(status="pending_review")
        session.get = AsyncMock(return_value=listing)

        result = await MarketplaceService.approve_listing(session, LISTING_ID)

        assert result is not None
        assert result.status == "approved"
        session.add.assert_called_with(listing)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(listing)

    @pytest.mark.asyncio
    async def test_approve_listing_not_found(self) -> None:
        """Returns None when listing does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await MarketplaceService.approve_listing(session, LISTING_ID)

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approve_listing_from_draft(self) -> None:
        """Approve works even when current status is 'draft'."""
        session = _mock_session()
        listing = _listing(status="draft")
        session.get = AsyncMock(return_value=listing)

        result = await MarketplaceService.approve_listing(session, LISTING_ID)

        assert result is not None
        assert result.status == "approved"


# ═══════════════════════════════════════════════════════════════════
# Reviews
# ═══════════════════════════════════════════════════════════════════


class TestCreateReview:
    """Tests for MarketplaceService.create_review."""

    @pytest.mark.asyncio
    async def test_create_review_updates_aggregate(self) -> None:
        """Review is saved and listing aggregates are recomputed."""
        session = _mock_session()
        review = _review(rating=4)
        listing = _listing(avg_rating=0.0, review_count=0)
        session.get = AsyncMock(return_value=listing)
        # Two exec calls: avg query, count query
        session.exec = AsyncMock(
            side_effect=[_scalar_result(4.0), _scalar_result(1)]
        )

        result = await MarketplaceService.create_review(session, review)

        session.add.assert_any_call(review)
        session.flush.assert_awaited_once()
        assert listing.avg_rating == 4.0
        assert listing.review_count == 1
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(review)
        assert result is review

    @pytest.mark.asyncio
    async def test_create_review_listing_not_found(self) -> None:
        """Review is still saved even if listing doesn't exist."""
        session = _mock_session()
        review = _review()
        session.get = AsyncMock(return_value=None)

        result = await MarketplaceService.create_review(session, review)

        session.add.assert_called_once_with(review)
        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(review)
        assert result is review

    @pytest.mark.asyncio
    async def test_create_review_avg_handles_none(self) -> None:
        """When avg returns None (edge case), avg_rating is set to 0.0."""
        session = _mock_session()
        review = _review(rating=5)
        listing = _listing()
        session.get = AsyncMock(return_value=listing)
        session.exec = AsyncMock(
            side_effect=[_scalar_result(None), _scalar_result(0)]
        )

        await MarketplaceService.create_review(session, review)

        assert listing.avg_rating == 0.0
        assert listing.review_count == 0

    @pytest.mark.asyncio
    async def test_create_review_avg_rounds_to_two_decimals(self) -> None:
        """Average rating is rounded to 2 decimal places."""
        session = _mock_session()
        review = _review(rating=3)
        listing = _listing()
        session.get = AsyncMock(return_value=listing)
        session.exec = AsyncMock(
            side_effect=[_scalar_result(3.666666), _scalar_result(3)]
        )

        await MarketplaceService.create_review(session, review)

        assert listing.avg_rating == 3.67


class TestListReviews:
    """Tests for MarketplaceService.list_reviews."""

    @pytest.mark.asyncio
    async def test_list_reviews_returns_items_and_count(self) -> None:
        """Returns paginated reviews with total count."""
        session = _mock_session()
        review = _review()
        session.exec = AsyncMock(
            side_effect=[_scalar_result(1), _exec_result([review])]
        )

        reviews, total = await MarketplaceService.list_reviews(
            session, LISTING_ID
        )

        assert total == 1
        assert len(reviews) == 1
        assert reviews[0] is review

    @pytest.mark.asyncio
    async def test_list_reviews_empty(self) -> None:
        """Returns empty list when no reviews exist."""
        session = _mock_session()
        session.exec = AsyncMock(
            side_effect=[_scalar_result(0), _exec_result([])]
        )

        reviews, total = await MarketplaceService.list_reviews(
            session, LISTING_ID
        )

        assert total == 0
        assert reviews == []

    @pytest.mark.asyncio
    async def test_list_reviews_pagination(self) -> None:
        """Limit and offset are accepted."""
        session = _mock_session()
        session.exec = AsyncMock(
            side_effect=[_scalar_result(0), _exec_result([])]
        )

        reviews, total = await MarketplaceService.list_reviews(
            session, LISTING_ID, limit=5, offset=10
        )

        assert total == 0
        assert reviews == []


# ═══════════════════════════════════════════════════════════════════
# Installs
# ═══════════════════════════════════════════════════════════════════


class TestInstallListing:
    """Tests for MarketplaceService.install_listing."""

    @pytest.mark.asyncio
    async def test_install_listing_bumps_counter(self) -> None:
        """Install record is saved and listing install_count is incremented."""
        session = _mock_session()
        install = _install()
        listing = _listing(install_count=5)
        session.get = AsyncMock(return_value=listing)

        result = await MarketplaceService.install_listing(session, install)

        session.add.assert_any_call(install)
        session.flush.assert_awaited_once()
        assert listing.install_count == 6
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(install)
        assert result is install

    @pytest.mark.asyncio
    async def test_install_listing_listing_not_found(self) -> None:
        """Install is still saved even if listing doesn't exist."""
        session = _mock_session()
        install = _install()
        session.get = AsyncMock(return_value=None)

        result = await MarketplaceService.install_listing(session, install)

        session.add.assert_called_once_with(install)
        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(install)
        assert result is install

    @pytest.mark.asyncio
    async def test_install_listing_counter_starts_at_zero(self) -> None:
        """First install on a listing moves count from 0 to 1."""
        session = _mock_session()
        install = _install()
        listing = _listing(install_count=0)
        session.get = AsyncMock(return_value=listing)

        await MarketplaceService.install_listing(session, install)

        assert listing.install_count == 1


# ═══════════════════════════════════════════════════════════════════
# Creator Profiles
# ═══════════════════════════════════════════════════════════════════


class TestCreatorCRUD:
    """Tests for creator profile operations."""

    @pytest.mark.asyncio
    async def test_create_creator(self) -> None:
        """Creator profile is added, committed, and refreshed."""
        session = _mock_session()
        profile = _creator()

        result = await MarketplaceService.create_creator(session, profile)

        session.add.assert_called_once_with(profile)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(profile)
        assert result is profile
        assert result.display_name == "Test Creator"

    @pytest.mark.asyncio
    async def test_get_creator_found(self) -> None:
        """Returns creator profile when found."""
        session = _mock_session()
        profile = _creator()
        session.get = AsyncMock(return_value=profile)

        result = await MarketplaceService.get_creator(session, CREATOR_ID)

        session.get.assert_awaited_once_with(CreatorProfile, CREATOR_ID)
        assert result is profile

    @pytest.mark.asyncio
    async def test_get_creator_not_found(self) -> None:
        """Returns None when creator profile does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await MarketplaceService.get_creator(session, CREATOR_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_create_creator_verified(self) -> None:
        """Creator can be created with is_verified=True."""
        session = _mock_session()
        profile = _creator(is_verified=True)

        result = await MarketplaceService.create_creator(session, profile)

        assert result.is_verified is True

    @pytest.mark.asyncio
    async def test_create_creator_no_bio(self) -> None:
        """Creator can be created without a bio."""
        session = _mock_session()
        profile = _creator(bio=None)

        result = await MarketplaceService.create_creator(session, profile)

        assert result.bio is None
