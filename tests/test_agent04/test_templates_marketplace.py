"""Tests for Templates & Marketplace — Agent 04.

Covers:
- Template service instantiation and CRUD
- Marketplace catalog browsing
- Marketplace install-by-id
- Seed templates script
- Template categories
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models import Agent, Template
from app.models.marketplace import (
    CreatorProfile,
    MarketplaceInstall,
    MarketplaceListing,
)
from app.models.template import (
    TemplateCategory,
    TemplateCreate,
    TemplateFilter,
    TemplatePage,
    TemplateRating,
    TemplateRatingCreate,
    TemplateResponse,
)
from app.services.template_service import TemplateService

# ── Fixtures ────────────────────────────────────────────────────────

TENANT = "tenant-tpl-test"
SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _user(tenant_id: str = TENANT, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="user@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=["templates:create", "templates:update", "templates:execute"],
        session_id="sess-tpl",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_session() -> AsyncMock:
    """Build a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _mock_secrets() -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_secret = AsyncMock(return_value={"key": "test-key"})
    mgr.put_secret = AsyncMock()
    return mgr


def _fake_template(**overrides: Any) -> Template:
    defaults: dict[str, Any] = dict(
        id=uuid4(),
        name="Test Template",
        description="A test template",
        category="Custom",
        definition={"model": "gpt-4o", "temperature": 0.5},
        tags=["test"],
        is_featured=False,
        usage_count=0,
        author_id=SYSTEM_USER_ID,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Template(**defaults)


# ── Template Service Legacy: instantiate ────────────────────────────


@pytest.mark.asyncio
async def test_instantiate_creates_agent() -> None:
    """Instantiating a template should create an Agent and increment usage_count."""
    template = _fake_template(usage_count=5)
    session = _mock_session()
    session.get = AsyncMock(return_value=template)

    agent = await TemplateService.instantiate(session, template.id, SYSTEM_USER_ID)

    assert agent is not None
    assert isinstance(agent, Agent)
    assert agent.name == f"{template.name} (from template)"
    assert agent.owner_id == SYSTEM_USER_ID
    assert template.usage_count == 6
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_instantiate_not_found() -> None:
    """Instantiating a missing template returns None."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    agent = await TemplateService.instantiate(session, uuid4(), SYSTEM_USER_ID)
    assert agent is None


# ── Template Service Legacy: CRUD ───────────────────────────────────


@pytest.mark.asyncio
async def test_create_template_legacy() -> None:
    """Legacy create persists template and returns it."""
    template = _fake_template()
    session = _mock_session()

    result = await TemplateService.create(session, template)

    session.add.assert_called_once_with(template)
    session.commit.assert_awaited_once()
    assert result is template


@pytest.mark.asyncio
async def test_get_template_legacy() -> None:
    """Legacy get retrieves by ID."""
    template = _fake_template()
    session = _mock_session()
    session.get = AsyncMock(return_value=template)

    result = await TemplateService.get(session, template.id)
    assert result is template


@pytest.mark.asyncio
async def test_delete_template_legacy() -> None:
    """Legacy delete removes the template."""
    template = _fake_template()
    session = _mock_session()
    session.get = AsyncMock(return_value=template)
    session.delete = AsyncMock()

    deleted = await TemplateService.delete(session, template.id)
    assert deleted is True
    session.delete.assert_awaited_once_with(template)


@pytest.mark.asyncio
async def test_delete_template_not_found() -> None:
    """Legacy delete returns False for missing template."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    deleted = await TemplateService.delete(session, uuid4())
    assert deleted is False


# ── Template Service Legacy: update ─────────────────────────────────


@pytest.mark.asyncio
async def test_update_template_legacy() -> None:
    """Legacy update applies partial changes."""
    template = _fake_template(name="Old Name")
    session = _mock_session()
    session.get = AsyncMock(return_value=template)

    result = await TemplateService.update(session, template.id, {"name": "New Name"})
    assert result is not None
    assert result.name == "New Name"


@pytest.mark.asyncio
async def test_update_template_not_found() -> None:
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await TemplateService.update(session, uuid4(), {"name": "X"})
    assert result is None


# ── Template categories ─────────────────────────────────────────────


def test_get_categories() -> None:
    """get_categories returns a non-empty list of TemplateCategory."""
    cats = TemplateService.get_categories()
    assert len(cats) >= 5
    assert all(isinstance(c, TemplateCategory) for c in cats)
    slugs = [c.slug for c in cats]
    assert "customer-service" in slugs
    assert "general" in slugs


# ── Enterprise: create_template ─────────────────────────────────────


@pytest.mark.asyncio
async def test_enterprise_create_template() -> None:
    """Enterprise create_template stores metadata and returns response."""
    user = _user()
    session = _mock_session()
    session.refresh = AsyncMock(side_effect=lambda t: None)

    data = TemplateCreate(
        name="Enterprise Test",
        description="Test",
        category="Custom",
        definition={"model": "gpt-4o"},
        tags=["test"],
    )

    with patch("app.services.template_service.check_permission"):
        result = await TemplateService.create_template(session, TENANT, user, data)

    assert isinstance(result, TemplateResponse)
    assert result.name == "Enterprise Test"
    assert result.tenant_id == TENANT
    session.commit.assert_awaited_once()


# ── Enterprise: rate_template ───────────────────────────────────────


@pytest.mark.asyncio
async def test_enterprise_rate_template() -> None:
    """Rate template updates aggregate and returns rating."""
    user = _user()
    template = _fake_template(
        definition={"model": "gpt-4o", "_meta": {"avg_rating": 4.0, "review_count": 2}},
    )
    session = _mock_session()
    session.get = AsyncMock(return_value=template)

    rating_data = TemplateRatingCreate(rating=5, review="Excellent!")

    with patch("app.services.template_service.check_permission"):
        result = await TemplateService.rate_template(session, TENANT, user, template.id, rating_data)

    assert isinstance(result, TemplateRating)
    assert result.rating == 5
    assert result.review == "Excellent!"


@pytest.mark.asyncio
async def test_enterprise_rate_template_not_found() -> None:
    user = _user()
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    rating_data = TemplateRatingCreate(rating=3)

    with patch("app.services.template_service.check_permission"):
        result = await TemplateService.rate_template(session, TENANT, user, uuid4(), rating_data)

    assert result is None


# ── Enterprise: fork_template ───────────────────────────────────────


@pytest.mark.asyncio
async def test_enterprise_fork_template() -> None:
    """Fork creates a copy with 'fork' suffix."""
    user = _user()
    template = _fake_template(
        name="Original",
        definition={"model": "gpt-4o", "_meta": {"difficulty": "beginner"}},
    )
    session = _mock_session()
    session.get = AsyncMock(return_value=template)
    session.refresh = AsyncMock(side_effect=lambda t: None)

    with patch("app.services.template_service.check_permission"):
        result = await TemplateService.fork_template(session, TENANT, user, template.id)

    assert result is not None
    assert isinstance(result, TemplateResponse)
    assert "(fork)" in result.name


@pytest.mark.asyncio
async def test_enterprise_fork_template_not_found() -> None:
    user = _user()
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("app.services.template_service.check_permission"):
        result = await TemplateService.fork_template(session, TENANT, user, uuid4())

    assert result is None


# ── Seed Templates ──────────────────────────────────────────────────


def test_seed_templates_data() -> None:
    """Seed data contains >= 20 templates with required fields."""
    from scripts.seed_templates import SEED_TEMPLATES

    assert len(SEED_TEMPLATES) >= 20
    for tpl in SEED_TEMPLATES:
        assert "name" in tpl
        assert "description" in tpl
        assert "category" in tpl
        assert "tags" in tpl
        assert isinstance(tpl["tags"], list)
        assert "definition" in tpl
        assert isinstance(tpl["definition"], dict)


def test_seed_templates_categories() -> None:
    """Seed templates span multiple categories."""
    from scripts.seed_templates import SEED_TEMPLATES

    categories = {t["category"] for t in SEED_TEMPLATES}
    assert len(categories) >= 5


def test_seed_templates_unique_names() -> None:
    """All seed template names are unique."""
    from scripts.seed_templates import SEED_TEMPLATES

    names = [t["name"] for t in SEED_TEMPLATES]
    assert len(names) == len(set(names))


# ── Marketplace Service: catalog & install_by_id ────────────────────


@pytest.mark.asyncio
async def test_marketplace_install_by_id_not_found() -> None:
    """install_by_id returns None when listing doesn't exist."""
    from app.services.marketplace import MarketplaceService

    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    result = await MarketplaceService.install_by_id(session, uuid4(), SYSTEM_USER_ID)
    assert result is None


@pytest.mark.asyncio
async def test_marketplace_install_by_id_success() -> None:
    """install_by_id creates install record and bumps counter."""
    from app.services.marketplace import MarketplaceService

    creator_id = uuid4()
    listing = MarketplaceListing(
        id=uuid4(),
        name="Test Listing",
        description="desc",
        category="agents",
        version="1.0.0",
        license="MIT",
        status="approved",
        creator_id=creator_id,
        install_count=3,
    )
    session = _mock_session()
    session.get = AsyncMock(return_value=listing)

    result = await MarketplaceService.install_by_id(session, listing.id, SYSTEM_USER_ID)

    assert result is not None
    assert isinstance(result, MarketplaceInstall)
    assert listing.install_count == 4
    session.commit.assert_awaited_once()
