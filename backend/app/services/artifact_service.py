"""Artifact service — large-output persistence with retention.

Owned by WS5 / Observability+Artifacts Squad. Phase 5 of the master plan.

Public surface
--------------

  store_artifact(session, *, tenant_id, run_id, step_id, content,
                 content_type, metadata=None, retention_days=30) -> Artifact
      Hash + persist + insert row. Caller commits.

  get_artifact(session, artifact_id, *, tenant_id=None) -> (Artifact, bytes)
      Tenant-scoped fetch. Returns ``None`` instead of raising on a
      cross-tenant access — the route translates that into a 404.

  maybe_persist_output_as_artifact(session, *, tenant_id, run_id, step_id,
                                    output_data, threshold_bytes=...) -> dict
      Threshold-based output extraction used by the dispatcher.

  expire_old_artifacts(session) -> int
      Delete rows whose ``expires_at`` is in the past + the underlying
      storage objects. Returns the count removed.

  list_artifacts(session, *, run_id=None, tenant_id=None,
                 limit=50, cursor=None) -> dict[str, Any]
      Cursor-paginated listing keyed by ``created_at`` + id.

  delete_artifact(session, artifact_id, *, tenant_id=None) -> bool
      Tenant-scoped delete (row + storage). Returns ``False`` when the
      caller does not own the artifact.

Design notes
------------

* The default storage backend is ``LocalArtifactStore``; tests inject a
  custom base directory via :func:`set_default_store`. Production wires
  up the real backend at app startup.

* ``maybe_persist_output_as_artifact`` is the dispatcher's hook. It must
  be cheap on the small-output path: ``json.dumps`` once, compare length,
  return the original dict unchanged. Only when the serialised payload
  exceeds the threshold do we hash + write + insert.

* All UTC timestamps are naive (no tzinfo) to match the workflow_runs
  schema convention. ``datetime.utcnow()`` keeps the stack homogeneous.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.artifact import Artifact
from app.storage.local_artifact_store import LocalArtifactStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Threshold + storage backend wiring
# ---------------------------------------------------------------------------

#: Outputs whose serialised JSON payload exceeds this threshold (bytes) are
#: persisted as artifacts and replaced by a tiny ``_artifact_ref`` shim.
DEFAULT_INLINE_THRESHOLD_BYTES = 32 * 1024  # 32 KiB

#: Default retention (days). Operators may pass an explicit value to
#: ``store_artifact`` to extend / shorten retention per artifact.
DEFAULT_RETENTION_DAYS = 30

_default_store: LocalArtifactStore | None = None


def get_default_store() -> LocalArtifactStore:
    """Return the process-wide default store (lazy init)."""
    global _default_store  # noqa: PLW0603
    if _default_store is None:
        _default_store = LocalArtifactStore()
    return _default_store


def set_default_store(store: LocalArtifactStore | None) -> None:
    """Override the process-wide default store. Tests use this fixture-style.

    Pass ``None`` to reset to the lazy default on next access.
    """
    global _default_store  # noqa: PLW0603
    _default_store = store


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


def _sha256_hex(payload: bytes) -> str:
    """Return the SHA-256 hex digest of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# store_artifact
# ---------------------------------------------------------------------------


async def store_artifact(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    run_id: UUID | None,
    step_id: str | None,
    content: bytes,
    content_type: str,
    metadata: dict[str, Any] | None = None,
    retention_days: int | None = DEFAULT_RETENTION_DAYS,
    store: LocalArtifactStore | None = None,
) -> Artifact:
    """Compute hash, write bytes, insert ``Artifact`` row, return it.

    Caller commits the surrounding transaction.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError(
            f"content must be bytes; got {type(content).__name__}"
        )

    backend = store or get_default_store()
    content_hash = _sha256_hex(content)
    now = _utcnow()
    expires_at: datetime | None = None
    if retention_days is not None and retention_days > 0:
        expires_at = now + timedelta(days=retention_days)

    artifact = Artifact(
        run_id=run_id,
        step_id=step_id,
        tenant_id=tenant_id,
        content_type=content_type,
        content_hash=content_hash,
        size_bytes=len(content),
        storage_backend="local",
        storage_uri="",  # filled in once we know the path
        retention_days=retention_days,
        expires_at=expires_at,
        created_at=now,
        meta=metadata or {},
    )
    # Persist bytes BEFORE the row so a failed write doesn't leave a
    # row whose storage_uri points nowhere. We name the file by the
    # artifact's pre-generated UUID.
    storage_uri = await backend.put(
        tenant_id=tenant_id,
        run_id=run_id,
        artifact_id=artifact.id,
        content=bytes(content),
    )
    artifact.storage_uri = storage_uri

    session.add(artifact)
    await session.flush()

    logger.debug(
        "artifact_service.store_artifact",
        extra={
            "artifact_id": str(artifact.id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "run_id": str(run_id) if run_id else None,
            "size_bytes": artifact.size_bytes,
            "content_type": content_type,
        },
    )
    return artifact


# ---------------------------------------------------------------------------
# get_artifact
# ---------------------------------------------------------------------------


async def get_artifact(
    session: AsyncSession,
    artifact_id: UUID,
    *,
    tenant_id: UUID | None = None,
    store: LocalArtifactStore | None = None,
) -> tuple[Artifact, bytes] | None:
    """Tenant-scoped artifact fetch.

    Returns ``(Artifact, bytes)`` on hit, ``None`` when the artifact
    does not exist OR is owned by a different tenant. The caller
    translates ``None`` into a 404 — never leaks existence.
    """
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        return None

    # Tenant scoping. ``tenant_id=None`` from the caller is the admin
    # path (no scoping). When the caller is tenant-scoped, an artifact
    # with no tenant_id is invisible to them (admin-only).
    if tenant_id is not None:
        if artifact.tenant_id is None or artifact.tenant_id != tenant_id:
            return None

    backend = store or get_default_store()
    try:
        content = await backend.get(artifact.storage_uri)
    except FileNotFoundError:
        # Storage object missing — the row is dangling. Surface as
        # "not found" so the caller doesn't see a 500.
        logger.warning(
            "artifact_service.get_artifact: storage object missing",
            extra={
                "artifact_id": str(artifact_id),
                "storage_uri": artifact.storage_uri,
            },
        )
        return None
    return artifact, content


# ---------------------------------------------------------------------------
# maybe_persist_output_as_artifact
# ---------------------------------------------------------------------------


async def maybe_persist_output_as_artifact(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    run_id: UUID | None,
    step_id: str | None,
    output_data: dict[str, Any] | None,
    threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES,
    retention_days: int | None = DEFAULT_RETENTION_DAYS,
    store: LocalArtifactStore | None = None,
) -> dict[str, Any] | None:
    """Replace large step outputs with an ``_artifact_ref`` shim.

    Behaviour:
      * ``output_data`` is None or already a shim → returned unchanged.
      * Serialised JSON is ≤ threshold → returned unchanged (inline path).
      * Otherwise: persist as artifact, return
        ``{"_artifact_ref": {"id": ..., "size_bytes": ..., "content_type":
          "application/json"}}``

    The function is intentionally cheap on the inline path so the
    dispatcher can call it on every step result.
    """
    if output_data is None:
        return None
    # Don't double-persist a previously extracted output.
    if isinstance(output_data, dict) and "_artifact_ref" in output_data:
        return output_data

    try:
        serialised = json.dumps(output_data, default=str).encode("utf-8")
    except (TypeError, ValueError):
        # Non-JSON-serialisable output — leave it for the engine layer.
        # We don't try to coerce; the caller controls the output shape.
        return output_data

    if len(serialised) <= threshold_bytes:
        return output_data

    artifact = await store_artifact(
        session,
        tenant_id=tenant_id,
        run_id=run_id,
        step_id=step_id,
        content=serialised,
        content_type="application/json",
        metadata={
            "extracted_from": "step_output",
            "step_id": step_id,
        },
        retention_days=retention_days,
        store=store,
    )

    return {
        "_artifact_ref": {
            "id": str(artifact.id),
            "size_bytes": artifact.size_bytes,
            "content_type": artifact.content_type,
            "content_hash": artifact.content_hash,
        }
    }


# ---------------------------------------------------------------------------
# expire_old_artifacts
# ---------------------------------------------------------------------------


async def expire_old_artifacts(
    session: AsyncSession,
    *,
    store: LocalArtifactStore | None = None,
) -> int:
    """Delete rows whose ``expires_at`` is in the past + their storage objects.

    Returns the number of artifacts removed. Errors deleting the storage
    object are logged but do NOT block the row deletion — a missing
    storage object is the same as a deleted one for retention purposes.
    Caller commits.
    """
    backend = store or get_default_store()
    now = _utcnow()
    stmt = (
        select(Artifact)
        .where(Artifact.expires_at.is_not(None))
        .where(Artifact.expires_at < now)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    count = 0
    for artifact in rows:
        try:
            await backend.delete(artifact.storage_uri)
        except OSError as exc:
            logger.warning(
                "artifact_service.expire_old_artifacts: storage delete failed",
                extra={
                    "artifact_id": str(artifact.id),
                    "storage_uri": artifact.storage_uri,
                    "error": str(exc),
                },
            )
        await session.delete(artifact)
        count += 1
    if count:
        logger.info(
            "artifact_service.expire_old_artifacts",
            extra={"count": count},
        )
    return count


# ---------------------------------------------------------------------------
# list_artifacts
# ---------------------------------------------------------------------------


async def list_artifacts(
    session: AsyncSession,
    *,
    run_id: UUID | None = None,
    tenant_id: UUID | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Cursor-paginated artifact listing.

    The cursor is the ISO timestamp of the previous page's last
    ``created_at`` value (no tie-breaker is needed because IDs are UUID
    v4 — ties are vanishingly rare and acceptable for a listing API).

    Returns ``{"data": [...], "next_cursor": str | None}``.
    """
    if limit <= 0:
        limit = 50
    if limit > 200:
        limit = 200

    stmt = select(Artifact)
    if run_id is not None:
        stmt = stmt.where(Artifact.run_id == run_id)
    if tenant_id is not None:
        stmt = stmt.where(Artifact.tenant_id == tenant_id)
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError:
            cursor_dt = None
        if cursor_dt is not None:
            stmt = stmt.where(Artifact.created_at < cursor_dt)

    stmt = stmt.order_by(Artifact.created_at.desc()).limit(limit + 1)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].created_at.isoformat()

    return {"data": rows, "next_cursor": next_cursor}


# ---------------------------------------------------------------------------
# delete_artifact
# ---------------------------------------------------------------------------


async def delete_artifact(
    session: AsyncSession,
    artifact_id: UUID,
    *,
    tenant_id: UUID | None = None,
    store: LocalArtifactStore | None = None,
) -> bool:
    """Tenant-scoped delete. Returns True on hit, False on miss/cross-tenant.

    Caller commits.
    """
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        return False
    if tenant_id is not None:
        if artifact.tenant_id is None or artifact.tenant_id != tenant_id:
            return False

    backend = store or get_default_store()
    try:
        await backend.delete(artifact.storage_uri)
    except OSError as exc:
        logger.warning(
            "artifact_service.delete_artifact: storage delete failed",
            extra={
                "artifact_id": str(artifact_id),
                "storage_uri": artifact.storage_uri,
                "error": str(exc),
            },
        )

    await session.delete(artifact)
    await session.flush()
    return True


__all__ = [
    "DEFAULT_INLINE_THRESHOLD_BYTES",
    "DEFAULT_RETENTION_DAYS",
    "delete_artifact",
    "expire_old_artifacts",
    "get_artifact",
    "get_default_store",
    "list_artifacts",
    "maybe_persist_output_as_artifact",
    "set_default_store",
    "store_artifact",
]
