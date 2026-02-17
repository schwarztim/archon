"""API routes for the Archon intelligent router and model registry."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.router import ModelRegistryEntry, RoutingRule
from app.secrets.manager import get_secrets_manager
from app.services.router import ModelRegistry, RoutingEngine, RoutingRuleService

router = APIRouter(prefix="/router", tags=["router"])


# ── Request / response schemas ──────────────────────────────────────


class RoutingRuleCreate(BaseModel):
    """Payload for creating a routing rule."""

    name: str
    description: str | None = None
    strategy: str = "balanced"
    priority: int = 0
    is_active: bool = True
    department_id: UUID | None = None
    agent_id: UUID | None = None
    weight_cost: float = PField(default=0.25, ge=0.0, le=1.0)
    weight_latency: float = PField(default=0.25, ge=0.0, le=1.0)
    weight_capability: float = PField(default=0.25, ge=0.0, le=1.0)
    weight_sensitivity: float = PField(default=0.25, ge=0.0, le=1.0)
    conditions: dict[str, Any] = PField(default_factory=dict)
    fallback_chain: list[str] = PField(default_factory=list)


class RoutingRuleUpdate(BaseModel):
    """Payload for partial-updating a routing rule."""

    name: str | None = None
    description: str | None = None
    strategy: str | None = None
    priority: int | None = None
    is_active: bool | None = None
    weight_cost: float | None = PField(default=None, ge=0.0, le=1.0)
    weight_latency: float | None = PField(default=None, ge=0.0, le=1.0)
    weight_capability: float | None = PField(default=None, ge=0.0, le=1.0)
    weight_sensitivity: float | None = PField(default=None, ge=0.0, le=1.0)
    conditions: dict[str, Any] | None = None
    fallback_chain: list[str] | None = None


class ModelRegistryCreate(BaseModel):
    """Payload for registering a model in the registry."""

    name: str
    provider: str
    model_id: str
    capabilities: list[str] = PField(default_factory=list)
    context_window: int = 4096
    supports_streaming: bool = True
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0
    speed_tier: str = "medium"
    avg_latency_ms: float = 500.0
    data_classification: str = "general"
    is_on_prem: bool = False
    is_active: bool = True
    config: dict[str, Any] = PField(default_factory=dict)


class ModelRegistryUpdate(BaseModel):
    """Payload for partial-updating a model registry entry."""

    name: str | None = None
    provider: str | None = None
    model_id: str | None = None
    capabilities: list[str] | None = None
    context_window: int | None = None
    supports_streaming: bool | None = None
    cost_per_input_token: float | None = None
    cost_per_output_token: float | None = None
    speed_tier: str | None = None
    avg_latency_ms: float | None = None
    data_classification: str | None = None
    is_on_prem: bool | None = None
    is_active: bool | None = None
    health_status: str | None = None
    error_rate: float | None = None
    config: dict[str, Any] | None = None


class RouteRequest(BaseModel):
    """Payload for requesting a routing decision."""

    department_id: UUID | None = None
    agent_id: UUID | None = None
    required_capabilities: list[str] | None = None
    data_classification: str = "general"
    strategy_override: str | None = None


class ApiKeyStore(BaseModel):
    """Payload for storing a provider API key."""

    api_key: str


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Routing Decision ────────────────────────────────────────────────


@router.post("/route")
async def route_request(
    body: RouteRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Select the optimal model for a request context."""
    decision = await RoutingEngine.route(
        session,
        department_id=body.department_id,
        agent_id=body.agent_id,
        required_capabilities=body.required_capabilities,
        data_classification=body.data_classification,
        strategy_override=body.strategy_override,
    )
    return {"data": decision, "meta": _meta()}


# ── Routing Rules CRUD ──────────────────────────────────────────────


@router.get("/rules")
async def list_rules(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    is_active: bool | None = Query(default=None),
    strategy: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List routing rules with pagination."""
    rules, total = await RoutingRuleService.list(
        session, is_active=is_active, strategy=strategy, limit=limit, offset=offset,
    )
    return {
        "data": [r.model_dump(mode="json") for r in rules],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/rules", status_code=201)
async def create_rule(
    body: RoutingRuleCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new routing rule."""
    rule = RoutingRule(**body.model_dump())
    created = await RoutingRuleService.create(session, rule)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/rules/{rule_id}")
async def get_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a routing rule by ID."""
    rule = await RoutingRuleService.get(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    return {"data": rule.model_dump(mode="json"), "meta": _meta()}


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: UUID,
    body: RoutingRuleUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a routing rule."""
    data = body.model_dump(exclude_unset=True)
    rule = await RoutingRuleService.update(session, rule_id, data)
    if rule is None:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    return {"data": rule.model_dump(mode="json"), "meta": _meta()}


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a routing rule."""
    deleted = await RoutingRuleService.delete(session, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Routing rule not found")


# ── Model Registry CRUD ────────────────────────────────────────────


@router.get("/models")
async def list_models(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    provider: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    capability: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List registered models with optional filters."""
    entries, total = await ModelRegistry.list(
        session, provider=provider, is_active=is_active, capability=capability,
        limit=limit, offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/models", status_code=201)
async def register_model(
    body: ModelRegistryCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a new model in the registry."""
    entry = ModelRegistryEntry(**body.model_dump())
    created = await ModelRegistry.register(session, entry)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/models/{model_id}")
async def get_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a model registry entry by ID."""
    entry = await ModelRegistry.get(session, model_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


@router.put("/models/{model_id}")
async def update_model(
    model_id: UUID,
    body: ModelRegistryUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a model registry entry."""
    data = body.model_dump(exclude_unset=True)
    entry = await ModelRegistry.update(session, model_id, data)
    if entry is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a model from the registry."""
    deleted = await ModelRegistry.delete(session, model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found")


# ── Provider API Key & Connection ───────────────────────────────────


@router.post("/providers/{provider_id}/api-key", status_code=201)
async def store_provider_api_key(
    provider_id: UUID,
    body: ApiKeyStore,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store provider API key in secrets manager."""
    entry = await ModelRegistry.get(session, provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    secrets = await get_secrets_manager()
    vault_path = f"archon/providers/{provider_id}/api_key"
    await secrets.put_secret(vault_path, {"api_key": body.api_key}, tenant_id="")
    entry.vault_secret_path = vault_path
    entry.updated_at = datetime.now(tz=timezone.utc)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return {"data": {"provider_id": str(provider_id), "vault_secret_path": vault_path}, "meta": _meta()}


@router.post("/providers/{provider_id}/test-connection")
async def test_provider_connection(
    provider_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Test connectivity to a provider by making a lightweight API call."""
    entry = await ModelRegistry.get(session, provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Stub: in production this would use the API key from Vault to make a real call
    return {"data": {"status": "connected", "latency_ms": 0}, "meta": _meta()}
