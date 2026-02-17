"""Intelligent routing engine and model registry for Archon."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.router import ModelRegistryEntry, RoutingRule


# ── Model Registry ──────────────────────────────────────────────────


class ModelRegistry:
    """Manages the catalogue of available LLM models and their metadata."""

    @staticmethod
    async def register(session: AsyncSession, entry: ModelRegistryEntry) -> ModelRegistryEntry:
        """Register a new model in the registry."""
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry

    @staticmethod
    async def get(session: AsyncSession, entry_id: UUID) -> ModelRegistryEntry | None:
        """Return a single registry entry by ID."""
        return await session.get(ModelRegistryEntry, entry_id)

    @staticmethod
    async def list(
        session: AsyncSession,
        *,
        provider: str | None = None,
        is_active: bool | None = None,
        capability: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ModelRegistryEntry], int]:
        """Return paginated model entries with optional filters and total count."""
        base = select(ModelRegistryEntry)
        if provider is not None:
            base = base.where(ModelRegistryEntry.provider == provider)
        if is_active is not None:
            base = base.where(ModelRegistryEntry.is_active == is_active)

        count_result = await session.exec(base)
        all_rows = count_result.all()

        # Filter by capability in-memory (JSON column)
        if capability is not None:
            all_rows = [r for r in all_rows if capability in (r.capabilities or [])]

        total = len(all_rows)

        stmt = base.offset(offset).limit(limit).order_by(
            ModelRegistryEntry.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        entries = list(result.all())

        if capability is not None:
            entries = [e for e in entries if capability in (e.capabilities or [])]

        return entries, total

    @staticmethod
    async def update(
        session: AsyncSession,
        entry_id: UUID,
        data: dict[str, Any],
    ) -> ModelRegistryEntry | None:
        """Partial-update a registry entry. Returns None if not found."""
        entry = await session.get(ModelRegistryEntry, entry_id)
        if entry is None:
            return None
        for key, value in data.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry

    @staticmethod
    async def delete(session: AsyncSession, entry_id: UUID) -> bool:
        """Delete a registry entry. Returns True if deleted."""
        entry = await session.get(ModelRegistryEntry, entry_id)
        if entry is None:
            return False
        await session.delete(entry)
        await session.commit()
        return True

    @staticmethod
    async def update_health(
        session: AsyncSession,
        entry_id: UUID,
        *,
        health_status: str,
        error_rate: float | None = None,
        avg_latency_ms: float | None = None,
    ) -> ModelRegistryEntry | None:
        """Update health metrics for a model entry."""
        data: dict[str, Any] = {"health_status": health_status}
        if error_rate is not None:
            data["error_rate"] = error_rate
        if avg_latency_ms is not None:
            data["avg_latency_ms"] = avg_latency_ms
        return await ModelRegistry.update(session, entry_id, data)


# ── Routing Rule CRUD ───────────────────────────────────────────────


class RoutingRuleService:
    """CRUD operations for routing rules."""

    @staticmethod
    async def create(session: AsyncSession, rule: RoutingRule) -> RoutingRule:
        """Persist a new routing rule."""
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule

    @staticmethod
    async def get(session: AsyncSession, rule_id: UUID) -> RoutingRule | None:
        """Return a routing rule by ID."""
        return await session.get(RoutingRule, rule_id)

    @staticmethod
    async def list(
        session: AsyncSession,
        *,
        is_active: bool | None = None,
        strategy: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[RoutingRule], int]:
        """Return paginated routing rules with optional filters."""
        base = select(RoutingRule)
        if is_active is not None:
            base = base.where(RoutingRule.is_active == is_active)
        if strategy is not None:
            base = base.where(RoutingRule.strategy == strategy)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            RoutingRule.priority.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        rules = list(result.all())
        return rules, total

    @staticmethod
    async def update(
        session: AsyncSession,
        rule_id: UUID,
        data: dict[str, Any],
    ) -> RoutingRule | None:
        """Partial-update a routing rule. Returns None if not found."""
        rule = await session.get(RoutingRule, rule_id)
        if rule is None:
            return None
        for key, value in data.items():
            if hasattr(rule, key):
                setattr(rule, key, value)
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule

    @staticmethod
    async def delete(session: AsyncSession, rule_id: UUID) -> bool:
        """Delete a routing rule. Returns True if deleted."""
        rule = await session.get(RoutingRule, rule_id)
        if rule is None:
            return False
        await session.delete(rule)
        await session.commit()
        return True


# ── Routing Decision Engine ─────────────────────────────────────────

# Valid built-in strategy names
STRATEGIES = frozenset({
    "cost_optimized",
    "performance_optimized",
    "balanced",
    "sensitive",
    "custom",
})


class RoutingEngine:
    """Selects the optimal model for a request using multi-factor scoring.

    The engine loads active routing rules from the database, matches them
    against request context (department, agent, data classification, etc.),
    and scores every eligible model in the registry.  The highest-scoring
    model is returned together with a fallback chain.

    Designed for <200ms p95 decision latency.
    """

    @staticmethod
    async def route(
        session: AsyncSession,
        *,
        department_id: UUID | None = None,
        agent_id: UUID | None = None,
        required_capabilities: list[str] | None = None,
        data_classification: str = "general",
        strategy_override: str | None = None,
    ) -> dict[str, Any]:
        """Select the best model for the given request context.

        Returns a dict with ``model``, ``fallbacks``, ``strategy``,
        ``scores``, and ``decision_ms``.
        """
        start = time.monotonic()

        # 1. Fetch applicable rule (most specific + highest priority)
        rule = await RoutingEngine._resolve_rule(
            session,
            department_id=department_id,
            agent_id=agent_id,
            strategy_override=strategy_override,
        )
        strategy = strategy_override or (rule.strategy if rule else "balanced")

        # 2. Fetch eligible models
        models = await RoutingEngine._eligible_models(
            session,
            required_capabilities=required_capabilities,
            data_classification=data_classification,
        )

        if not models:
            elapsed = (time.monotonic() - start) * 1000
            return {
                "model": None,
                "fallbacks": [],
                "strategy": strategy,
                "scores": {},
                "decision_ms": round(elapsed, 2),
            }

        # 3. Score each model
        weights = RoutingEngine._weights(rule, strategy)
        scored = [
            (m, RoutingEngine._score(m, weights, strategy))
            for m in models
        ]
        scored.sort(key=lambda t: t[1], reverse=True)

        primary = scored[0][0]
        fallbacks = [s[0].model_dump(mode="json") for s in scored[1:4]]
        scores = {str(s[0].id): round(s[1], 4) for s in scored}

        # Append rule-defined fallback chain entries not already present
        if rule and rule.fallback_chain:
            seen_ids = {str(primary.id)} | {f["id"] for f in fallbacks}
            for fid in rule.fallback_chain:
                if fid not in seen_ids:
                    fb_model = await session.get(ModelRegistryEntry, fid)
                    if fb_model and fb_model.is_active:
                        fallbacks.append(fb_model.model_dump(mode="json"))
                        seen_ids.add(fid)

        elapsed = (time.monotonic() - start) * 1000
        return {
            "model": primary.model_dump(mode="json"),
            "fallbacks": fallbacks,
            "strategy": strategy,
            "scores": scores,
            "decision_ms": round(elapsed, 2),
        }

    # ── internals ────────────────────────────────────────────────────

    @staticmethod
    async def _resolve_rule(
        session: AsyncSession,
        *,
        department_id: UUID | None,
        agent_id: UUID | None,
        strategy_override: str | None,
    ) -> RoutingRule | None:
        """Find the highest-priority active rule matching the context."""
        stmt = (
            select(RoutingRule)
            .where(RoutingRule.is_active == True)  # noqa: E712
            .order_by(RoutingRule.priority.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        rules = list(result.all())

        for rule in rules:
            # More specific rules (agent+dept) take precedence
            if rule.agent_id is not None and rule.agent_id != agent_id:
                continue
            if rule.department_id is not None and rule.department_id != department_id:
                continue
            if strategy_override and rule.strategy != strategy_override:
                continue
            return rule

        return None

    @staticmethod
    async def _eligible_models(
        session: AsyncSession,
        *,
        required_capabilities: list[str] | None,
        data_classification: str,
    ) -> list[ModelRegistryEntry]:
        """Fetch active, healthy models that meet capability and data requirements."""
        stmt = (
            select(ModelRegistryEntry)
            .where(ModelRegistryEntry.is_active == True)  # noqa: E712
            .where(ModelRegistryEntry.health_status != "unhealthy")
        )
        result = await session.exec(stmt)
        models = list(result.all())

        # Classification hierarchy: general < internal < restricted
        classification_rank = {"general": 0, "internal": 1, "restricted": 2}
        req_rank = classification_rank.get(data_classification, 0)

        filtered: list[ModelRegistryEntry] = []
        for m in models:
            model_rank = classification_rank.get(m.data_classification, 0)
            if model_rank < req_rank:
                continue  # model not cleared for this data level
            if required_capabilities:
                model_caps = set(m.capabilities or [])
                if not set(required_capabilities).issubset(model_caps):
                    continue
            filtered.append(m)

        return filtered

    @staticmethod
    def _weights(rule: RoutingRule | None, strategy: str) -> dict[str, float]:
        """Return scoring weights, applying strategy-specific defaults."""
        if rule:
            return {
                "cost": rule.weight_cost,
                "latency": rule.weight_latency,
                "capability": rule.weight_capability,
                "sensitivity": rule.weight_sensitivity,
            }
        presets: dict[str, dict[str, float]] = {
            "cost_optimized": {"cost": 0.6, "latency": 0.1, "capability": 0.2, "sensitivity": 0.1},
            "performance_optimized": {"cost": 0.1, "latency": 0.5, "capability": 0.3, "sensitivity": 0.1},
            "balanced": {"cost": 0.25, "latency": 0.25, "capability": 0.25, "sensitivity": 0.25},
            "sensitive": {"cost": 0.05, "latency": 0.05, "capability": 0.1, "sensitivity": 0.8},
        }
        return presets.get(strategy, presets["balanced"])

    @staticmethod
    def _score(model: ModelRegistryEntry, weights: dict[str, float], strategy: str) -> float:
        """Compute a 0–1 composite score for a model given weights.

        Higher is better.  Each factor is normalised to 0–1 so that
        weights act as direct multipliers.
        """
        # Cost score: cheaper is better (inverse, capped)
        total_cost = model.cost_per_input_token + model.cost_per_output_token
        cost_score = max(0.0, 1.0 - (total_cost / 100.0))  # $100/M tok = 0

        # Latency score: lower latency is better
        latency_score = max(0.0, 1.0 - (model.avg_latency_ms / 5000.0))

        # Capability score: more capabilities = higher
        cap_count = len(model.capabilities) if model.capabilities else 0
        capability_score = min(1.0, cap_count / 5.0)

        # Sensitivity score: on-prem or restricted gets full marks
        sensitivity_score = 0.5
        if model.is_on_prem:
            sensitivity_score = 1.0
        elif model.data_classification == "restricted":
            sensitivity_score = 0.9
        elif model.data_classification == "internal":
            sensitivity_score = 0.7

        # Health penalty
        health_mult = 1.0
        if model.health_status == "degraded":
            health_mult = 0.7

        raw = (
            weights.get("cost", 0.25) * cost_score
            + weights.get("latency", 0.25) * latency_score
            + weights.get("capability", 0.25) * capability_score
            + weights.get("sensitivity", 0.25) * sensitivity_score
        )
        return raw * health_mult


__all__ = [
    "ModelRegistry",
    "RoutingEngine",
    "RoutingRuleService",
]
