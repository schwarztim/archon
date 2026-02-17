"""SQLModel database models for the Archon intelligent router."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class RoutingRule(SQLModel, table=True):
    """Configurable rule that influences model selection for requests."""

    __tablename__ = "routing_rules"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    strategy: str = Field(default="balanced")  # cost_optimized | performance_optimized | balanced | sensitive | custom
    priority: int = Field(default=0)  # Higher = evaluated first
    is_active: bool = Field(default=True)

    # Scope filters — when set, rule only applies to matching requests
    department_id: UUID | None = Field(default=None, index=True)
    agent_id: UUID | None = Field(default=None, index=True, foreign_key="agents.id")

    # Factor weights for multi-factor scoring (0.0–1.0 each)
    weight_cost: float = Field(default=0.25)
    weight_latency: float = Field(default=0.25)
    weight_capability: float = Field(default=0.25)
    weight_sensitivity: float = Field(default=0.25)

    # Optional constraints
    conditions: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )  # e.g. {"time_range": "off-hours", "budget_remaining_below": 100}

    # Fallback chain — ordered list of model registry entry IDs
    fallback_chain: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ModelRegistryEntry(SQLModel, table=True):
    """Registry entry tracking an available LLM, its capabilities, cost, and health."""

    __tablename__ = "model_registry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    provider: str = Field(index=True)  # openai | anthropic | google | mistral | cohere | local
    model_id: str  # Provider-specific model identifier, e.g. "gpt-4o"

    # Capabilities
    capabilities: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )  # e.g. ["chat", "code", "vision", "function_calling"]
    context_window: int = Field(default=4096)
    supports_streaming: bool = Field(default=True)

    # Cost (per 1M tokens, USD)
    cost_per_input_token: float = Field(default=0.0)
    cost_per_output_token: float = Field(default=0.0)

    # Performance profile
    speed_tier: str = Field(default="medium")  # fast | medium | slow
    avg_latency_ms: float = Field(default=500.0)

    # Data classification
    data_classification: str = Field(default="general")  # general | internal | restricted
    is_on_prem: bool = Field(default=False)

    # Health / availability
    is_active: bool = Field(default=True)
    health_status: str = Field(default="healthy")  # healthy | degraded | unhealthy
    error_rate: float = Field(default=0.0)  # 0.0–1.0

    # Arbitrary provider config / metadata
    config: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    # Vault secret path for API key storage
    vault_secret_path: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ── Enterprise Pydantic schemas (non-table) ────────────────────────


class RoutingRequest(SQLModel):
    """Incoming request to be routed to an optimal model provider."""

    task_type: str = Field(description="Type of task: chat, code, vision, embedding, etc.")
    input_tokens_estimate: int = Field(default=500, ge=0)
    data_classification: str = Field(default="general", description="general | internal | restricted")
    latency_requirement: str = Field(default="medium", description="fast | medium | slow")
    budget_limit: float | None = Field(default=None, ge=0.0, description="Max cost in USD for this request")
    required_capabilities: list[str] = Field(default_factory=list)
    geo_residency: str | None = Field(default=None, description="Required data residency region")


class DecisionFactor(SQLModel):
    """Individual scoring factor contributing to a routing decision."""

    factor: str
    weight: float
    score: float
    weighted_score: float
    explanation: str = ""


class RoutingDecision(SQLModel):
    """Result of the intelligent routing engine with full explainability."""

    selected_model: str
    selected_provider: str
    score: float
    explanation: str
    fallback_chain: list[str] = Field(default_factory=list)
    decision_factors: list[DecisionFactor] = Field(default_factory=list)
    decision_ms: float = 0.0
    data_classification_met: bool = True


class ModelProvider(SQLModel):
    """Enterprise model provider registration payload / response."""

    id: UUID | None = Field(default=None)
    name: str
    api_type: str = Field(description="openai | anthropic | google | mistral | cohere | local")
    model_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    cost_per_1k_tokens: float = Field(default=0.0, ge=0.0)
    avg_latency_ms: float = Field(default=500.0, ge=0.0)
    data_classification_level: str = Field(default="general", description="general | internal | restricted")
    geo_residency: str = Field(default="us", description="Data residency region")
    is_active: bool = True


class RoutingPolicy(SQLModel):
    """Per-tenant routing weight configuration."""

    cost_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    latency_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    quality_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    data_residency_weight: float = Field(default=0.25, ge=0.0, le=1.0)


class ProviderHealth(SQLModel):
    """Health status for a registered model provider."""

    provider_id: str
    provider_name: str
    status: str = Field(description="healthy | degraded | unhealthy | circuit_open")
    latency_p50: float = 0.0
    latency_p99: float = 0.0
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    circuit_breaker_status: str = Field(default="closed", description="closed | open | half_open")
    consecutive_failures: int = 0


class RoutingStats(SQLModel):
    """Aggregated routing statistics for a tenant."""

    total_requests: int = 0
    avg_decision_ms: float = 0.0
    top_models: list[dict[str, Any]] = Field(default_factory=list)
    fallback_rate: float = 0.0
    circuit_breaker_trips: int = 0


__all__ = [
    "DecisionFactor",
    "ModelProvider",
    "ModelRegistryEntry",
    "ProviderHealth",
    "RoutingDecision",
    "RoutingPolicy",
    "RoutingRequest",
    "RoutingRule",
    "RoutingStats",
]
