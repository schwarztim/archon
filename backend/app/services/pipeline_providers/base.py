"""Base protocol for pipeline provider adapters (W9a).

All provider adapters must satisfy this protocol. The protocol is structural
(``runtime_checkable``) so duck-typed test doubles work without subclassing.

Canonical status vocabulary (returned by ``normalize_status``):
  "running"    — pipeline is executing
  "completed"  — pipeline finished successfully
  "failed"     — pipeline finished with a failure
  "cancelled"  — pipeline was cancelled
  "unknown"    — status cannot be mapped (treat as still-running for polling)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PipelineProvider(Protocol):
    """Structural protocol for outbound pipeline provider adapters.

    All methods are coroutines. Adapters MUST be stateless: every piece of
    state (credentials, run IDs, URLs) is passed per-call so that adapters
    can be used as singletons without locking.
    """

    async def start_pipeline(
        self,
        *,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Trigger an external pipeline run.

        ``config`` contains provider-specific trigger parameters (repo, ref,
        workflow_id, inputs, …). ``credentials`` contains resolved secret
        values (token, org, project, …).

        Returns a dict that MUST include:
          ``external_run_id``   — provider's run / build identifier (str)
          ``external_run_url``  — human-readable URL (str or None)
          Any additional provider-specific fields are passed through.
        """
        ...

    async def get_pipeline_status(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Poll the external pipeline for its current status.

        Returns a dict that MUST include:
          ``status``       — one of the canonical status strings
          ``raw_status``   — original provider string (for audit)
          ``conclusion``   — provider-specific conclusion (may be None)
          ``error``        — dict or None (non-None when status == "failed")
        """
        ...

    async def cancel_pipeline(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> bool:
        """Request cancellation of an external pipeline run.

        Returns True if the cancellation request was accepted, False otherwise.
        Adapters should not raise on cancellation failures — return False and
        let the caller decide whether to retry.
        """
        ...

    def normalize_status(self, raw_status: str) -> str:
        """Map a provider-specific status string to a canonical status.

        Must return one of: "running", "completed", "failed", "cancelled",
        "unknown". Unknown raw values MUST map to "unknown".
        """
        ...

    def normalize_error(self, raw_error: dict[str, Any]) -> dict[str, Any]:
        """Extract a canonical error structure from a provider error blob.

        Returns a dict with at least:
          ``message``  — human-readable error description
          ``code``     — provider-specific error code (str or None)
          ``details``  — full raw error for debugging (dict)
        """
        ...


__all__ = ["PipelineProvider"]
