"""Pydantic models for the Natural Language → Agent Wizard pipeline."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ── Step 1: Describe ────────────────────────────────────────────────


class NLBuildRequest(BaseModel):
    """Incoming natural-language description of a desired agent."""

    description: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Free-text description of the agent to build",
    )
    workspace_id: str | None = Field(
        default=None,
        description="Optional workspace scope",
    )


class TemplateMatch(BaseModel):
    """A template that partially matches the user intent."""

    template_id: str
    template_name: str
    similarity: float = Field(ge=0.0, le=1.0)


class NLAnalysis(BaseModel):
    """Result of the *describe* step — NLP analysis of the request."""

    model_config = ConfigDict(populate_by_name=True)

    analysis_id: str = Field(default_factory=lambda: uuid4().hex)
    original_description: str = Field(alias="description")
    intents: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    connectors_detected: list[str] = Field(default_factory=list)
    template_matches: list[TemplateMatch] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ── Step 2: Plan ────────────────────────────────────────────────────


class PlannedNode(BaseModel):
    """A single node in the planned agent graph."""

    node_id: str
    label: str
    node_type: str = "default"
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class PlannedEdge(BaseModel):
    """A directed edge between two planned nodes."""

    source: str
    target: str
    condition: str = ""


class ModelRequirement(BaseModel):
    """An LLM model required by the planned agent."""

    provider: str
    model_id: str
    purpose: str = ""


class ConnectorRequirement(BaseModel):
    """An external connector required by the planned agent."""

    connector_type: str
    name: str
    purpose: str = ""


class CredentialRequirement(BaseModel):
    """A Vault credential path needed at runtime."""

    vault_path: str
    connector_type: str
    description: str = ""


class NLBuildPlan(BaseModel):
    """Result of the *plan* step — structured build plan."""

    plan_id: str = Field(default_factory=lambda: uuid4().hex)
    analysis_id: str
    nodes: list[PlannedNode] = Field(default_factory=list)
    edges: list[PlannedEdge] = Field(default_factory=list)
    models_needed: list[ModelRequirement] = Field(default_factory=list)
    connectors_needed: list[ConnectorRequirement] = Field(default_factory=list)
    credential_requirements: list[CredentialRequirement] = Field(default_factory=list)
    estimated_cost: float = 0.0
    security_notes: list[str] = Field(default_factory=list)


# ── Step 3: Build ───────────────────────────────────────────────────


class GeneratedAgent(BaseModel):
    """Result of the *build* step — a fully generated agent definition."""

    agent_name: str
    tenant_id: str
    workspace_id: str = ""
    owner_id: str = ""
    graph_definition: dict[str, Any] = Field(default_factory=dict)
    python_source: str = ""
    credential_manifest: list[CredentialRequirement] = Field(default_factory=list)
    plan_id: str = ""


# ── Step 4: Validate ────────────────────────────────────────────────


class SecurityIssue(BaseModel):
    """A single security finding from the validation scan."""

    severity: str = "warning"
    code: str = ""
    message: str = ""


class ValidationResult(BaseModel):
    """Result of the *validate* step."""

    passed: bool = True
    security_issues: list[SecurityIssue] = Field(default_factory=list)
    cost_estimate: float = 0.0
    compliance_notes: list[str] = Field(default_factory=list)


# ── Refine ──────────────────────────────────────────────────────────


class RefineRequest(BaseModel):
    """Request body for the iterative refinement endpoint."""

    agent: GeneratedAgent
    feedback: str = Field(..., min_length=1, max_length=2000)
    iteration: int = Field(default=1, ge=1, le=3)


__all__ = [
    "ConnectorRequirement",
    "CredentialRequirement",
    "GeneratedAgent",
    "ModelRequirement",
    "NLAnalysis",
    "NLBuildPlan",
    "NLBuildRequest",
    "PlannedEdge",
    "PlannedNode",
    "RefineRequest",
    "SecurityIssue",
    "TemplateMatch",
    "ValidationResult",
]
