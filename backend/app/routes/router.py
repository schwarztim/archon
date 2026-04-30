"""API routes for the Archon intelligent router and model registry."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from app.utils.time import utcnow
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.database import get_session
from app.models.router import ModelRegistryEntry, RoutingRule
from app.models.visual_rule import VisualRule as VisualRuleModel
from app.secrets.manager import get_secrets_manager
from app.services.router import ModelRegistry, RoutingEngine, RoutingRuleService
from starlette.responses import Response

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


class ProviderCreate(BaseModel):
    """Payload for registering a provider."""

    name: str
    provider_type: str  # openai | anthropic | azure | google | bedrock | custom
    base_url: str | None = None
    is_active: bool = True
    config: dict[str, Any] = PField(default_factory=dict)


class ProviderCredentials(BaseModel):
    """Payload for storing provider credentials."""

    api_key: str | None = None
    credentials: dict[str, Any] = PField(default_factory=dict)


class VisualRule(BaseModel):
    """A visual routing rule."""

    id: str | None = None
    name: str
    conditions: list[dict[str, Any]] = PField(default_factory=list)
    action: dict[str, Any] = PField(default_factory=dict)
    is_active: bool = True


class VisualRulesPayload(BaseModel):
    """Payload for saving visual rules."""

    rules: list[VisualRule] = PField(default_factory=list)


class VisualRouteRequest(BaseModel):
    """Payload for visual route evaluation."""

    context: dict[str, Any] = PField(default_factory=dict)


class FallbackChain(BaseModel):
    """Fallback chain configuration."""

    chain: list[str] = PField(default_factory=list)
    retry_count: int = 1
    timeout_seconds: int = 30


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
        session,
        is_active=is_active,
        strategy=strategy,
        limit=limit,
        offset=offset,
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


@router.get("/rules/visual")
async def get_visual_rules(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get visual rule builder data (DB-backed)."""
    stmt = select(VisualRuleModel).order_by(VisualRuleModel.priority.desc())
    result = await session.exec(stmt)
    rows = result.all()
    rules = [
        {
            "id": str(r.id),
            "name": r.name,
            "priority": r.priority,
            "conditions": r.conditions or [],
            "action": r.action or {},
            "is_active": r.is_active,
        }
        for r in rows
    ]
    return {"data": {"rules": rules}, "meta": _meta()}


@router.put("/rules/visual")
async def save_visual_rules(
    body: VisualRulesPayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Replace all visual rules (DB-backed).

    Full-replace semantics: existing rows are deleted, then the new set is inserted.
    This mirrors the original in-memory assignment.
    """
    from sqlalchemy import delete as sa_delete

    now = datetime.now(tz=timezone.utc)

    # Drop existing rules (full replace)
    await session.exec(sa_delete(VisualRuleModel))  # type: ignore[arg-type]

    new_rows = []
    for rule_schema in body.rules:
        row = VisualRuleModel(
            name=rule_schema.name,
            conditions=rule_schema.conditions,
            action=rule_schema.action,
            is_active=rule_schema.is_active,
            created_at=now,
            updated_at=now,
        )
        if rule_schema.id:
            try:
                from uuid import UUID as _UUID
                row.id = _UUID(rule_schema.id)
            except (ValueError, AttributeError):
                pass
        session.add(row)
        new_rows.append(row)

    await session.commit()

    saved = [
        {
            "id": str(r.id),
            "name": r.name,
            "priority": r.priority,
            "conditions": r.conditions or [],
            "action": r.action or {},
            "is_active": r.is_active,
        }
        for r in new_rows
    ]
    return {"data": {"rules": saved}, "meta": _meta()}


@router.post("/route/visual")
async def evaluate_visual_route(
    body: VisualRouteRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Evaluate a visual routing rule against the given context (DB-backed)."""
    stmt = (
        select(VisualRuleModel)
        .where(VisualRuleModel.is_active == True)  # noqa: E712
        .order_by(VisualRuleModel.priority.desc())
    )
    result = await session.exec(stmt)
    rows = result.all()

    matched_rules = [
        {
            "id": str(r.id),
            "name": r.name,
            "conditions": r.conditions or [],
            "action": r.action or {},
            "is_active": r.is_active,
        }
        for r in rows
    ]
    action = matched_rules[0]["action"] if matched_rules else {}
    return {
        "data": {
            "matched_rules": matched_rules,
            "action": action,
            "context": body.context,
        },
        "meta": _meta(),
    }


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


@router.delete("/rules/{rule_id}", status_code=204, response_class=Response)
async def delete_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a routing rule."""
    deleted = await RoutingRuleService.delete(session, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    return Response(status_code=204)


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
        session,
        provider=provider,
        is_active=is_active,
        capability=capability,
        limit=limit,
        offset=offset,
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


@router.delete("/models/{model_id}", status_code=204, response_class=Response)
async def delete_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a model from the registry."""
    deleted = await ModelRegistry.delete(session, model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found")
    return Response(status_code=204)


# ── Provider Endpoints (static routes first) ───────────────────────


@router.get("/providers")
async def list_providers(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all registered providers (models grouped by provider)."""
    entries, total = await ModelRegistry.list(session, limit=1000, offset=0)
    providers: dict[str, dict[str, Any]] = {}
    for e in entries:
        pid = e.provider
        if pid not in providers:
            providers[pid] = {
                "id": pid,
                "name": pid,
                "provider_type": pid,
                "is_active": True,
                "model_count": 0,
                "models": [],
            }
        providers[pid]["model_count"] += 1
        providers[pid]["models"].append(e.model_dump(mode="json"))
    return {
        "data": list(providers.values()),
        "meta": _meta(total=len(providers)),
    }


@router.post("/providers", status_code=201)
async def create_provider(
    body: ProviderCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a new provider (creates a placeholder model registry entry)."""
    entry = ModelRegistryEntry(
        name=body.name,
        provider=body.provider_type,
        model_id=f"{body.provider_type}/default",
        capabilities=[],
        is_active=body.is_active,
        config=body.config,
    )
    created = await ModelRegistry.register(session, entry)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/providers/health")
async def providers_health_summary(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Aggregated provider health summary."""
    entries, _ = await ModelRegistry.list(session, limit=1000, offset=0)
    summary: dict[str, dict[str, Any]] = {}
    for e in entries:
        pid = e.provider
        if pid not in summary:
            summary[pid] = {
                "provider": pid,
                "healthy": 0,
                "degraded": 0,
                "unhealthy": 0,
                "total": 0,
            }
        summary[pid]["total"] += 1
        status = e.health_status or "healthy"
        if status in summary[pid]:
            summary[pid][status] += 1
    return {"data": list(summary.values()), "meta": _meta()}


@router.get("/providers/health/detail")
async def providers_health_detail(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """All providers health detail."""
    entries, _ = await ModelRegistry.list(session, limit=1000, offset=0)
    detail: dict[str, dict[str, Any]] = {}
    for e in entries:
        pid = e.provider
        if pid not in detail:
            detail[pid] = {"provider": pid, "models": []}
        detail[pid]["models"].append(
            {
                "id": str(e.id),
                "name": e.name,
                "health_status": e.health_status or "healthy",
                "error_rate": e.error_rate,
                "avg_latency_ms": e.avg_latency_ms,
            }
        )
    return {"data": list(detail.values()), "meta": _meta()}


@router.get("/providers/credential-schemas")
async def get_credential_schemas() -> dict[str, Any]:
    """Return credential field schemas per provider type."""
    schemas = {
        "openai": {
            "fields": [
                {"name": "api_key", "type": "string", "required": True, "secret": True}
            ]
        },
        "anthropic": {
            "fields": [
                {"name": "api_key", "type": "string", "required": True, "secret": True}
            ]
        },
        "azure": {
            "fields": [
                {"name": "api_key", "type": "string", "required": True, "secret": True},
                {
                    "name": "endpoint",
                    "type": "string",
                    "required": True,
                    "secret": False,
                },
                {
                    "name": "deployment_name",
                    "type": "string",
                    "required": True,
                    "secret": False,
                },
                {
                    "name": "api_version",
                    "type": "string",
                    "required": False,
                    "secret": False,
                },
            ]
        },
        "google": {
            "fields": [
                {"name": "api_key", "type": "string", "required": True, "secret": True}
            ]
        },
        "bedrock": {
            "fields": [
                {
                    "name": "aws_access_key_id",
                    "type": "string",
                    "required": True,
                    "secret": True,
                },
                {
                    "name": "aws_secret_access_key",
                    "type": "string",
                    "required": True,
                    "secret": True,
                },
                {
                    "name": "aws_region",
                    "type": "string",
                    "required": True,
                    "secret": False,
                },
            ]
        },
        "custom": {
            "fields": [
                {
                    "name": "api_key",
                    "type": "string",
                    "required": False,
                    "secret": True,
                },
                {
                    "name": "base_url",
                    "type": "string",
                    "required": True,
                    "secret": False,
                },
            ]
        },
    }
    return {"data": schemas, "meta": _meta()}


# ── Provider Dynamic Routes ({provider_id}) ────────────────────────


@router.delete("/providers/{provider_id}", status_code=204, response_class=Response)
async def delete_provider(
    provider_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a provider (its model registry entry)."""
    deleted = await ModelRegistry.delete(session, provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")
    return Response(status_code=204)


@router.get("/providers/{provider_id}/health")
async def provider_health_detail(
    provider_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Single provider health detail."""
    entry = await ModelRegistry.get(session, provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {
        "data": {
            "id": str(entry.id),
            "provider": entry.provider,
            "health_status": entry.health_status or "healthy",
            "error_rate": entry.error_rate,
            "avg_latency_ms": entry.avg_latency_ms,
        },
        "meta": _meta(),
    }


@router.put("/providers/{provider_id}/credentials")
async def store_provider_credentials(
    provider_id: UUID,
    body: ProviderCredentials,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store/update provider credentials in secrets manager."""
    entry = await ModelRegistry.get(session, provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    secrets = await get_secrets_manager()
    vault_path = f"archon/providers/{provider_id}/credentials"
    secret_data: dict[str, Any] = {**body.credentials}
    if body.api_key:
        secret_data["api_key"] = body.api_key
    await secrets.put_secret(vault_path, secret_data, tenant_id="")
    entry.vault_secret_path = vault_path
    entry.updated_at = utcnow()
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return {
        "data": {"provider_id": str(provider_id), "vault_secret_path": vault_path},
        "meta": _meta(),
    }


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
    entry.updated_at = utcnow()
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return {
        "data": {"provider_id": str(provider_id), "vault_secret_path": vault_path},
        "meta": _meta(),
    }


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


# ── Fallback Chain ──────────────────────────────────────────────────


# In-memory store for fallback chain config (replace with DB persistence later)
_fallback_chain_store: dict[str, Any] = {
    "chain": [],
    "retry_count": 1,
    "timeout_seconds": 30,
}


@router.get("/fallback")
async def get_fallback_chain() -> dict[str, Any]:
    """Get the fallback chain configuration."""
    return {"data": _fallback_chain_store, "meta": _meta()}


@router.put("/fallback")
async def save_fallback_chain(body: FallbackChain) -> dict[str, Any]:
    """Save/update the fallback chain configuration."""
    global _fallback_chain_store
    _fallback_chain_store = body.model_dump()
    return {"data": _fallback_chain_store, "meta": _meta()}


# ── Embeddings Endpoint ─────────────────────────────────────────────


class EmbeddingsRequest(BaseModel):
    """Payload for the embeddings endpoint."""

    text: str = PField(..., min_length=1, description="Text to embed")
    model: str = PField(
        default="qrg-embedding-experimental",
        description="Embeddings model deployment name",
    )


class EmbeddingsResponse(BaseModel):
    """Response from the embeddings endpoint."""

    embedding: list[float]
    model: str
    usage: dict[str, int]


@router.post(
    "/embeddings", response_model=EmbeddingsResponse, tags=["router", "embeddings"]
)
async def create_embedding(body: EmbeddingsRequest) -> EmbeddingsResponse:
    """Generate a vector embedding for the provided text via Azure OpenAI.

    Requires ``ARCHON_AZURE_OPENAI_API_KEY`` and optionally
    ``ARCHON_AZURE_OPENAI_ENDPOINT`` to be set in the environment.
    """
    from app.config import settings
    from app.services.router_service import call_azure_openai_with_retry

    api_key = settings.AZURE_OPENAI_API_KEY or os.environ.get(
        "AZURE_OPENAI_API_KEY", ""
    )
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Azure OpenAI API key not configured. Set ARCHON_AZURE_OPENAI_API_KEY.",
        )

    endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
    deployment = body.model
    url = (
        f"{endpoint}/openai/deployments/{deployment}/embeddings?api-version=2023-05-15"
    )

    payload = {"input": body.text, "model": deployment}

    try:
        data = await call_azure_openai_with_retry(url, payload, api_key)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Azure OpenAI error: {exc}"
        ) from exc

    embedding_data = data.get("data", [{}])[0]
    usage = data.get("usage", {"prompt_tokens": 0, "total_tokens": 0})

    return EmbeddingsResponse(
        embedding=embedding_data.get("embedding", []),
        model=data.get("model", deployment),
        usage={
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    )
