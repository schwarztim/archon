"""Improvement Engine models — gaps and proposals."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.utcnow()


class ImprovementGap(SQLModel, table=True):
    """A detected gap in compliance, health, performance, workflow, or security."""

    __tablename__ = "improvement_gaps"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    category: str  # compliance, health, performance, workflow, security
    source: str  # which system detected the gap
    severity: str = Field(default="medium")  # low, medium, high, critical
    title: str
    description: str
    evidence: dict | None = Field(default=None, sa_column=Column(JSON))
    affected_resources: dict | None = Field(default=None, sa_column=Column(JSON))
    tenant_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    resolved: bool = Field(default=False)
    resolved_at: datetime | None = Field(default=None)
    resolved_by_proposal_id: str | None = Field(default=None)


class ImprovementProposal(SQLModel, table=True):
    """An LLM-generated proposal addressing one or more improvement gaps."""

    __tablename__ = "improvement_proposals"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    gap_id: str | None = Field(default=None, index=True)
    title: str
    description: str
    proposed_changes: dict | None = Field(default=None, sa_column=Column(JSON))
    impact_analysis: dict | None = Field(default=None, sa_column=Column(JSON))
    confidence_score: float = Field(default=0.0)  # 0-1 LLM confidence
    status: str = Field(
        default="proposed"
    )  # proposed, approved, implementing, completed, rejected
    analysis_model: str | None = Field(default=None)  # which model generated it
    tenant_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    approved_by: str | None = Field(default=None)
    approved_at: datetime | None = Field(default=None)


__all__ = ["ImprovementGap", "ImprovementProposal"]
