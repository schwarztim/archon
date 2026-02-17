"""Pydantic models for Live Interactive Components system."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ComponentCategory(str, Enum):
    """Supported interactive component categories."""

    CHART = "chart"
    FORM = "form"
    TABLE = "table"
    APPROVAL = "approval"
    CODE_EDITOR = "code_editor"
    MAP = "map"
    TIMELINE = "timeline"


class ComponentType(BaseModel):
    """Registered component type definition with RBAC requirements."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    category: ComponentCategory
    component_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")
    default_config: dict[str, Any] = Field(default_factory=dict)
    rbac_requirements: list[str] = Field(default_factory=list)
    tenant_id: str = ""
    created_by: str = ""
    created_at: datetime = Field(default_factory=_utcnow)

    model_config = {"populate_by_name": True}


class ComponentConfig(BaseModel):
    """Configuration for rendering a component instance."""

    type: ComponentCategory
    data_source: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    display_options: dict[str, Any] = Field(default_factory=dict)


class ComponentSession(BaseModel):
    """Session binding a user to an interactive component lifecycle."""

    session_id: UUID = Field(default_factory=uuid4)
    user_id: str
    tenant_id: str
    component_type: ComponentCategory
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None
    status: str = "active"


class RenderedComponent(BaseModel):
    """Server-side rendered component output with CSP nonce for sandboxing."""

    session_id: UUID
    html_content: str = ""
    scripts: list[str] = Field(default_factory=list)
    styles: list[str] = Field(default_factory=list)
    csp_nonce: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class ComponentAction(BaseModel):
    """User interaction event on a live component."""

    session_id: UUID
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


class ActionResult(BaseModel):
    """Result of processing a component action."""

    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    next_render: RenderedComponent | None = None


__all__ = [
    "ActionResult",
    "ComponentAction",
    "ComponentCategory",
    "ComponentConfig",
    "ComponentSession",
    "ComponentType",
    "RenderedComponent",
]
