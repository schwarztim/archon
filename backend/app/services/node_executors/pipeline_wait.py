"""Pipeline wait node executor (W9b).

Polls the external pipeline provider until the run reaches a terminal state,
emitting heartbeat progress on each poll cycle. Supports cooperative
cancellation via ``context.check_cancelled``.

node_config keys:
  ``provider``            — provider name (github_actions, azure_devops, generic_webhook)
  ``external_run_id``     — the run ID returned by execute_pipeline_start
  ``credential_refs``     — dict mapping credential key -> vault secret ref
  ``pipeline_config``     — provider-specific config (owner/repo/org/project/…)
  ``poll_interval_seconds`` — seconds between polls (default: 15)
  ``max_polls``           — maximum number of polls before giving up (default: 120 = 30m)

output_data:
  ``external_run_id``  — the run ID that was polled
  ``status``           — canonical terminal status (completed/failed/cancelled)
  ``conclusion``       — provider-specific conclusion string
  ``run_url``          — human-readable URL (may be None)
  ``error``            — error dict if status == "failed" (may be None)
  ``polls``            — number of polls performed
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 15  # seconds
_DEFAULT_MAX_POLLS = 120     # 120 × 15s = 30 minutes


async def execute_pipeline_wait(context: Any) -> Any:
    """W9b: poll external pipeline until terminal, heartbeat progress each cycle."""
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415
    from app.services.pipeline_providers import get_provider  # noqa: PLC0415

    config: dict[str, Any] = context.node_config or {}
    provider_name: str = config.get("provider", "")
    if not provider_name:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_wait: node_config.provider is required",
            non_retryable=True,
        )

    external_run_id: str = config.get("external_run_id", "")
    if not external_run_id:
        # Also check input_data (may have been passed from pipeline_start output).
        external_run_id = (context.input_data or {}).get("external_run_id", "")
    if not external_run_id:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_wait: external_run_id is required",
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
                error_message=f"pipeline_wait: failed to resolve credential {key!r}: {exc}",
                non_retryable=True,
            )

    pipeline_config: dict[str, Any] = config.get("pipeline_config") or {}
    poll_interval: int = int(config.get("poll_interval_seconds") or _DEFAULT_POLL_INTERVAL)
    max_polls: int = int(config.get("max_polls") or _DEFAULT_MAX_POLLS)

    _TERMINAL = {"completed", "failed", "cancelled"}
    polls = 0

    while polls < max_polls:
        # Cooperative cancellation check.
        await context.check_cancelled()

        # Poll provider.
        try:
            status_result = await provider.get_pipeline_status(
                external_run_id=external_run_id,
                credentials=credentials,
                config=pipeline_config,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "pipeline_wait: get_pipeline_status error (poll=%d): %s", polls, exc
            )
            # Transient polling error — continue; don't consume a poll slot.
            await asyncio.sleep(poll_interval)
            continue

        polls += 1
        current_status: str = status_result.get("status", "unknown")

        await context.heartbeat(
            {
                "polls": polls,
                "current_status": current_status,
                "external_run_id": external_run_id,
                "provider": provider_name,
                "raw_status": status_result.get("raw_status"),
            }
        )

        log.debug(
            "pipeline_wait: poll=%d status=%s run_id=%s",
            polls,
            current_status,
            external_run_id,
        )

        if current_status in _TERMINAL:
            # Map "completed" to activity success, others to failure.
            activity_status = (
                "completed" if current_status == "completed" else "failed"
            )
            error = status_result.get("error") if current_status == "failed" else None

            return ActivityResult(
                status=activity_status,
                output_data={
                    "external_run_id": external_run_id,
                    "status": current_status,
                    "conclusion": status_result.get("conclusion"),
                    "run_url": status_result.get("run_url"),
                    "error": error,
                    "polls": polls,
                },
                error_code=(
                    (error or {}).get("code") if activity_status == "failed" else None
                ),
                error_message=(
                    (error or {}).get("message") if activity_status == "failed" else None
                ),
            )

        # Wait before next poll.
        await asyncio.sleep(poll_interval)

    # Max polls exceeded — treat as a timeout failure.
    return ActivityResult(
        status="failed",
        error_code="PipelineWaitTimeout",
        error_message=(
            f"pipeline_wait: max_polls ({max_polls}) exceeded for run {external_run_id}"
        ),
        output_data={
            "external_run_id": external_run_id,
            "status": "unknown",
            "polls": polls,
        },
    )


__all__ = ["execute_pipeline_wait"]
