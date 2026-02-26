"""Plugin and Tool Pydantic schemas for the MCP Host Gateway."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResourceLimits(BaseModel):
    """Container resource constraints."""

    cpu: str = Field(default="0.5", description="CPU limit, e.g. '0.5' or '1'")
    memory: str = Field(default="512Mi", description="Memory limit, e.g. '512Mi'")


class ContainerConfig(BaseModel):
    """Container-type plugin configuration."""

    image: str = Field(..., description="Docker image reference")
    port: int = Field(default=8080, description="Container port to proxy")
    idle_timeout: int = Field(default=300, description="Seconds before idle container is stopped")
    resources: ResourceLimits = Field(default_factory=ResourceLimits)
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables injected at runtime"
    )


class ToolSchema(BaseModel):
    """Individual tool exposed by a plugin."""

    id: str = Field(..., description="Unique tool identifier, e.g. 'get_revenue'")
    description: str = Field(default="", description="Human-readable tool description")
    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for tool input"
    )
    can_forward: bool = Field(
        default=True,
        description=(
            "If False, execute via built-in Azure OpenAI; if True, forward to plugin backend."
        ),
    )


class Plugin(BaseModel):
    """Validated plugin definition loaded from a YAML file."""

    name: str = Field(..., description="Unique plugin slug, e.g. 'finance-revenue-mcp'")
    display_name: str = Field(default="", description="Human-readable label")
    version: str = Field(default="0.1.0")
    enabled: bool = Field(default=True)
    description: str = Field(default="")

    # Plugin type: 'builtin' | 'forward' | 'container'
    type: str = Field(default="forward", description="Plugin execution type")

    # For 'forward' and 'container' types
    endpoint: str | None = Field(default=None, description="Backend URL for 'forward' type")

    # For 'container' type
    container: ContainerConfig | None = Field(default=None)

    # Access control
    required_groups: list[str] = Field(
        default_factory=list,
        description="Entra group IDs or names that can access this plugin",
    )

    # Tools exposed by this plugin
    tools: list[ToolSchema] = Field(default_factory=list)

    # Transport (legacy compatibility)
    transport: str = Field(default="http")
    auth_type: str = Field(default="none")
    auth_header: str = Field(default="Authorization")

    # Free-form extra metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
