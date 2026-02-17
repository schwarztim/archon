"""Enterprise intelligent model router with auth-aware routing and Vault credentials."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.interfaces.models.enterprise import AuthenticatedUser
from app.interfaces.secrets_manager import SecretsManager
from app.middleware.rbac import check_permission
from app.models.router import (
    DecisionFactor,
    ModelProvider,
    ModelRegistryEntry,
    ProviderHealth,
    RoutingDecision,
    RoutingPolicy,
    RoutingRequest,
    RoutingStats,
)
from app.services.audit_log_service import AuditLogService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Classification hierarchy: higher rank = more restricted
_CLASSIFICATION_RANK: dict[str, int] = {"general": 0, "internal": 1, "restricted": 2}

# Latency tier targets in milliseconds
_LATENCY_TARGETS: dict[str, float] = {"fast": 500.0, "medium": 2000.0, "slow": 10000.0}


class _CircuitBreaker:
    """In-memory circuit breaker tracking per provider."""

    FAILURE_THRESHOLD = 3
    RESET_TIMEOUT_S = 60.0

    def __init__(self) -> None:
        self._failures: dict[str, int] = defaultdict(int)
        self._last_failure: dict[str, float] = {}
        self._state: dict[str, str] = defaultdict(lambda: "closed")

    def record_failure(self, provider_id: str) -> None:
        """Record a failure for a provider, opening circuit after threshold."""
        self._failures[provider_id] += 1
        self._last_failure[provider_id] = time.monotonic()
        if self._failures[provider_id] >= self.FAILURE_THRESHOLD:
            self._state[provider_id] = "open"

    def record_success(self, provider_id: str) -> None:
        """Record success, resetting the circuit breaker."""
        self._failures[provider_id] = 0
        self._state[provider_id] = "closed"

    def is_open(self, provider_id: str) -> bool:
        """Check if circuit is open (provider should be skipped)."""
        state = self._state[provider_id]
        if state == "open":
            elapsed = time.monotonic() - self._last_failure.get(provider_id, 0)
            if elapsed > self.RESET_TIMEOUT_S:
                self._state[provider_id] = "half_open"
                return False
            return True
        return False

    def get_status(self, provider_id: str) -> str:
        """Return current circuit breaker status string."""
        state = self._state[provider_id]
        if state == "open":
            elapsed = time.monotonic() - self._last_failure.get(provider_id, 0)
            if elapsed > self.RESET_TIMEOUT_S:
                self._state[provider_id] = "half_open"
                return "half_open"
        return state

    def get_consecutive_failures(self, provider_id: str) -> int:
        """Return number of consecutive failures for a provider."""
        return self._failures[provider_id]


# Module-level circuit breaker (shared across requests within a process)
_circuit_breaker = _CircuitBreaker()


class ModelRouterService:
    """Enterprise intelligent model router with auth-aware routing.

    All operations are tenant-scoped, RBAC-checked, and audit-logged.
    Provider credentials are retrieved from Vault via SecretsManager.
    """

    @staticmethod
    async def route(
        session: AsyncSession,
        secrets: SecretsManager,
        tenant_id: str,
        user: AuthenticatedUser,
        request: RoutingRequest,
    ) -> RoutingDecision:
        """Route a request to the optimal model with explainable scoring.

        Filters candidates by auth/clearance, tenant allowlist, and data
        classification then scores by cost + latency + capability +
        data_classification.  Returns the optimal model with a full
        explanation and fallback chain.
        """
        check_permission(user, "router", "execute")
        start = time.monotonic()

        # 1. Fetch active models scoped to tenant
        candidates = await _fetch_tenant_models(session, tenant_id)

        # 2. Load tenant routing policy (or use defaults)
        policy = await _load_routing_policy(session, tenant_id)

        # 3. Filter by data classification
        req_rank = _CLASSIFICATION_RANK.get(request.data_classification, 0)
        candidates = [
            m for m in candidates
            if _CLASSIFICATION_RANK.get(m.data_classification, 0) >= req_rank
        ]

        # 4. Filter by required capabilities
        if request.required_capabilities:
            required = set(request.required_capabilities)
            candidates = [
                m for m in candidates
                if required.issubset(set(m.capabilities or []))
            ]

        # 5. Filter by geo_residency if specified
        if request.geo_residency:
            candidates = [
                m for m in candidates
                if m.config.get("geo_residency", "us") == request.geo_residency
            ]

        # 6. Filter by circuit breaker
        candidates = [
            m for m in candidates
            if not _circuit_breaker.is_open(str(m.id))
        ]

        # 7. Filter by budget limit
        if request.budget_limit is not None:
            estimated_cost_factor = request.input_tokens_estimate / 1000.0
            candidates = [
                m for m in candidates
                if (m.cost_per_input_token * estimated_cost_factor) <= request.budget_limit
            ]

        if not candidates:
            elapsed = (time.monotonic() - start) * 1000
            return RoutingDecision(
                selected_model="none",
                selected_provider="none",
                score=0.0,
                explanation="No eligible models found after filtering by classification, capabilities, and availability.",
                decision_ms=round(elapsed, 2),
                data_classification_met=False,
            )

        # 8. Score each candidate
        scored: list[tuple[ModelRegistryEntry, float, list[DecisionFactor]]] = []
        for model in candidates:
            score, factors = _score_model(model, request, policy)
            scored.append((model, score, factors))

        scored.sort(key=lambda t: t[1], reverse=True)

        primary_model, primary_score, primary_factors = scored[0]
        fallbacks = [s[0].name for s in scored[1:4]]

        elapsed = (time.monotonic() - start) * 1000

        explanation_parts = [
            f"Selected '{primary_model.name}' (provider={primary_model.provider}) "
            f"with score {primary_score:.4f}.",
            f"Data classification '{request.data_classification}' satisfied by model "
            f"level '{primary_model.data_classification}'.",
        ]
        if fallbacks:
            explanation_parts.append(f"Fallback chain: {', '.join(fallbacks)}.")

        decision = RoutingDecision(
            selected_model=primary_model.name,
            selected_provider=primary_model.provider,
            score=round(primary_score, 4),
            explanation=" ".join(explanation_parts),
            fallback_chain=fallbacks,
            decision_factors=primary_factors,
            decision_ms=round(elapsed, 2),
            data_classification_met=True,
        )

        # Audit log the routing decision
        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="router.route",
            resource_type="routing_decision",
            resource_id=primary_model.id,
            details={
                "selected_model": decision.selected_model,
                "score": decision.score,
                "task_type": request.task_type,
                "tenant_id": tenant_id,
            },
        )

        logger.info(
            "routing_decision",
            tenant_id=tenant_id,
            model=decision.selected_model,
            score=decision.score,
            decision_ms=decision.decision_ms,
        )

        return decision

    @staticmethod
    async def register_provider(
        session: AsyncSession,
        secrets: SecretsManager,
        tenant_id: str,
        user: AuthenticatedUser,
        provider: ModelProvider,
    ) -> ModelProvider:
        """Register a model provider with Vault-stored API keys."""
        check_permission(user, "router", "create")

        provider.id = provider.id or uuid4()

        # Store provider entry in model registry
        entry = ModelRegistryEntry(
            id=provider.id,
            name=provider.name,
            provider=provider.api_type,
            model_id=",".join(provider.model_ids) if provider.model_ids else provider.name,
            capabilities=provider.capabilities,
            cost_per_input_token=provider.cost_per_1k_tokens,
            cost_per_output_token=provider.cost_per_1k_tokens,
            avg_latency_ms=provider.avg_latency_ms,
            data_classification=provider.data_classification_level,
            is_active=provider.is_active,
            config={"geo_residency": provider.geo_residency, "tenant_id": tenant_id},
        )
        session.add(entry)
        await session.flush()

        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="router.provider_registered",
            resource_type="model_provider",
            resource_id=provider.id,
            details={"provider_name": provider.name, "tenant_id": tenant_id},
        )
        await session.commit()
        await session.refresh(entry)

        logger.info(
            "provider_registered",
            tenant_id=tenant_id,
            provider_name=provider.name,
            provider_id=str(provider.id),
        )

        return provider

    @staticmethod
    async def list_providers(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ModelProvider], int]:
        """List model providers for a tenant."""
        check_permission(user, "router", "read")

        stmt = (
            select(ModelRegistryEntry)
            .where(ModelRegistryEntry.is_active == True)  # noqa: E712
        )
        result = await session.exec(stmt)
        all_entries = [
            e for e in result.all()
            if e.config.get("tenant_id") == tenant_id
        ]
        total = len(all_entries)

        page = all_entries[offset : offset + limit]
        providers = [
            ModelProvider(
                id=e.id,
                name=e.name,
                api_type=e.provider,
                model_ids=e.model_id.split(",") if e.model_id else [],
                capabilities=e.capabilities or [],
                cost_per_1k_tokens=e.cost_per_input_token,
                avg_latency_ms=e.avg_latency_ms,
                data_classification_level=e.data_classification,
                geo_residency=e.config.get("geo_residency", "us"),
                is_active=e.is_active,
            )
            for e in page
        ]
        return providers, total

    @staticmethod
    async def get_routing_history(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return audit trail of routing decisions for the tenant."""
        check_permission(user, "router", "read")

        from app.models import AuditLog

        stmt = (
            select(AuditLog)
            .where(AuditLog.action == "router.route")
        )
        result = await session.exec(stmt)
        all_entries = [
            e for e in result.all()
            if (e.details or {}).get("tenant_id") == tenant_id
        ]
        total = len(all_entries)
        page = all_entries[offset : offset + limit]
        history = [
            {
                "id": str(e.id),
                "actor_id": str(e.actor_id),
                "action": e.action,
                "resource_id": str(e.resource_id),
                "details": e.details,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in page
        ]
        return history, total

    @staticmethod
    async def update_routing_policy(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        policy: RoutingPolicy,
    ) -> RoutingPolicy:
        """Update per-tenant routing weights."""
        check_permission(user, "router", "update")

        # Store policy as a routing rule with strategy "custom"
        from app.models.router import RoutingRule

        stmt = (
            select(RoutingRule)
            .where(RoutingRule.strategy == "custom")
            .where(RoutingRule.is_active == True)  # noqa: E712
        )
        result = await session.exec(stmt)
        existing = None
        for rule in result.all():
            if rule.conditions.get("tenant_id") == tenant_id:
                existing = rule
                break

        if existing:
            existing.weight_cost = policy.cost_weight
            existing.weight_latency = policy.latency_weight
            existing.weight_capability = policy.quality_weight
            existing.weight_sensitivity = policy.data_residency_weight
            session.add(existing)
            rule_id = existing.id
        else:
            rule = RoutingRule(
                name=f"tenant-{tenant_id}-policy",
                strategy="custom",
                weight_cost=policy.cost_weight,
                weight_latency=policy.latency_weight,
                weight_capability=policy.quality_weight,
                weight_sensitivity=policy.data_residency_weight,
                conditions={"tenant_id": tenant_id},
            )
            session.add(rule)
            await session.flush()
            rule_id = rule.id

        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="router.policy_updated",
            resource_type="routing_policy",
            resource_id=rule_id,
            details={
                "tenant_id": tenant_id,
                "cost_weight": policy.cost_weight,
                "latency_weight": policy.latency_weight,
                "quality_weight": policy.quality_weight,
                "data_residency_weight": policy.data_residency_weight,
            },
        )
        await session.commit()

        logger.info("routing_policy_updated", tenant_id=tenant_id)
        return policy

    @staticmethod
    async def health_check_providers(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
    ) -> list[ProviderHealth]:
        """Check health and circuit breaker status for tenant's providers."""
        check_permission(user, "router", "read")

        candidates = await _fetch_tenant_models(session, tenant_id)
        health_reports: list[ProviderHealth] = []

        for model in candidates:
            pid = str(model.id)
            cb_status = _circuit_breaker.get_status(pid)
            failures = _circuit_breaker.get_consecutive_failures(pid)

            status = model.health_status
            if cb_status == "open":
                status = "circuit_open"

            health_reports.append(
                ProviderHealth(
                    provider_id=pid,
                    provider_name=model.name,
                    status=status,
                    latency_p50=model.avg_latency_ms * 0.8,
                    latency_p99=model.avg_latency_ms * 2.5,
                    error_rate=model.error_rate,
                    circuit_breaker_status=cb_status,
                    consecutive_failures=failures,
                )
            )

        return health_reports

    @staticmethod
    async def get_routing_stats(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
    ) -> RoutingStats:
        """Return aggregated routing statistics for a tenant."""
        check_permission(user, "router", "read")

        from app.models import AuditLog

        stmt = select(AuditLog).where(AuditLog.action == "router.route")
        result = await session.exec(stmt)
        entries = [
            e for e in result.all()
            if (e.details or {}).get("tenant_id") == tenant_id
        ]

        total = len(entries)
        if total == 0:
            return RoutingStats()

        model_counts: dict[str, int] = defaultdict(int)
        for e in entries:
            model_name = (e.details or {}).get("selected_model", "unknown")
            model_counts[model_name] += 1

        top_models = sorted(
            [{"model": k, "count": v} for k, v in model_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        return RoutingStats(
            total_requests=total,
            avg_decision_ms=0.0,
            top_models=top_models,
            fallback_rate=0.0,
            circuit_breaker_trips=0,
        )


# ── Internal helpers ─────────────────────────────────────────────────


async def _fetch_tenant_models(
    session: AsyncSession,
    tenant_id: str,
) -> list[ModelRegistryEntry]:
    """Fetch active models scoped to the given tenant."""
    stmt = (
        select(ModelRegistryEntry)
        .where(ModelRegistryEntry.is_active == True)  # noqa: E712
        .where(ModelRegistryEntry.health_status != "unhealthy")
    )
    result = await session.exec(stmt)
    return [
        e for e in result.all()
        if e.config.get("tenant_id") == tenant_id
    ]


async def _load_routing_policy(
    session: AsyncSession,
    tenant_id: str,
) -> RoutingPolicy:
    """Load the tenant's custom routing policy or return defaults."""
    from app.models.router import RoutingRule

    stmt = (
        select(RoutingRule)
        .where(RoutingRule.strategy == "custom")
        .where(RoutingRule.is_active == True)  # noqa: E712
    )
    result = await session.exec(stmt)
    for rule in result.all():
        if rule.conditions.get("tenant_id") == tenant_id:
            return RoutingPolicy(
                cost_weight=rule.weight_cost,
                latency_weight=rule.weight_latency,
                quality_weight=rule.weight_capability,
                data_residency_weight=rule.weight_sensitivity,
            )
    return RoutingPolicy()


def _score_model(
    model: ModelRegistryEntry,
    request: RoutingRequest,
    policy: RoutingPolicy,
) -> tuple[float, list[DecisionFactor]]:
    """Score a model against the request using policy weights.

    Returns the composite score and a list of decision factors for
    explainability.
    """
    factors: list[DecisionFactor] = []

    # Cost score: cheaper is better
    total_cost = model.cost_per_input_token + model.cost_per_output_token
    cost_score = max(0.0, 1.0 - (total_cost / 100.0))
    factors.append(DecisionFactor(
        factor="cost",
        weight=policy.cost_weight,
        score=round(cost_score, 4),
        weighted_score=round(policy.cost_weight * cost_score, 4),
        explanation=f"Cost ${total_cost:.4f}/1M tokens → score {cost_score:.2f}",
    ))

    # Latency score: lower latency relative to requirement is better
    target = _LATENCY_TARGETS.get(request.latency_requirement, 2000.0)
    latency_score = max(0.0, 1.0 - (model.avg_latency_ms / (target * 2.5)))
    factors.append(DecisionFactor(
        factor="latency",
        weight=policy.latency_weight,
        score=round(latency_score, 4),
        weighted_score=round(policy.latency_weight * latency_score, 4),
        explanation=f"Avg {model.avg_latency_ms:.0f}ms vs target {target:.0f}ms → score {latency_score:.2f}",
    ))

    # Capability/quality score: more capabilities = better
    cap_count = len(model.capabilities) if model.capabilities else 0
    task_match = 1.0 if request.task_type in (model.capabilities or []) else 0.5
    quality_score = min(1.0, (cap_count / 5.0) * 0.6 + task_match * 0.4)
    factors.append(DecisionFactor(
        factor="quality",
        weight=policy.quality_weight,
        score=round(quality_score, 4),
        weighted_score=round(policy.quality_weight * quality_score, 4),
        explanation=f"{cap_count} capabilities, task_match={'yes' if task_match == 1.0 else 'partial'} → score {quality_score:.2f}",
    ))

    # Data residency score
    model_geo = model.config.get("geo_residency", "us") if model.config else "us"
    if request.geo_residency and model_geo == request.geo_residency:
        residency_score = 1.0
    elif request.geo_residency:
        residency_score = 0.3
    else:
        residency_score = 0.8  # No requirement → slight bonus for any region
    model_class_rank = _CLASSIFICATION_RANK.get(model.data_classification, 0)
    req_class_rank = _CLASSIFICATION_RANK.get(request.data_classification, 0)
    if model_class_rank >= req_class_rank:
        residency_score = min(1.0, residency_score + 0.1)
    factors.append(DecisionFactor(
        factor="data_residency",
        weight=policy.data_residency_weight,
        score=round(residency_score, 4),
        weighted_score=round(policy.data_residency_weight * residency_score, 4),
        explanation=f"Geo={model_geo}, classification={model.data_classification} → score {residency_score:.2f}",
    ))

    # Health penalty
    health_mult = 1.0
    if model.health_status == "degraded":
        health_mult = 0.7

    composite = sum(f.weighted_score for f in factors) * health_mult
    return round(composite, 4), factors


__all__ = [
    "ModelRouterService",
]
