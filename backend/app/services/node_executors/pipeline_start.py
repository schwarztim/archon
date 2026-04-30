"""Pipeline start node executor (W9b).

Resolves the configured provider adapter, resolves credentials via the
ActivityContext secret resolver, calls provider.start_pipeline, creates a
PipelineCorrelation row, and returns the external_run_id in output_data.

node_config keys:
  ``provider``            — one of: github_actions, azure_devops, generic_webhook
  ``pipeline_config``     — dict of provider-specific trigger parameters
  ``credential_refs``     — dict mapping credential key -> vault secret ref
                            e.g. {"token": "vault://ci/github-pat"}
  ``correlation_id``      — optional Archon correlation ID to link to
  ``idempotent``          — if True, return existing correlation on duplicate
                            (default: True)

output_data:
  ``external_run_id``     — the provider's run identifier
  ``external_run_url``    — human-readable URL (may be None)
  ``correlation_id``      — the PipelineCorrelation.id (UUID str)
  ``provider``            — the provider name used
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import uuid4

log = logging.getLogger(__name__)


async def execute_pipeline_start(context: Any) -> Any:
    """W9b: trigger an external pipeline run, persist a PipelineCorrelation."""
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415
    from app.services.pipeline_providers import get_provider  # noqa: PLC0415

    config: dict[str, Any] = context.node_config or {}
    provider_name: str = config.get("provider", "")
    if not provider_name:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_start: node_config.provider is required",
            non_retryable=True,
        )

    # Resolve provider.
    try:
        provider = get_provider(provider_name)
    except ValueError as exc:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message=str(exc),
            non_retryable=True,
        )

    # Resolve credentials from vault references.
    credential_refs: dict[str, str] = config.get("credential_refs") or {}
    credentials: dict[str, Any] = {}
    for key, ref in credential_refs.items():
        try:
            credentials[key] = await context.resolve_secret(ref)
        except Exception as exc:  # noqa: BLE001
            return ActivityResult(
                status="failed",
                error_code="SecretResolutionError",
                error_message=f"pipeline_start: failed to resolve credential {key!r}: {exc}",
                non_retryable=True,
            )

    pipeline_config: dict[str, Any] = config.get("pipeline_config") or {}

    # Idempotency: compute key from (run_id, provider, pipeline_config).
    raw_idem = f"{context.run_id}:{provider_name}:{_stable_hash(pipeline_config)}"
    idempotency_key = hashlib.sha256(raw_idem.encode()).hexdigest()

    # Check for an existing correlation if idempotent mode is on (default True).
    idempotent: bool = config.get("idempotent", True)
    if idempotent and context.db_session is not None:
        existing = await _find_existing_correlation(
            context.db_session,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            log.info(
                "pipeline_start: returning existing correlation %s (idempotent)",
                existing.id,
            )
            return ActivityResult(
                status="completed",
                output_data={
                    "external_run_id": existing.external_run_id,
                    "external_run_url": None,
                    "correlation_id": str(existing.id),
                    "provider": provider_name,
                    "idempotent_hit": True,
                },
            )

    # Trigger the external pipeline.
    try:
        result = await provider.start_pipeline(
            config=pipeline_config,
            credentials=credentials,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("pipeline_start: provider.start_pipeline failed: %s", exc)
        return ActivityResult(
            status="failed",
            error_code="PipelineStartError",
            error_message=str(exc)[:1024],
        )

    external_run_id: str = result.get("external_run_id", "")
    external_run_url: str | None = result.get("external_run_url")

    # Create the PipelineCorrelation row.
    correlation_id_str: str | None = None
    if context.db_session is not None:
        try:
            correlation_id_str = await _create_correlation(
                session=context.db_session,
                tenant_id=context.tenant_id,
                run_id=context.run_id,
                provider=provider_name,
                external_run_id=external_run_id,
                idempotency_key=idempotency_key,
                extra=result,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "pipeline_start: failed to create PipelineCorrelation: %s", exc
            )
            # Non-fatal: activity output is still valid without the row.

    await context.heartbeat(
        {
            "provider": provider_name,
            "external_run_id": external_run_id,
            "correlation_id": correlation_id_str,
        }
    )

    return ActivityResult(
        status="completed",
        output_data={
            "external_run_id": external_run_id,
            "external_run_url": external_run_url,
            "correlation_id": correlation_id_str,
            "provider": provider_name,
            "idempotent_hit": False,
        },
    )


# ── DB helpers ────────────────────────────────────────────────────────────────


async def _find_existing_correlation(session: Any, *, idempotency_key: str) -> Any:
    """Return an existing PipelineCorrelation by idempotency_key, or None."""
    from app.models.pipeline import PipelineCorrelation  # noqa: PLC0415
    from sqlmodel import select  # noqa: PLC0415

    stmt = (
        select(PipelineCorrelation)
        .where(PipelineCorrelation.idempotency_key == idempotency_key)
        .limit(1)
    )
    result = await session.exec(stmt)
    return result.first()


async def _create_correlation(
    session: Any,
    *,
    tenant_id: str | None,
    run_id: str,
    provider: str,
    external_run_id: str,
    idempotency_key: str,
    extra: dict[str, Any],
) -> str:
    """INSERT a PipelineCorrelation row and return its id as a string."""
    from uuid import UUID  # noqa: PLC0415

    from app.models.pipeline import PipelineCorrelation  # noqa: PLC0415

    try:
        tenant_uuid = UUID(str(tenant_id)) if tenant_id else None
        run_uuid = UUID(str(run_id))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid UUID: {exc}") from exc

    # Use a synthetic external_event_id so the unique constraint is satisfied.
    external_event_id = f"archon:{run_id}:{external_run_id}"

    correlation = PipelineCorrelation(
        tenant_id=tenant_uuid,
        workflow_run_id=run_uuid,
        provider=provider if provider in (
            "github_actions", "azure_devops", "jenkins", "gitlab", "generic_webhook"
        ) else "generic_webhook",
        external_event_id=external_event_id,
        external_run_id=external_run_id,
        external_pipeline_id=str(extra.get("pipeline_id") or extra.get("workflow_id") or ""),
        external_branch=extra.get("branch") or extra.get("ref"),
        idempotency_key=idempotency_key,
    )
    session.add(correlation)
    await session.commit()
    await session.refresh(correlation)
    return str(correlation.id)


def _stable_hash(obj: dict[str, Any]) -> str:
    """Compute a stable deterministic hex digest of a dict."""
    import json  # noqa: PLC0415

    serialised = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


__all__ = ["execute_pipeline_start"]
