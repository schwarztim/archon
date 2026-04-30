"""Pipeline cancel node executor (W9b).

Calls provider.cancel_pipeline for the configured run. Returns ``completed``
whether or not the provider accepted the request (the boolean result is
surfaced in output_data so callers can log appropriately).

node_config keys:
  ``provider``            — provider name
  ``external_run_id``     — run to cancel
  ``credential_refs``     — dict mapping credential key -> vault secret ref
  ``pipeline_config``     — provider-specific config (owner/repo/org/project/…)

output_data:
  ``external_run_id``  — run that was targeted
  ``accepted``         — True if provider accepted the cancellation request
  ``provider``         — the provider name used
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


async def execute_pipeline_cancel(context: Any) -> Any:
    """W9b: request cancellation of an external pipeline run."""
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415
    from app.services.pipeline_providers import get_provider  # noqa: PLC0415

    config: dict[str, Any] = context.node_config or {}
    provider_name: str = config.get("provider", "")
    if not provider_name:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_cancel: node_config.provider is required",
            non_retryable=True,
        )

    external_run_id: str = config.get("external_run_id", "")
    if not external_run_id:
        external_run_id = (context.input_data or {}).get("external_run_id", "")
    if not external_run_id:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_cancel: external_run_id is required",
            non_retryable=True,
        )

    try:
        provider = get_provider(provider_name)
    except ValueError as exc:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message=str(exc),
            non_retryable=True,
        )

    # Resolve credentials.
    credential_refs: dict[str, str] = config.get("credential_refs") or {}
    credentials: dict[str, Any] = {}
    for key, ref in credential_refs.items():
        try:
            credentials[key] = await context.resolve_secret(ref)
        except Exception as exc:  # noqa: BLE001
            return ActivityResult(
                status="failed",
                error_code="SecretResolutionError",
                error_message=f"pipeline_cancel: failed to resolve credential {key!r}: {exc}",
                non_retryable=True,
            )

    pipeline_config: dict[str, Any] = config.get("pipeline_config") or {}

    log.info(
        "pipeline_cancel: requesting cancellation of run=%s via provider=%s",
        external_run_id,
        provider_name,
    )

    accepted = await provider.cancel_pipeline(
        external_run_id=external_run_id,
        credentials=credentials,
        config=pipeline_config,
    )

    await context.heartbeat(
        {
            "provider": provider_name,
            "external_run_id": external_run_id,
            "cancel_accepted": accepted,
        }
    )

    return ActivityResult(
        status="completed",
        output_data={
            "external_run_id": external_run_id,
            "accepted": accepted,
            "provider": provider_name,
        },
    )


__all__ = ["execute_pipeline_cancel"]
