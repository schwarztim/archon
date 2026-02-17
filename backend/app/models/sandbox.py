"""Pydantic models for the enterprise sandbox execution service."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────


class SandboxStatus(str, Enum):
    """Lifecycle states of a sandbox environment."""

    CREATING = "creating"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DESTROYED = "destroyed"


class ExecutionStatus(str, Enum):
    """Status of an individual execution within a sandbox."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    COST_LIMIT = "cost_limit"


class NetworkPolicy(str, Enum):
    """Network isolation policy for a sandbox."""

    NONE = "none"
    EGRESS_ONLY = "egress_only"
    RESTRICTED = "restricted"
    FULL = "full"


class StatisticalMethod(str, Enum):
    """Statistical method for arena comparisons."""

    PAIRED_T_TEST = "paired_t_test"
    WILCOXON = "wilcoxon"
    BOOTSTRAP = "bootstrap"


# ── Configuration models ─────────────────────────────────────────────


class ResourceLimits(BaseModel):
    """Resource constraints applied to a sandbox."""

    max_execution_time: int = Field(
        default=30, ge=1, le=300,
        description="Maximum execution time in seconds",
    )
    max_memory_mb: int = Field(
        default=256, ge=16, le=4096,
        description="Maximum memory in megabytes",
    )
    max_cpu_percent: int = Field(
        default=100, ge=10, le=400,
        description="CPU percentage limit",
    )
    max_cost_usd: float = Field(
        default=10.0, ge=0.01, le=1000.0,
        description="Maximum cost in USD before abort",
    )


class SandboxConfig(BaseModel):
    """Configuration for creating a sandbox environment."""

    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    ttl_seconds: int = Field(
        default=3600, ge=60, le=86400,
        description="Time-to-live in seconds before auto-cleanup",
    )
    network_policy: NetworkPolicy = Field(default=NetworkPolicy.RESTRICTED)
    allowed_connectors: list[str] = Field(
        default_factory=list,
        description="Connector IDs the sandbox may access",
    )


# ── Core models ──────────────────────────────────────────────────────


class Sandbox(BaseModel):
    """Represents an isolated sandbox execution environment."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    status: SandboxStatus = SandboxStatus.CREATING
    config: SandboxConfig = Field(default_factory=SandboxConfig)
    created_by: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    expires_at: datetime | None = None
    resource_usage: dict[str, Any] = Field(default_factory=dict)
    credential_lease_ids: list[str] = Field(default_factory=list)


class SandboxExecution(BaseModel):
    """Record of an agent execution inside a sandbox."""

    execution_id: UUID = Field(default_factory=uuid4)
    sandbox_id: UUID
    agent_id: UUID
    status: ExecutionStatus = ExecutionStatus.QUEUED
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] | None = None
    cost: float = 0.0
    duration_ms: float = 0.0
    credential_lease_id: str | None = None


# ── Arena models ─────────────────────────────────────────────────────


class ArenaTestCase(BaseModel):
    """A single test case for arena comparison."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = ""
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_output: dict[str, Any] | None = None
    scoring_weight: float = Field(default=1.0, ge=0.0)


class EvaluationCriteria(BaseModel):
    """Criteria used to evaluate agent outputs in arena mode."""

    accuracy_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    latency_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    cost_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    quality_weight: float = Field(default=0.2, ge=0.0, le=1.0)


class ArenaConfig(BaseModel):
    """Configuration for an arena A/B comparison."""

    agent_ids: list[UUID] = Field(..., min_length=2)
    test_cases: list[ArenaTestCase] = Field(..., min_length=1)
    evaluation_criteria: EvaluationCriteria = Field(
        default_factory=EvaluationCriteria,
    )
    statistical_method: StatisticalMethod = Field(
        default=StatisticalMethod.PAIRED_T_TEST,
    )


class AgentArenaMetrics(BaseModel):
    """Per-agent metrics from an arena run."""

    agent_id: UUID
    avg_latency_ms: float = 0.0
    avg_cost: float = 0.0
    accuracy_score: float = 0.0
    quality_score: float = 0.0
    composite_score: float = 0.0
    test_results: list[dict[str, Any]] = Field(default_factory=list)


class ArenaResult(BaseModel):
    """Result of an arena comparison across multiple agents."""

    arena_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    results_per_agent: list[AgentArenaMetrics] = Field(default_factory=list)
    winner: UUID | None = None
    confidence_score: float = 0.0
    statistical_method: StatisticalMethod = StatisticalMethod.PAIRED_T_TEST
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


# ── Benchmark models ────────────────────────────────────────────────


class BenchmarkTestCase(BaseModel):
    """A single test case within a benchmark set."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = ""
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_output: dict[str, Any] | None = None
    max_latency_ms: float | None = None
    max_cost: float | None = None


class ScoringRubric(BaseModel):
    """Scoring rubric for benchmark evaluation."""

    accuracy_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    latency_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    cost_weight: float = Field(default=0.25, ge=0.0, le=1.0)


class BenchmarkSet(BaseModel):
    """A standardized set of test cases for benchmarking agents."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    test_cases: list[BenchmarkTestCase] = Field(default_factory=list)
    scoring_rubric: ScoringRubric = Field(default_factory=ScoringRubric)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class BenchmarkResult(BaseModel):
    """Result of running an agent against a benchmark set."""

    benchmark_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    benchmark_set_id: UUID
    tenant_id: str
    scores: dict[str, float] = Field(default_factory=dict)
    rank: int | None = None
    percentile: float | None = None
    total_cost: float = 0.0
    total_duration_ms: float = 0.0
    test_results: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


__all__ = [
    "ArenaConfig",
    "ArenaResult",
    "ArenaTestCase",
    "AgentArenaMetrics",
    "BenchmarkResult",
    "BenchmarkSet",
    "BenchmarkTestCase",
    "EvaluationCriteria",
    "ExecutionStatus",
    "NetworkPolicy",
    "ResourceLimits",
    "Sandbox",
    "SandboxConfig",
    "SandboxExecution",
    "SandboxStatus",
    "ScoringRubric",
    "StatisticalMethod",
]
