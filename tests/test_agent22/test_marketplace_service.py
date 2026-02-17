"""Tests for MarketplaceService — publisher, packages, installs, ratings, signatures, reviews."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.marketplace import (
    CreatorProfile,
    Installation,
    MarketplaceCategory,
    MarketplaceListing,
    MarketplacePackage,
    PackageRating,
    PackageSearchResult,
    PackageSubmission,
    Publisher,
    PublisherAnalytics,
    PublisherProfile,
    ReviewResult,
    SignatureVerification,
)
from app.services.marketplace_service import MarketplaceService

# ── Fixtures ────────────────────────────────────────────────────────

TENANT = "tenant-marketplace-test"


def _user(tenant_id: str = TENANT, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="pub@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=["marketplace:create", "marketplace:read"],
        session_id="sess-mkt",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_secrets() -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_secret = AsyncMock(return_value={"fingerprint": "ABCD1234"})
    mgr.put_secret = AsyncMock()
    return mgr


def _mock_session() -> AsyncMock:
    """Build a mock AsyncSession with execute/add/flush/commit."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _publisher_profile(**overrides: Any) -> PublisherProfile:
    defaults: dict[str, Any] = dict(
        display_name="Test Publisher",
        email="pub@example.com",
        bio="A test publisher",
        github_url="https://github.com/test",
    )
    defaults.update(overrides)
    return PublisherProfile(**defaults)


def _package_sub(**overrides: Any) -> PackageSubmission:
    defaults: dict[str, Any] = dict(
        name="my-agent",
        description="A test agent",
        category="agents",
        license="MIT",
        version="1.0.0",
        source_url="https://github.com/test/my-agent",
    )
    defaults.update(overrides)
    return PackageSubmission(**defaults)


def _fake_creator(user_id: str) -> CreatorProfile:
    return CreatorProfile(
        id=uuid4(),
        user_id=UUID(user_id),
        display_name="Test Publisher",
        is_verified=True,
    )


def _fake_listing(creator_id: UUID, **overrides: Any) -> MarketplaceListing:
    defaults: dict[str, Any] = dict(
        id=uuid4(),
        name="my-agent",
        description="desc",
        category="agents",
        version="1.0.0",
        license="MIT",
        status="approved",
        creator_id=creator_id,
        install_count=0,
        avg_rating=0.0,
        review_count=0,
        extra_metadata={"signed": True, "signature_fingerprint": "ABCD1234"},
    )
    defaults.update(overrides)
    return MarketplaceListing(**defaults)


# ── register_publisher ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_publisher_success() -> None:
    user = _user()
    session = _mock_session()
    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         patch("app.services.marketplace_service.AuditLogService.create", new_callable=AsyncMock):
        pub = await svc.register_publisher(TENANT, user, _publisher_profile(), session)

    assert isinstance(pub, Publisher)
    assert pub.display_name == "Test Publisher"
    assert pub.verified is False
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_publisher_audit_logged() -> None:
    user = _user()
    session = _mock_session()
    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         patch("app.services.marketplace_service.AuditLogService.create", new_callable=AsyncMock) as mock_audit:
        await svc.register_publisher(TENANT, user, _publisher_profile(), session)

    mock_audit.assert_awaited_once()
    call_kwargs = mock_audit.call_args
    assert call_kwargs[1]["action"] == "marketplace.publisher.registered" or \
           call_kwargs[0][2] == "marketplace.publisher.registered"


# ── publish_package ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_package_success() -> None:
    user = _user()
    creator = _fake_creator(user.id)
    session = _mock_session()

    # execute returns the creator when queried
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = creator
    session.execute = AsyncMock(return_value=mock_result)

    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         patch("app.services.marketplace_service.AuditLogService.create", new_callable=AsyncMock):
        pkg = await svc.publish_package(TENANT, user, _package_sub(), session)

    assert isinstance(pkg, MarketplacePackage)
    assert pkg.name == "my-agent"
    assert pkg.verified_signature is True
    assert pkg.publisher.display_name == "Test Publisher"


@pytest.mark.asyncio
async def test_publish_package_incompatible_license() -> None:
    user = _user()
    session = _mock_session()
    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         pytest.raises(ValueError, match="not in the approved list"):
        await svc.publish_package(
            TENANT, user, _package_sub(license="GPL-3.0"), session,
        )


@pytest.mark.asyncio
async def test_publish_package_no_publisher_profile() -> None:
    user = _user()
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         pytest.raises(ValueError, match="register as a publisher"):
        await svc.publish_package(TENANT, user, _package_sub(), session)


# ── install_package ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_package_success() -> None:
    user = _user()
    listing = _fake_listing(uuid4())
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    session.execute = AsyncMock(return_value=mock_result)

    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         patch("app.services.marketplace_service.AuditLogService.create", new_callable=AsyncMock):
        result = await svc.install_package(TENANT, user, listing.id, session)

    assert isinstance(result, Installation)
    assert result.package_id == listing.id
    assert result.tenant_id == TENANT


@pytest.mark.asyncio
async def test_install_package_not_found() -> None:
    user = _user()
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         pytest.raises(ValueError, match="not found or not approved"):
        await svc.install_package(TENANT, user, uuid4(), session)


# ── search_packages ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_packages_empty() -> None:
    session = _mock_session()
    # First execute: count query
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    # Second execute: listing query
    listing_result = MagicMock()
    listing_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[count_result, listing_result])

    svc = MarketplaceService(_mock_secrets())
    result = await svc.search_packages(TENANT, None, None, session)

    assert isinstance(result, PackageSearchResult)
    assert result.total == 0
    assert result.packages == []


@pytest.mark.asyncio
async def test_search_packages_with_results() -> None:
    creator = _fake_creator(str(uuid4()))
    listing = _fake_listing(creator.id)
    session = _mock_session()

    count_result = MagicMock()
    count_result.scalar.return_value = 1
    listing_result = MagicMock()
    listing_result.scalars.return_value.all.return_value = [listing]
    creator_result = MagicMock()
    creator_result.scalar_one_or_none.return_value = creator
    session.execute = AsyncMock(side_effect=[count_result, listing_result, creator_result])

    svc = MarketplaceService(_mock_secrets())
    result = await svc.search_packages(TENANT, "my-agent", None, session)

    assert result.total == 1
    assert len(result.packages) == 1
    assert result.packages[0].name == "my-agent"


# ── rate_package ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_package_success() -> None:
    user = _user()
    listing = _fake_listing(uuid4(), review_count=0, avg_rating=0.0)
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    session.execute = AsyncMock(return_value=mock_result)

    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         patch("app.services.marketplace_service.AuditLogService.create", new_callable=AsyncMock):
        rating = await svc.rate_package(TENANT, user, listing.id, 5, "Great!", session)

    assert isinstance(rating, PackageRating)
    assert rating.rating == 5
    assert rating.review == "Great!"


@pytest.mark.asyncio
async def test_rate_package_not_found() -> None:
    user = _user()
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         pytest.raises(ValueError, match="not found"):
        await svc.rate_package(TENANT, user, uuid4(), 4, None, session)


# ── get_publisher_analytics ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_publisher_analytics_success() -> None:
    user = _user()
    creator = _fake_creator(user.id)
    listing = _fake_listing(creator.id, install_count=10, review_count=2, avg_rating=4.5)
    session = _mock_session()

    creator_result = MagicMock()
    creator_result.scalar_one_or_none.return_value = creator
    listings_result = MagicMock()
    listings_result.scalars.return_value.all.return_value = [listing]
    session.execute = AsyncMock(side_effect=[creator_result, listings_result])

    secrets = _mock_secrets()
    svc = MarketplaceService(secrets)

    with patch("app.services.marketplace_service.check_permission"):
        analytics = await svc.get_publisher_analytics(TENANT, user, session)

    assert isinstance(analytics, PublisherAnalytics)
    assert analytics.total_installs == 10
    assert analytics.total_ratings == 2


@pytest.mark.asyncio
async def test_publisher_analytics_no_profile() -> None:
    user = _user()
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    with patch("app.services.marketplace_service.check_permission"), \
         pytest.raises(ValueError, match="not found"):
        await svc.get_publisher_analytics(TENANT, user, session)


# ── verify_package_signature ────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_signature_valid() -> None:
    listing = _fake_listing(uuid4())
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    sig = await svc.verify_package_signature(listing.id, session)

    assert isinstance(sig, SignatureVerification)
    assert sig.valid is True
    assert sig.signer == "ABCD1234"
    assert sig.algorithm == "GPG-RSA4096"


@pytest.mark.asyncio
async def test_verify_signature_not_found() -> None:
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    with pytest.raises(ValueError, match="not found"):
        await svc.verify_package_signature(uuid4(), session)


# ── run_review_pipeline ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_pipeline_passes() -> None:
    listing = _fake_listing(uuid4(), definition={})
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    result = await svc.run_review_pipeline(listing.id, session)

    assert isinstance(result, ReviewResult)
    assert result.passed is True
    assert result.license_compatible is True
    assert result.security_score >= 70.0


@pytest.mark.asyncio
async def test_review_pipeline_bad_license() -> None:
    listing = _fake_listing(uuid4(), license="GPL-3.0", definition={})
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    result = await svc.run_review_pipeline(listing.id, session)

    assert result.license_compatible is False
    assert any("license" in f.lower() for f in result.findings)


@pytest.mark.asyncio
async def test_review_pipeline_secret_leak_detection() -> None:
    listing = _fake_listing(
        uuid4(),
        definition={"config": "api_key=abc123"},
    )
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    session.execute = AsyncMock(return_value=mock_result)
    svc = MarketplaceService(_mock_secrets())

    result = await svc.run_review_pipeline(listing.id, session)

    assert any("secret" in f.lower() or "api_key" in f.lower() for f in result.findings)


# ── list_categories ─────────────────────────────────────────────────


def test_list_categories() -> None:
    svc = MarketplaceService(_mock_secrets())
    cats = svc.list_categories()
    assert len(cats) == 5
    slugs = [c.slug for c in cats]
    assert "agents" in slugs
    assert "connectors" in slugs
