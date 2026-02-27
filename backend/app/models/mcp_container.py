"""SQLModel database model for MCP Server Container management (ToolHive pattern)."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class MCPServerContainer(SQLModel, table=True):
    """Lifecycle record for a managed MCP server Docker container."""

    __tablename__ = "mcp_server_containers"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True)
    image: str  # Docker image name
    tag: str = Field(default="latest")
    status: str = Field(default="created")  # created, pulling, running, stopped, error
    container_id: str | None = Field(default=None)  # Docker container ID
    port_mappings: dict | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    env_vars: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    volumes: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    health_check_url: str | None = Field(default=None)
    labels: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    resource_limits: dict | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    restart_policy: str = Field(default="unless-stopped")
    network: str = Field(default="archon-mcp")
    tenant_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_health_check: datetime | None = Field(default=None)
    health_status: str | None = Field(default=None)  # healthy, unhealthy, unknown
    error_message: str | None = Field(default=None)


__all__ = ["MCPServerContainer"]
