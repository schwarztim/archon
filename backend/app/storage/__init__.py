"""Storage backends for durable artifact persistence (Phase 5).

Owned by WS5 / Observability+Artifacts Squad. The package exposes a
backend-neutral interface for the artifact service layer:

    put(content) -> storage_uri
    get(storage_uri) -> bytes
    delete(storage_uri) -> bool
    list_by_run(run_id) -> list[storage_uri]

The default backend is :class:`LocalArtifactStore`, a filesystem-backed
implementation suitable for single-node deployments and tests. Production
deployments will register an S3 (or similar) backend via the same
interface; the artifact service consults ``Artifact.storage_backend`` to
route reads back to the correct store.
"""

from __future__ import annotations

from app.storage.local_artifact_store import LocalArtifactStore

__all__ = ["LocalArtifactStore"]
