"""Pipeline ingress service (W8).

Handles webhook signature verification, idempotent event ingestion, and
linking external CI/CD pipeline events to WorkflowRun rows via
PipelineCorrelation.

Design principles:
  - Provider-neutral core: all providers share the same ingestion path.
    Providers differ only in signature verification and event-field extraction.
  - Idempotency: (provider, external_event_id) is the dedupe key at the
    schema layer. The service returns the existing PipelineCorrelation on
    duplicate delivery without creating a second WorkflowRun.
  - Signature-first: verification runs before any DB access. A 401 on
    bad signature costs nothing.
  - WorkflowRun creation is delegated entirely to ExecutionFacade.create_run
    with triggered_by="pipeline". The WorkflowRun model is not modified.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pipeline import PipelineCorrelation
from app.services.execution_facade import ExecutionFacade

log = logging.getLogger(__name__)

# ── Provider-specific signature verification ─────────────────────────────────


def _verify_github_signature(
    payload_bytes: bytes, signature_header: str, secret: str
) -> bool:
    """Verify GitHub's X-Hub-Signature-256 HMAC-SHA256 header.

    GitHub sends: ``sha256=<hex-digest>``
    """
    if not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header[len("sha256="):]
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), expected_hex)


def _verify_gitlab_signature(
    payload_bytes: bytes, signature_header: str, secret: str
) -> bool:
    """Verify GitLab's X-Gitlab-Token header (plaintext comparison)."""
    # GitLab sends the token value directly; no HMAC.
    return hmac.compare_digest(signature_header, secret)


def _verify_azure_devops_signature(
    payload_bytes: bytes, signature_header: str, secret: str
) -> bool:
    """Verify Azure DevOps HMAC-SHA1 shared-secret header.

    Azure DevOps sends: ``sha1=<hex-digest>``
    """
    if not signature_header.startswith("sha1="):
        return False
    expected_hex = signature_header[len("sha1="):]
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha1)  # noqa: S324
    return hmac.compare_digest(mac.hexdigest(), expected_hex)


def _verify_jenkins_signature(
    payload_bytes: bytes, signature_header: str, secret: str
) -> bool:
    """Verify Jenkins Generic Webhook Trigger HMAC-SHA256 header."""
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature_header)


def _verify_generic_hmac(
    payload_bytes: bytes, signature_header: str, secret: str
) -> bool:
    """Generic HMAC-SHA256: compare hex digest directly."""
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature_header)


_VERIFIERS = {
    "github_actions": _verify_github_signature,
    "gitlab": _verify_gitlab_signature,
    "azure_devops": _verify_azure_devops_signature,
    "jenkins": _verify_jenkins_signature,
    "generic_webhook": _verify_generic_hmac,
}


def _verify_signature(
    provider: str, payload_bytes: bytes, signature: str, secret: str
) -> bool:
    """Route to the provider-specific verifier. Returns False on unknown provider."""
    verifier = _VERIFIERS.get(provider)
    if verifier is None:
        log.warning("pipeline_service: unknown provider %r; rejecting", provider)
        return False
    return verifier(payload_bytes, signature, secret)


# ── Event field extraction ────────────────────────────────────────────────────


def _extract_github_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a GitHub Actions webhook payload."""
    return {
        "external_event_id": str(
            payload.get("delivery", payload.get("check_suite", {}).get("id", ""))
        ),
        "external_run_id": str(
            payload.get("workflow_run", {}).get("id", "")
        ) or None,
        "external_pipeline_id": payload.get("workflow", {}).get("id")
            and str(payload["workflow"]["id"]) or None,
        "external_commit_sha": payload.get("workflow_run", {}).get("head_sha"),
        "external_branch": payload.get("workflow_run", {}).get("head_branch"),
        "external_actor": payload.get("sender", {}).get("login"),
        "environment": payload.get("deployment", {}).get("environment"),
    }


def _extract_azure_devops_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from an Azure DevOps service-hook payload."""
    resource = payload.get("resource", {})
    return {
        "external_event_id": str(payload.get("id", "")),
        "external_run_id": str(resource.get("id", "")) or None,
        "external_pipeline_id": str(
            resource.get("definition", {}).get("id", "")
        ) or None,
        "external_commit_sha": resource.get("sourceVersion"),
        "external_branch": resource.get("sourceBranch"),
        "external_actor": resource.get("requestedBy", {}).get("displayName"),
        "environment": resource.get("parameters", {}).get("environment"),
    }


def _extract_gitlab_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a GitLab webhook payload."""
    return {
        "external_event_id": str(payload.get("pipeline_id", payload.get("object_attributes", {}).get("id", ""))),
        "external_run_id": str(payload.get("pipeline_id", "")) or None,
        "external_pipeline_id": str(payload.get("project", {}).get("id", "")) or None,
        "external_commit_sha": payload.get("commit", {}).get("id")
            or payload.get("object_attributes", {}).get("sha"),
        "external_branch": payload.get("object_attributes", {}).get("ref"),
        "external_actor": payload.get("user", {}).get("username"),
        "environment": payload.get("object_attributes", {}).get("environment"),
    }


def _extract_jenkins_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a Jenkins Generic Webhook payload."""
    return {
        "external_event_id": str(payload.get("build", {}).get("full_url", ""))
            or str(payload.get("build", {}).get("number", "")),
        "external_run_id": str(payload.get("build", {}).get("number", "")) or None,
        "external_pipeline_id": payload.get("name"),
        "external_commit_sha": payload.get("build", {}).get("scm", {}).get("commit"),
        "external_branch": payload.get("build", {}).get("scm", {}).get("branch"),
        "external_actor": payload.get("build", {}).get("cause", {}).get("userId"),
        "environment": payload.get("build", {}).get("parameters", {}).get("environment"),
    }


def _extract_generic_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a generic webhook payload.

    Callers are expected to put fields under top-level keys that match
    the canonical names, or nest them under an 'event' key.
    """
    event = payload.get("event", payload)
    return {
        "external_event_id": str(event.get("event_id", event.get("id", ""))),
        "external_run_id": str(event.get("run_id", "")) or None,
        "external_pipeline_id": str(event.get("pipeline_id", "")) or None,
        "external_commit_sha": event.get("commit_sha"),
        "external_branch": event.get("branch"),
        "external_actor": event.get("actor"),
        "environment": event.get("environment"),
    }


_EXTRACTORS = {
    "github_actions": _extract_github_fields,
    "azure_devops": _extract_azure_devops_fields,
    "gitlab": _extract_gitlab_fields,
    "jenkins": _extract_jenkins_fields,
    "generic_webhook": _extract_generic_fields,
}


def _compute_idempotency_key(provider: str, external_event_id: str) -> str:
    """Compute idempotency_key as sha256(provider + external_event_id)."""
    raw = f"{provider}:{external_event_id}".encode()
    return hashlib.sha256(raw).hexdigest()


# ── Public service functions ──────────────────────────────────────────────────


async def ingest_pipeline_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workflow_id: UUID,
    provider: str,
    event_payload: dict[str, Any],
    signature: str,
    secret: str,
    payload_bytes: bytes,
    callback_url: str | None = None,
    callback_url_secret_ref: str | None = None,
) -> tuple[PipelineCorrelation, bool]:
    """Ingest a signed pipeline webhook event.

    Signature verification MUST pass before this function is called from
    the route layer. The route passes ``payload_bytes`` (the raw request
    body) and the decoded ``event_payload`` dict separately so verification
    uses the exact wire bytes.

    Returns:
        (correlation, is_new) — is_new=False on idempotent duplicate delivery.

    Raises:
        ValueError — invalid provider or missing external_event_id.
        PermissionError — signature verification failed.
    """
    if provider not in _VERIFIERS:
        raise ValueError(
            f"Unknown provider {provider!r}. "
            f"Valid providers: {list(_VERIFIERS)}"
        )

    # Verify signature before any DB work.
    if not _verify_signature(provider, payload_bytes, signature, secret):
        raise PermissionError("Webhook signature verification failed")

    # Extract provider-specific event fields.
    extractor = _EXTRACTORS[provider]
    fields = extractor(event_payload)

    external_event_id = fields.get("external_event_id", "")
    if not external_event_id:
        raise ValueError(
            f"Could not extract external_event_id from {provider!r} payload"
        )

    idempotency_key = _compute_idempotency_key(provider, external_event_id)

    # Check for existing correlation (idempotency).
    existing = await get_correlation_by_external(
        session, provider=provider, external_event_id=external_event_id
    )
    if existing is not None:
        log.info(
            "pipeline_service: duplicate event provider=%s event_id=%s — returning existing correlation %s",
            provider,
            external_event_id,
            existing.id,
        )
        return existing, False

    # Create the WorkflowRun through ExecutionFacade (no modifications to it).
    run, _ = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        input_data={
            "provider": provider,
            "external_event_id": external_event_id,
            "event_payload": event_payload,
        },
        triggered_by="pipeline",
        trigger_type="webhook",
        idempotency_key=idempotency_key,
    )

    # Create the PipelineCorrelation row linking run to the external event.
    correlation = PipelineCorrelation(
        tenant_id=tenant_id,
        workflow_run_id=run.id,
        provider=provider,
        external_event_id=external_event_id,
        external_run_id=fields.get("external_run_id"),
        external_pipeline_id=fields.get("external_pipeline_id"),
        external_commit_sha=fields.get("external_commit_sha"),
        external_branch=fields.get("external_branch"),
        external_actor=fields.get("external_actor"),
        environment=fields.get("environment"),
        callback_url=callback_url,
        callback_url_secret_ref=callback_url_secret_ref,
        idempotency_key=idempotency_key,
    )
    session.add(correlation)
    await session.commit()
    await session.refresh(correlation)

    log.info(
        "pipeline_service: ingested event provider=%s event_id=%s "
        "correlation_id=%s run_id=%s",
        provider,
        external_event_id,
        correlation.id,
        run.id,
    )
    try:
        from app.services.metrics_service import record_pipeline_ingress  # noqa: PLC0415
        record_pipeline_ingress(provider=provider)
    except Exception as exc:  # noqa: BLE001
        log.debug("pipeline metrics emit failed: %s", exc)
    return correlation, True


async def get_correlation_by_run(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> PipelineCorrelation | None:
    """Return the PipelineCorrelation for a given WorkflowRun ID, or None."""
    stmt = (
        select(PipelineCorrelation)
        .where(PipelineCorrelation.workflow_run_id == run_id)
        .limit(1)
    )
    result = await session.exec(stmt)
    return result.first()


async def get_correlation_by_external(
    session: AsyncSession,
    *,
    provider: str,
    external_event_id: str,
) -> PipelineCorrelation | None:
    """Return the PipelineCorrelation for (provider, external_event_id), or None."""
    stmt = (
        select(PipelineCorrelation)
        .where(PipelineCorrelation.provider == provider)
        .where(PipelineCorrelation.external_event_id == external_event_id)
        .limit(1)
    )
    result = await session.exec(stmt)
    return result.first()


async def update_callback_status(
    session: AsyncSession,
    *,
    correlation_id: UUID,
    status: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record a callback status update for an external pipeline.

    This is a stub for sending status back to the provider (e.g. updating
    a GitHub commit status or Azure DevOps build status). The implementation
    updates the correlation's updated_at timestamp and logs the transition;
    the actual HTTP callback is left to a dedicated callback service.
    """
    from datetime import timezone as _tz  # noqa: PLC0415
    from datetime import datetime as _dt  # noqa: PLC0415

    corr = await session.get(PipelineCorrelation, correlation_id)
    if corr is None:
        log.warning(
            "pipeline_service: update_callback_status called for unknown correlation %s",
            correlation_id,
        )
        return

    corr.updated_at = _dt.now(_tz.utc).replace(tzinfo=None)
    session.add(corr)
    await session.commit()

    log.info(
        "pipeline_service: callback status update correlation=%s status=%s details=%s",
        correlation_id,
        status,
        details,
    )


__all__ = [
    "ingest_pipeline_event",
    "get_correlation_by_run",
    "get_correlation_by_external",
    "update_callback_status",
    "_verify_signature",
]
