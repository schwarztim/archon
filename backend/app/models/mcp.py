"""SQLModel database models for MCP interactive components."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# Valid component types
COMPONENT_TYPES = frozenset({"form", "chart", "table", "text", "code", "image"})

# Component lifecycle states
COMPONENT_STATES = frozenset({"mounted", "updated", "unmounted"})

# Session states
SESSION_STATES = frozenset({"active", "closed", "expired"})


class MCPComponent(SQLModel, table=True):
    """Interactive UI component that agents can embed in responses."""

    __tablename__ = "mcp_components"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(index=True, foreign_key="mcp_sessions.id")
    component_type: str = Field(index=True)  # form | chart | table | text | code | image
    props: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    state: str = Field(default="mounted")  # mounted | updated | unmounted
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MCPSession(SQLModel, table=True):
    """WebSocket session for interactive MCP component communication."""

    __tablename__ = "mcp_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID | None = Field(default=None, index=True, foreign_key="agents.id")
    user_id: UUID | None = Field(default=None, index=True, foreign_key="users.id")
    status: str = Field(default="active")  # active | closed | expired
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    closed_at: datetime | None = Field(default=None)


class MCPInteraction(SQLModel, table=True):
    """User interaction event on an MCP component (click, submit, change)."""

    __tablename__ = "mcp_interactions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(index=True, foreign_key="mcp_sessions.id")
    component_id: UUID = Field(index=True, foreign_key="mcp_components.id")
    event_type: str = Field(index=True)  # e.g. onClick, onChange, onSubmit
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "COMPONENT_STATES",
    "COMPONENT_TYPES",
    "MCPComponent",
    "MCPInteraction",
    "MCPSession",
    "SESSION_STATES",
]
