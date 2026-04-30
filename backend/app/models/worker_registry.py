"""SQLModel for the worker heartbeat + worker registration registries.

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

W2 addendum: heartbeat liveness is folded into ``WorkerRegistration``
via inline columns (``last_heartbeat_at``, ``current_load``,
``in_flight_task_count``) rather than a separate ``WorkerHeartbeat`` row.
The inline approach has a smaller blast radius (one table, one upsert)
and lets capability-matching queries answer "is this worker live AND
underloaded?" in a single index scan. The legacy ``WorkerHeartbeat``
table is preserved for backwards compatibility and does not change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, Index
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC for TIMESTAMP WITHOUT TIME ZONE columns (matches workflow.py)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkerHeartbeat(SQLModel, table=True):
    """Per-process worker registration row.

    A worker UPSERTs this on start, refreshes ``last_heartbeat_at`` every
    ``HEARTBEAT_INTERVAL`` seconds, and DELETEs it on graceful shutdown.

    Concurrency: ``worker_id`` is the primary key, so two registrations
    for the same id collapse to one row (the latest wins on UPSERT).
    Lease ownership is governed by ``workflow_runs.lease_owner`` on the
    run side, NOT this table — this table is only the liveness signal.
    """

    __tablename__ = "worker_heartbeats"  # type: ignore[assignment]

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


class WorkerRegistration(SQLModel, table=True):
    """Worker identity + capability + liveness row (W2).

    Workers register at startup with the queues they poll, the activity
    types they can execute, and operating limits. The row is UPSERTed on
    boot and refreshed on each heartbeat tick.

    The ``status`` column drives capability matching:
        ``active``    — claim-eligible
        ``draining``  — finish in-flight tasks, do not claim new work
        ``stale``     — heartbeat exceeded threshold; reclaim leases

    Stale-lookup index ``(tenant_id, status, last_heartbeat_at)`` powers
    the worker-registry sweep that promotes silent ``active`` rows to
    ``stale`` after the heartbeat threshold elapses.
    """

    __tablename__ = "worker_registrations"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "ix_workerregistration_stale_lookup",
            "tenant_id",
            "status",
            "last_heartbeat_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    worker_name: str = Field()
    worker_version: str = Field()
    environment: str = Field(default="production")
    queue_names: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    capabilities: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    max_concurrency: int = Field(default=10)
    started_at: datetime = Field(default_factory=_utcnow)
    last_heartbeat_at: datetime = Field(default_factory=_utcnow, index=True)
    status: str = Field(default="active")
    deployment_id: str | None = Field(default=None)
    # Inlined liveness/load (no separate WorkerHeartbeat row for W2 — see
    # module docstring for the rationale).
    current_load: int = Field(default=0)
    in_flight_task_count: int = Field(default=0)


__all__ = ["WorkerHeartbeat", "WorkerRegistration"]
