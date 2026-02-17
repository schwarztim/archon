"""Typed Pydantic schemas for Agent sub-configurations and API payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Sub-schemas ─────────────────────────────────────────────────────


class AgentStep(BaseModel):
    """A single step in an agent's execution graph."""

    name: str
    type: str = "action"
    config: dict[str, Any] = Field(default_factory=dict)
    next: str | None = None


class ToolBinding(BaseModel):
    """A tool binding that an agent can invoke during execution."""

    name: str
    type: str = "function"
    config: dict[str, Any] = Field(default_factory=dict)
    required: bool = False


class LLMConfig(BaseModel):
    """LLM provider configuration for an agent."""

    provider: str = "openai"
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    extra: dict[str, Any] = Field(default_factory=dict)


class RAGConfig(BaseModel):
    """Retrieval-Augmented Generation configuration."""

    enabled: bool = False
    collection_id: str | None = None
    top_k: int = 5
    similarity_threshold: float = 0.7
    extra: dict[str, Any] = Field(default_factory=dict)


class MCPConfig(BaseModel):
    """Model Context Protocol configuration."""

    enabled: bool = False
    server_url: str | None = None
    tools: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class SecurityPolicy(BaseModel):
    """Security constraints applied to an agent."""

    max_tokens_per_request: int = 10000
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    require_approval: bool = False
    dlp_enabled: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


# ── Agent Create / Update schemas ───────────────────────────────────


class AgentCreate(BaseModel):
    """Payload for creating an agent with typed sub-schemas."""

    name: str
    description: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    owner_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    steps: list[AgentStep] | None = None
    tools: list[ToolBinding] | None = None
    llm_config: LLMConfig | None = None
    rag_config: RAGConfig | None = None
    mcp_config: MCPConfig | None = None
    security_policy: SecurityPolicy | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    graph_definition: dict[str, Any] | None = None
    group_id: str | None = None


class AgentUpdate(BaseModel):
    """Payload for partially updating an agent with typed sub-schemas."""

    name: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None
    status: str | None = None
    tags: list[str] | None = None
    steps: list[AgentStep] | None = None
    tools: list[ToolBinding] | None = None
    llm_config: LLMConfig | None = None
    rag_config: RAGConfig | None = None
    mcp_config: MCPConfig | None = None
    security_policy: SecurityPolicy | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    graph_definition: dict[str, Any] | None = None
    group_id: str | None = None


# ── Execution request schema ────────────────────────────────────────


class ExecuteAgentRequest(BaseModel):
    """Payload for POST /api/v1/agents/{agent_id}/execute."""

    input: dict[str, Any] = Field(default_factory=dict)
    config_overrides: dict[str, Any] = Field(default_factory=dict)
