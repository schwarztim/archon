"""Artifact model — Phase 5 large-output persistence.

Owned by WS5 / Observability+Artifacts Squad. Phase 5 of the master plan
introduces durable artifact storage so step outputs that exceed the inline
threshold do not bloat ``workflow_run_steps.output_data``. Instead, the
dispatcher persists the bytes via ``LocalArtifactStore`` (or another backend
in the future) and rewrites the step's ``output_data`` to a tiny
``_artifact_ref`` reference.

Design notes
------------

* ``run_id`` is nullable so artifacts may be attached to ad-hoc resources
  (e.g. system-generated reports) that are not bound to a specific run.
  When set, FK cascade-deletes artifact rows when their owning run is
  deleted, so stale rows cannot accumulate.

* ``content_hash`` is the SHA-256 hex of the stored bytes. It is indexed
  to support deduplication and integrity checks.

* ``storage_backend`` carries the backend key (``"local"``, ``"s3"`` once
  implemented). ``storage_uri`` is the backend-specific addressing string
  — for ``LocalArtifactStore`` this is an absolute filesystem path.

* ``retention_days`` + ``expires_at``: ``expires_at`` is the authoritative
  field consulted by ``expire_old_artifacts``; ``retention_days`` is kept
  separately for human reference / future re-derivation.

* ``meta`` (NOT ``metadata``): SQLModel reserves ``metadata`` on the
  declarative class for SQLAlchemy's MetaData object. Naming the JSON
  column ``meta`` avoids the clash entirely. The REST surface still
  exposes the field as ``metadata`` in serialised responses for caller
  ergonomics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class Artifact(SQLModel, table=True):
    """Persisted large-output blob with retention metadata.

    Lifecycle:
      * ``store_artifact`` writes the bytes via the storage backend, then
        inserts the row.
      * ``expire_old_artifacts`` sweeps rows whose ``expires_at`` is in
        the past and deletes both the storage object and the row.
      * ``get_artifact`` is tenant-scoped — cross-tenant access returns
        no row (the route then 404s, never leaking existence).
    """

    __tablename__ = "artifacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    step_id: str | None = Field(default=None)
    tenant_id: UUID | None = Field(default=None, index=True)
    content_type: str = Field(default="application/octet-stream")
    content_hash: str = Field(index=True)  # sha256 hex of the stored bytes
    size_bytes: int = Field(default=0)
    storage_backend: str = Field(default="local")
    storage_uri: str = Field(default="")
    retention_days: int | None = Field(default=None)
    expires_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    meta: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )


__all__ = ["Artifact"]
