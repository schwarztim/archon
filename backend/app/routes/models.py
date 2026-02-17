"""Model (LLM provider) CRUD endpoints and enterprise model router."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models import Model
from app.models.router import (
    FallbackChainConfig,
    ModelProvider,
    PROVIDER_CREDENTIAL_SCHEMAS,
    RoutingPolicy,
    RoutingRequest,
    VisualRouteRequest,
    VisualRoutingRule,
)
from app.secrets.manager import get_secrets_manager
from app.services import ModelService
from app.services.router_service import ModelRouterService

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

router = APIRouter(prefix="/models", tags=["models"])
router_api = APIRouter(prefix="/router", tags=["router"])


# ── Request / response schemas ──────────────────────────────────────


class ModelCreate(BaseModel):
    """Payload for creating a model configuration."""

    name: str
    provider: str
    model_id: str
    config: dict[str, Any]
    is_active: bool = True


class ModelUpdate(BaseModel):
    """Payload for updating a model configuration (partial)."""

    name: str | None = None
    provider: str | None = None
    model_id: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class ProviderCredentialsPayload(BaseModel):
    """Payload for storing provider credentials."""

    credentials: dict[str, Any]


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/")
async def list_models(
    provider: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List models with pagination and optional filters."""
    models, total = await ModelService.list(
        session, provider=provider, is_active=is_active, limit=limit, offset=offset,
    )
    return {
        "data": [m.model_dump(mode="json") for m in models],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.post("/", status_code=201)
async def create_model(
    body: ModelCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new model configuration."""
    span_ctx = _tracer.start_as_current_span("create_model") if _tracer else None
    try:
        if span_ctx:
            span_ctx.__enter__()
        model = Model(**body.model_dump())
        created = await ModelService.create(session, model)
        return {
            "data": created.model_dump(mode="json"),
            "meta": _meta(),
        }
    finally:
        if span_ctx:
            span_ctx.__exit__(None, None, None)


@router.get("/{model_id}")
async def get_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single model by ID."""
    model = await ModelService.get(session, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return {
        "data": model.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.put("/{model_id}")
async def update_model(
    model_id: UUID,
    body: ModelUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an existing model configuration."""
    data = body.model_dump(exclude_unset=True)
    model = await ModelService.update(session, model_id, data)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return {
        "data": model.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a model configuration."""
    deleted = await ModelService.delete(session, model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found")


# ── Enterprise Model Router Routes ──────────────────────────────────


@router_api.post("/route", status_code=200)
async def route_request(
    body: RoutingRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Route a request to the optimal model provider."""
    secrets = await get_secrets_manager()
    decision = await ModelRouterService.route(
        session, secrets, user.tenant_id, user, body,
    )
    return {"data": decision.model_dump(mode="json"), "meta": _meta()}


@router_api.post("/providers", status_code=201)
async def register_provider(
    body: ModelProvider,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a new model provider for the tenant."""
    secrets = await get_secrets_manager()
    provider = await ModelRouterService.register_provider(
        session, secrets, user.tenant_id, user, body,
    )
    return {"data": provider.model_dump(mode="json"), "meta": _meta()}


@router_api.get("/providers")
async def list_providers(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List model providers for the authenticated tenant."""
    providers, total = await ModelRouterService.list_providers(
        session, user.tenant_id, user, limit=limit, offset=offset,
    )
    return {
        "data": [p.model_dump(mode="json") for p in providers],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router_api.get("/providers/health")
async def provider_health(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Check health and circuit breaker status for all tenant providers."""
    health = await ModelRouterService.health_check_providers(
        session, user.tenant_id, user,
    )
    return {
        "data": [h.model_dump(mode="json") for h in health],
        "meta": _meta(),
    }


@router_api.get("/history")
async def routing_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return audit trail of routing decisions for the tenant."""
    history, total = await ModelRouterService.get_routing_history(
        session, user.tenant_id, user, limit=limit, offset=offset,
    )
    return {
        "data": history,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router_api.put("/policy")
async def update_routing_policy(
    body: RoutingPolicy,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update per-tenant routing weights / policy."""
    policy = await ModelRouterService.update_routing_policy(
        session, user.tenant_id, user, body,
    )
    return {"data": policy.model_dump(mode="json"), "meta": _meta()}


@router_api.get("/stats")
async def routing_stats(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return aggregated routing statistics for the tenant."""
    stats = await ModelRouterService.get_routing_stats(
        session, user.tenant_id, user,
    )
    return {"data": stats.model_dump(mode="json"), "meta": _meta()}


# ── Provider Credential & Test Endpoints ────────────────────────────


@router_api.get("/providers/credential-schemas")
async def get_credential_schemas(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return per-provider-type credential form schemas."""
    schemas = {
        k: v.model_dump(mode="json")
        for k, v in PROVIDER_CREDENTIAL_SCHEMAS.items()
    }
    return {"data": schemas, "meta": _meta()}


@router_api.put("/providers/{provider_id}/credentials")
async def save_provider_credentials(
    provider_id: UUID,
    body: ProviderCredentialsPayload,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store provider credentials in Vault. Returns provider without secrets."""
    secrets = await get_secrets_manager()
    try:
        entry = await ModelRouterService.save_provider_credentials(
            session, secrets, user.tenant_id, user, provider_id, body.credentials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "data": {
            "provider_id": str(provider_id),
            "vault_path": entry.vault_secret_path,
            "credentials_saved": True,
        },
        "meta": _meta(),
    }


@router_api.post("/providers/{provider_id}/test")
async def test_provider_connection(
    provider_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Test connection to a provider using Vault-stored credentials."""
    secrets = await get_secrets_manager()
    result = await ModelRouterService.test_connection(
        session, secrets, user.tenant_id, user, provider_id,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router_api.get("/providers/{provider_id}/health")
async def get_provider_health_detail(
    provider_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get detailed health metrics for a single provider."""
    try:
        health = await ModelRouterService.get_provider_health_detail(
            session, user.tenant_id, user, provider_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": health.model_dump(mode="json"), "meta": _meta()}


@router_api.get("/providers/health/detail")
async def get_all_provider_health_detail(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get detailed health for all tenant providers with circuit breaker."""
    health = await ModelRouterService.get_all_provider_health_detail(
        session, user.tenant_id, user,
    )
    return {
        "data": [h.model_dump(mode="json") for h in health],
        "meta": _meta(),
    }


@router_api.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete provider and clean up Vault credentials."""
    secrets = await get_secrets_manager()
    deleted = await ModelRouterService.delete_provider(
        session, secrets, user.tenant_id, user, provider_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")


# ── Visual Routing Rule Endpoints ───────────────────────────────────


@router_api.post("/route/visual")
async def visual_route_request(
    body: VisualRouteRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Route a request using visual rules with explainable decision."""
    decision = await ModelRouterService.route_visual(
        session, user.tenant_id, user, body,
    )
    return {"data": decision.model_dump(mode="json"), "meta": _meta()}


@router_api.get("/rules/visual")
async def get_visual_rules(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get visual routing rules for the tenant."""
    rules = await ModelRouterService.get_visual_rules(
        session, user.tenant_id, user,
    )
    return {
        "data": [r.model_dump(mode="json") for r in rules],
        "meta": _meta(),
    }


@router_api.put("/rules/visual")
async def save_visual_rules(
    body: list[VisualRoutingRule],
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Save visual routing rules (bulk upsert with priority)."""
    rules = await ModelRouterService.save_visual_rules(
        session, user.tenant_id, user, body,
    )
    return {
        "data": [r.model_dump(mode="json") for r in rules],
        "meta": _meta(),
    }


@router_api.get("/fallback")
async def get_fallback_chain(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get fallback chain configuration for the tenant."""
    chain = await ModelRouterService.get_fallback_chain(
        session, user.tenant_id, user,
    )
    return {"data": chain.model_dump(mode="json"), "meta": _meta()}


@router_api.put("/fallback")
async def save_fallback_chain(
    body: FallbackChainConfig,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Save fallback chain ordering for the tenant."""
    chain = await ModelRouterService.save_fallback_chain(
        session, user.tenant_id, user, body,
    )
    return {"data": chain.model_dump(mode="json"), "meta": _meta()}
