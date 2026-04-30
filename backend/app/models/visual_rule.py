"""SQLModel table definition for persisted visual routing rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class VisualRule(SQLModel, table=True):
    """Persistent visual routing rule.

    Replaces the ``_visual_rules_store`` in-memory list in
    ``backend/app/routes/router.py``.
    """

    __tablename__ = "visual_rules"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # tenant_id added by A15 (0006_add_tenant_id_to_visual_rule migration).
    # nullable=True intentionally — backfill is operator's responsibility before
    # enforcing NOT NULL in production. Route handlers should filter by tenant_id.
    tenant_id: Optional[UUID] = Field(default=None, index=True)
    name: str
    priority: int = 0
    conditions: Optional[Any] = Field(default_factory=list, sa_column=Column(JSON))
    action: Optional[Any] = Field(default_factory=dict, sa_column=Column(JSON))
    is_active: bool = True
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
