"""Template Library & Marketplace API routes.

Enterprise-hardened endpoints with JWT auth, RBAC, tenant isolation,
and audit logging.  Preserves backward-compatible legacy endpoints.
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
from app.middleware.rbac import require_permission
from app.models import Template
from app.models.template import (
    InstalledTemplate,
    InstallConfig,
    TemplateCategory,
    TemplateCreate as EnterpriseTemplateCreate,
    TemplateFilter,
    TemplatePage,
    TemplateRating,
    TemplateRatingCreate,
    TemplateResponse,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.template_service import TemplateService
from starlette.responses import Response

router = APIRouter(prefix="/templates", tags=["templates"])


# ── Legacy request schemas (preserved for backward compat) ──────────


class TemplateCreate(BaseModel):
    """Payload for creating a template (legacy)."""

    name: str
    description: str | None = None
    category: str
    definition: dict[str, Any]
    tags: list[str] = PField(default_factory=list)
    is_featured: bool = False
    author_id: UUID = UUID("00000000-0000-0000-0000-000000000001")


class TemplateUpdate(BaseModel):
    """Payload for updating a template (partial, legacy)."""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    definition: dict[str, Any] | None = None
    tags: list[str] | None = None
    is_featured: bool | None = None


class InstantiateRequest(BaseModel):
    """Payload for instantiating a template into an agent (legacy)."""

    owner_id: UUID


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Enterprise routes ────────────────────────────────────────────────


@router.get("/categories")
async def list_categories() -> dict[str, Any]:
    """List all template categories."""
    cats = TemplateService.get_categories()
    return {
        "data": [c.model_dump() for c in cats],
        "meta": _meta(),
    }


@router.get("/search")
async def search_templates(
    q: str = Query(..., min_length=1),
    semantic: bool = Query(default=False),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search templates with text or semantic matching."""
    results = await TemplateService.search_templates(
        session,
        user.tenant_id,
        q,
        semantic=semantic,
    )
    return {
        "data": [r.model_dump(mode="json") for r in results],
        "meta": _meta(),
    }


@router.get("/")
async def list_templates(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    is_featured: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    difficulty: str | None = Query(default=None),
    min_rating: float | None = Query(default=None, ge=0.0, le=5.0),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser | None = Depends(get_current_user),
) -> dict[str, Any]:
    """List templates with pagination and filters.

    Supports both legacy offset-based and enterprise page-based pagination.
    When authenticated, returns tenant-scoped enterprise response.
    """
    if user is not None:
        from app.models.template import TemplateDifficulty

        tags_list = [tag] if tag else None
        diff = None
        if difficulty:
            try:
                diff = TemplateDifficulty(difficulty)
            except ValueError:
                pass

        filters = TemplateFilter(
            category=category,
            tags=tags_list,
            difficulty=diff,
            min_rating=min_rating,
            search_query=search,
            is_featured=is_featured,
        )
        result = await TemplateService.list_templates(
            session,
            user.tenant_id,
            filters,
            page=page,
            page_size=page_size,
        )
        return {
            "data": [t.model_dump(mode="json") for t in result.items],
            "meta": _meta(
                pagination={
                    "total": result.total,
                    "page": result.page,
                    "page_size": result.page_size,
                    "limit": limit,
                    "offset": offset,
                },
            ),
        }

    # Legacy fallback (no auth)
    templates, total = await TemplateService.list(
        session,
        category=category,
        tag=tag,
        is_featured=is_featured,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [t.model_dump(mode="json") for t in templates],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.post("/", status_code=201)
async def create_template(
    body: TemplateCreate,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new template."""
    if user is not None:
        enterprise_data = EnterpriseTemplateCreate(
            name=body.name,
            description=body.description,
            category=body.category,
            definition=body.definition,
            tags=body.tags,
            is_featured=body.is_featured,
        )
        resp = await TemplateService.create_template(
            session,
            user.tenant_id,
            user,
            enterprise_data,
        )
        return {
            "data": resp.model_dump(mode="json"),
            "meta": _meta(),
        }

    # Legacy fallback
    template = Template(**body.model_dump())
    created = await TemplateService.create(session, template)
    return {
        "data": created.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/{template_id}")
async def get_template(
    template_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a single template by ID."""
    if user is not None:
        resp = await TemplateService.get_template(session, user.tenant_id, template_id)
        if resp is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return {
            "data": resp.model_dump(mode="json"),
            "meta": _meta(),
        }

    # Legacy fallback
    template = await TemplateService.get(session, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "data": template.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/{template_id}/publish", status_code=200)
async def publish_template(
    template_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("templates", "update")),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Publish a template to the marketplace with Vault-based signature."""
    resp = await TemplateService.publish_template(
        session,
        user.tenant_id,
        user,
        template_id,
        secrets,
    )
    if resp is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "data": resp.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/{template_id}/install", status_code=201)
async def install_template(
    template_id: UUID,
    body: InstallConfig | None = None,
    user: AuthenticatedUser = Depends(require_permission("templates", "execute")),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Install a template with config wizard and credential checks."""
    overrides = body.overrides if body else {}
    result = await TemplateService.install_template(
        session,
        user.tenant_id,
        user,
        template_id,
        secrets,
        config_overrides=overrides,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/{template_id}/rate", status_code=201)
async def rate_template(
    template_id: UUID,
    body: TemplateRatingCreate,
    user: AuthenticatedUser = Depends(require_permission("templates", "update")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Rate and review a template."""
    result = await TemplateService.rate_template(
        session,
        user.tenant_id,
        user,
        template_id,
        body,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/{template_id}/fork", status_code=201)
async def fork_template(
    template_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("templates", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Fork a template for customisation."""
    result = await TemplateService.fork_template(
        session,
        user.tenant_id,
        user,
        template_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


# ── Legacy routes (preserved) ───────────────────────────────────────


@router.put("/{template_id}")
async def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an existing template (legacy)."""
    data = body.model_dump(exclude_unset=True)
    template = await TemplateService.update(session, template_id, data)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "data": template.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.delete("/{template_id}", status_code=204, response_class=Response)
async def delete_template(
    template_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a template (legacy)."""
    deleted = await TemplateService.delete(session, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    return Response(status_code=204)


@router.post("/{template_id}/instantiate", status_code=201)
async def instantiate_template(
    template_id: UUID,
    body: InstantiateRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Instantiate a template — creates a new Agent (legacy)."""
    agent = await TemplateService.instantiate(session, template_id, body.owner_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "data": agent.model_dump(mode="json"),
        "meta": _meta(),
    }
