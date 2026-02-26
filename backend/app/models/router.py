"""SQLModel database models for the Archon intelligent router."""

from __future__ import annotations

import uuid as _uuid_module
from datetime import datetime, timezone
from typing import Any, Optional
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
    description: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    strategy: str = Field(
        default="balanced"
    )  # cost_optimized | performance_optimized | balanced | sensitive | custom
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
    provider: str = Field(
        index=True
    )  # openai | anthropic | google | mistral | cohere | local
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
    data_classification: str = Field(
        default="general"
    )  # general | internal | restricted
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


class ProviderHealthHistory(SQLModel, table=True):
    """Persisted record of a single provider health-check result."""

    __tablename__ = "provider_health_history"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    provider_id: UUID = Field(foreign_key="model_registry.id", index=True)
    checked_at: datetime = Field(default_factory=_utcnow, index=True)
    is_healthy: bool
    latency_ms: int
    error_message: Optional[str] = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    status_code: Optional[int] = Field(default=None)


# ── Enterprise Pydantic schemas (non-table) ────────────────────────


class RoutingRequest(SQLModel):
    """Incoming request to be routed to an optimal model provider."""

    task_type: str = Field(
        description="Type of task: chat, code, vision, embedding, etc."
    )
    input_tokens_estimate: int = Field(default=500, ge=0)
    data_classification: str = Field(
        default="general", description="general | internal | restricted"
    )
    latency_requirement: str = Field(
        default="medium", description="fast | medium | slow"
    )
    budget_limit: float | None = Field(
        default=None, ge=0.0, description="Max cost in USD for this request"
    )
    required_capabilities: list[str] = Field(default_factory=list)
    geo_residency: str | None = Field(
        default=None, description="Required data residency region"
    )


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
    api_type: str = Field(
        description="openai | anthropic | google | mistral | cohere | local"
    )
    model_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    cost_per_1k_tokens: float = Field(default=0.0, ge=0.0)
    avg_latency_ms: float = Field(default=500.0, ge=0.0)
    data_classification_level: str = Field(
        default="general", description="general | internal | restricted"
    )
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
    circuit_breaker_status: str = Field(
        default="closed", description="closed | open | half_open"
    )
    consecutive_failures: int = 0


class RoutingStats(SQLModel):
    """Aggregated routing statistics for a tenant."""

    total_requests: int = 0
    avg_decision_ms: float = 0.0
    top_models: list[dict[str, Any]] = Field(default_factory=list)
    fallback_rate: float = 0.0
    circuit_breaker_trips: int = 0


# ── Visual Routing Rule schemas ─────────────────────────────────────


class RoutingCondition(SQLModel):
    """A single condition in a visual routing rule."""

    field: str = Field(
        description="capability | max_cost | min_context | sensitivity_level | tenant_tier | time_of_day | model_preference"
    )
    operator: str = Field(
        description="equals | not_equals | contains | greater_than | less_than | in | not_in"
    )
    value: str | float | list[str] = Field(description="Condition value")


class VisualRoutingRule(SQLModel):
    """A routing rule with structured conditions for the visual builder."""

    id: UUID | None = Field(default=None)
    name: str
    description: str | None = None
    conditions: list[RoutingCondition] = Field(default_factory=list)
    target_model_id: str
    priority: int = 0
    enabled: bool = True


class VisualRouteRequest(SQLModel):
    """Request payload for the visual routing decision endpoint."""

    capability: str | None = Field(
        default=None,
        description="chat | completion | embedding | vision | function_calling",
    )
    sensitivity_level: str | None = Field(
        default=None, description="low | medium | high | critical"
    )
    max_cost: float | None = Field(
        default=None, ge=0.0, description="Max cost per 1K tokens"
    )
    min_context: int | None = Field(
        default=None, ge=0, description="Min context window size"
    )
    tenant_tier: str | None = Field(
        default=None, description="free | standard | premium | enterprise"
    )
    preferred_model: str | None = Field(
        default=None, description="Preferred model family"
    )


class VisualRouteDecision(SQLModel):
    """Response from the visual routing decision endpoint with explanation."""

    model_id: str
    model_name: str
    provider_id: str
    provider_name: str
    reason: str
    alternatives: list[dict[str, str]] = Field(default_factory=list)


class FallbackChainConfig(SQLModel):
    """Ordered list of fallback model IDs."""

    model_ids: list[str] = Field(default_factory=list)


# ── Provider Credential schemas ─────────────────────────────────────


class CredentialField(SQLModel):
    """Definition for a single credential field in a provider schema."""

    name: str
    label: str
    field_type: str = Field(
        default="password", description="password | text | url | select"
    )
    required: bool = True
    placeholder: str = ""
    description: str = ""


class ProviderCredentialSchema(SQLModel):
    """Provider type-specific credential form schema."""

    provider_type: str
    label: str
    fields: list[CredentialField] = Field(default_factory=list)


class TestConnectionResult(SQLModel):
    """Result of testing provider connectivity."""

    success: bool
    latency_ms: float = 0.0
    models_found: int = 0
    message: str = ""
    error: str | None = None


class ProviderHealthDetail(SQLModel):
    """Detailed provider health with circuit breaker and metrics."""

    provider_id: str
    provider_name: str
    status: str = Field(description="healthy | degraded | unhealthy | circuit_open")
    metrics: dict[str, Any] = Field(default_factory=dict)
    circuit_breaker: dict[str, Any] = Field(default_factory=dict)


# ── Credential Schema Registry ──────────────────────────────────────


PROVIDER_CREDENTIAL_SCHEMAS: dict[str, ProviderCredentialSchema] = {
    "openai": ProviderCredentialSchema(
        provider_type="openai",
        label="OpenAI",
        fields=[CredentialField(name="api_key", label="API Key", placeholder="sk-...")],
    ),
    "anthropic": ProviderCredentialSchema(
        provider_type="anthropic",
        label="Anthropic",
        fields=[
            CredentialField(name="api_key", label="API Key", placeholder="sk-ant-...")
        ],
    ),
    "azure_openai": ProviderCredentialSchema(
        provider_type="azure_openai",
        label="Azure OpenAI",
        fields=[
            CredentialField(name="api_key", label="API Key"),
            CredentialField(
                name="endpoint_url",
                label="Endpoint URL",
                field_type="url",
                placeholder="https://your-resource.openai.azure.com/",
            ),
            CredentialField(
                name="deployment_name", label="Deployment Name", field_type="text"
            ),
            CredentialField(
                name="api_version",
                label="API Version",
                field_type="text",
                placeholder="2024-02-01",
            ),
        ],
    ),
    "ollama": ProviderCredentialSchema(
        provider_type="ollama",
        label="Ollama",
        fields=[
            CredentialField(
                name="base_url",
                label="Base URL",
                field_type="url",
                required=True,
                placeholder="http://localhost:11434",
            ),
        ],
    ),
    "huggingface": ProviderCredentialSchema(
        provider_type="huggingface",
        label="HuggingFace",
        fields=[
            CredentialField(name="api_token", label="API Token"),
            CredentialField(
                name="endpoint_url",
                label="Endpoint URL",
                field_type="url",
                required=False,
            ),
        ],
    ),
    "google": ProviderCredentialSchema(
        provider_type="google",
        label="Google AI",
        fields=[
            CredentialField(name="api_key", label="API Key"),
            CredentialField(
                name="project_id", label="Project ID", field_type="text", required=False
            ),
        ],
    ),
    "aws_bedrock": ProviderCredentialSchema(
        provider_type="aws_bedrock",
        label="AWS Bedrock",
        fields=[
            CredentialField(
                name="access_key_id", label="Access Key ID", field_type="text"
            ),
            CredentialField(name="secret_access_key", label="Secret Access Key"),
            CredentialField(
                name="region",
                label="Region",
                field_type="text",
                placeholder="us-east-1",
            ),
        ],
    ),
    "custom": ProviderCredentialSchema(
        provider_type="custom",
        label="Custom / OpenAI-Compatible",
        fields=[
            CredentialField(name="api_key", label="API Key", required=False),
            CredentialField(
                name="base_url",
                label="Base URL",
                field_type="url",
                placeholder="https://api.example.com/v1",
            ),
        ],
    ),
}


__all__ = [
    "CredentialField",
    "DecisionFactor",
    "FallbackChainConfig",
    "ModelProvider",
    "ModelRegistryEntry",
    "PROVIDER_CREDENTIAL_SCHEMAS",
    "ProviderCredentialSchema",
    "ProviderHealth",
    "ProviderHealthDetail",
    "ProviderHealthHistory",
    "RoutingCondition",
    "RoutingDecision",
    "RoutingPolicy",
    "RoutingRequest",
    "RoutingRule",
    "RoutingStats",
    "TestConnectionResult",
    "VisualRouteDecision",
    "VisualRouteRequest",
    "VisualRoutingRule",
]
