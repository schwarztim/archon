"""RunChain model — ADR-008 §6.

Captures the chain of runs created by continue-as-new (W12).

Schema is frozen by ADR-008. Table name ``run_chains``.

WorkflowRun itself does NOT gain chain_id / parent_run_id columns —
that preserves the XOR contract and keeps WorkflowRun focused on
execution state. Visibility queries that want chain context join
through RunChain.run_id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class RunChain(SQLModel, table=True):
    """Ordered chain entry created by continue-as-new.

    Each continue-as-new creates one RunChain row:
    - chain_id   shared across all runs in the chain (search by this)
    - root_run_id  the originating run
    - parent_run_id  the run that issued continue-as-new
    - run_id  the new child run created by continue-as-new
    - generation_number  0 for root, 1 for first child, etc.

    The root run's entry has parent_run_id == run_id (self-referential)
    and generation_number == 0.

    ADR-008 §6 locks the table name, columns, constraints, and indexes.
    """

    __tablename__ = "run_chains"
    __table_args__ = (
        UniqueConstraint(
            "chain_id",
            "generation_number",
            name="uq_run_chain_chain_generation",
        ),
        UniqueConstraint(
            "run_id",
            name="uq_run_chain_run_id",
        ),
        Index("ix_run_chain_chain", "chain_id", "generation_number"),
        Index("ix_run_chain_root", "root_run_id"),
        Index("ix_run_chain_parent", "parent_run_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    chain_id: UUID = Field(index=True)
    root_run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    parent_run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    generation_number: int = Field()
    compacted_state: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    continue_reason: str = Field(
        sa_column=Column(SAText, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["RunChain"]
