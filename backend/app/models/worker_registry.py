"""SQLModel for the worker heartbeat registry.

Schema bound by: Phase 6 — Worker Plane. Each running worker process
upserts a row into ``worker_heartbeats`` on start, refreshes
``last_heartbeat_at`` periodically, and deletes the row on graceful
shutdown.

Stale rows (worker silent for ``max_silence_seconds`` = 600s by default)
are pruned by the worker registry; their leases are reclaimed via the
dispatcher's ``reclaim_expired_runs`` primitive — see
``backend/app/services/run_dispatcher.py`` (when W1.3 lands its lease
machinery) and ``backend/app/services/worker_registry.py``.

This module is OWNED by WS4 (Worker Plane Squad). The SOURCE OF TRUTH
for the schema is migration 0008_worker_registry. Edit them together.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC for TIMESTAMP WITHOUT TIME ZONE columns (matches workflow.py)."""
    return datetime.utcnow()


class WorkerHeartbeat(SQLModel, table=True):
    """Per-process worker registration row.

    A worker UPSERTs this on start, refreshes ``last_heartbeat_at`` every
    ``HEARTBEAT_INTERVAL`` seconds, and DELETEs it on graceful shutdown.

    Concurrency: ``worker_id`` is the primary key, so two registrations
    for the same id collapse to one row (the latest wins on UPSERT).
    Lease ownership is governed by ``workflow_runs.lease_owner`` on the
    run side, NOT this table — this table is only the liveness signal.
    """

    __tablename__ = "worker_heartbeats"

    worker_id: str = Field(primary_key=True)
    hostname: str
    pid: int
    started_at: datetime = Field(default_factory=_utcnow)
    last_heartbeat_at: datetime = Field(default_factory=_utcnow, index=True)
    lease_count: int = Field(default=0)
    capabilities: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    version: str | None = Field(default=None)
    tenant_affinity: list[str] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )


__all__ = ["WorkerHeartbeat"]
