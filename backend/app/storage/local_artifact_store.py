"""Filesystem-backed artifact store.

Owned by WS5 / Observability+Artifacts Squad. Single-node deployments
and the test suite use this backend; production swap-in is a strict
interface match (``put`` / ``get`` / ``delete`` / ``list_by_run``).

Layout:

    {base_dir}/{tenant_id}/{run_id}/{artifact_id}

* ``tenant_id`` is ``"_global"`` when the artifact has no tenant.
* ``run_id`` is ``"_unbound"`` when the artifact is not attached to a run.
* The leaf is the artifact's UUID — no extension; the ``content_type``
  on the ``Artifact`` row is the source of truth for MIME.

Concurrency: writes go via ``tempfile + os.replace`` so a torn write
cannot corrupt an existing object. ``put`` and ``delete`` are idempotent
within a single artifact_id (overwrites are atomic).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = "/tmp/archon/artifacts"


class LocalArtifactStore:
    """Filesystem-backed artifact store.

    Args:
        base_dir: Root directory for all artifact bytes. Created on first
            write if missing. Defaults to ``/tmp/archon/artifacts``.
    """

    def __init__(self, base_dir: Path | str = DEFAULT_BASE_DIR) -> None:
        self.base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _resolve_dir(
        self,
        *,
        tenant_id: UUID | None,
        run_id: UUID | None,
    ) -> Path:
        """Resolve the directory that holds a given (tenant, run) pair."""
        tenant_part = str(tenant_id) if tenant_id else "_global"
        run_part = str(run_id) if run_id else "_unbound"
        return self.base_dir / tenant_part / run_part

    def _resolve_path(
        self,
        *,
        tenant_id: UUID | None,
        run_id: UUID | None,
        artifact_id: UUID,
    ) -> Path:
        """Resolve the absolute filesystem path for an artifact id."""
        return self._resolve_dir(tenant_id=tenant_id, run_id=run_id) / str(
            artifact_id
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def put(
        self,
        *,
        tenant_id: UUID | None,
        run_id: UUID | None,
        artifact_id: UUID,
        content: bytes,
    ) -> str:
        """Persist ``content`` for ``artifact_id``; return ``storage_uri``.

        Atomic on POSIX — writes to a tempfile within the target directory,
        then renames over the destination. The tempfile path is bound to
        the same directory so ``os.replace`` is a single inode rename
        (atomic guarantee).
        """
        target = self._resolve_path(
            tenant_id=tenant_id,
            run_id=run_id,
            artifact_id=artifact_id,
        )
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write to a tempfile in the same dir, then atomically rename.
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{artifact_id}-",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # Some filesystems (e.g. tmpfs on certain kernels) reject
                    # fsync — durability falls back to OS buffer guarantees.
                    pass
            os.replace(tmp_path, target)
        except Exception:
            # Best-effort cleanup of the tempfile if rename never happened.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.debug(
            "local_artifact_store.put",
            extra={
                "artifact_id": str(artifact_id),
                "size_bytes": len(content),
                "storage_uri": str(target),
            },
        )
        return str(target)

    async def get(self, storage_uri: str) -> bytes:
        """Return the bytes stored at ``storage_uri``.

        Raises ``FileNotFoundError`` when the object is missing.
        """
        path = Path(storage_uri)
        with path.open("rb") as fh:
            return fh.read()

    async def delete(self, storage_uri: str) -> bool:
        """Delete the file at ``storage_uri``.

        Returns ``True`` when a file was removed, ``False`` when the path
        was already absent. Errors are propagated — the caller decides
        whether to re-raise (cleanup loops typically swallow errors so
        a single corrupt entry can't block the sweep).
        """
        path = Path(storage_uri)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    async def list_by_run(self, run_id: UUID) -> list[str]:
        """Return all storage URIs whose path lives under ``run_id``.

        Walks the layout ``{base}/*/run_id/*`` so artifacts created with
        different tenants for the same run are all surfaced. Used by
        cleanup loops that need to enumerate per-run artifacts without
        a database round-trip.
        """
        results: list[str] = []
        if not self.base_dir.exists():
            return results
        for tenant_dir in self.base_dir.iterdir():
            run_dir = tenant_dir / str(run_id)
            if run_dir.is_dir():
                for entry in run_dir.iterdir():
                    if entry.is_file():
                        results.append(str(entry))
        return results


__all__ = ["LocalArtifactStore", "DEFAULT_BASE_DIR"]
