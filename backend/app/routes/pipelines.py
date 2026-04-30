"""Pipeline ingress endpoints (W8).

Provides signed webhook ingestion from external CI/CD providers and
correlation query endpoints.

Endpoints:
  POST /api/v1/pipelines/webhook/{provider}
      Signed webhook ingress — GitHub Actions, Azure DevOps, Jenkins,
      GitLab, or generic HMAC-SHA256. Signature verification runs before
      any DB access. Returns 201 on new correlation, 200 on duplicate.

  GET /api/v1/pipelines/correlations/{run_id}
      Return the PipelineCorrelation for a WorkflowRun.

  GET /api/v1/pipelines/correlations
      List correlations with optional provider/tenant filters.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import Depends

from app.database import get_session
from app.models.pipeline import PipelineCorrelation, _VALID_PROVIDERS
from app.services.pipeline_service import (
    get_correlation_by_external,
    get_correlation_by_run,
    ingest_pipeline_event,
    update_callback_status,
)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
log = logging.getLogger(__name__)

# ── Request / Response shapes ─────────────────────────────────────────────────

_DEFAULT_WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")


class WebhookIngestRequest(BaseModel):
    """Body for the generic webhook ingress endpoint.

    ``workflow_id`` selects which workflow to start when the event arrives.
    ``secret_ref`` is the vault path used to retrieve the signing secret.
    ``secret`` is the raw secret (for tests / non-vault usage). In
    production exactly one of secret_ref or secret should be provided.
    """

    workflow_id: UUID = _DEFAULT_WORKFLOW_ID
    tenant_id: UUID = _DEFAULT_TENANT_ID
    secret: str = ""
    secret_ref: str | None = None
    callback_url: str | None = None
    callback_url_secret_ref: str | None = None


class CorrelationOut(BaseModel):
    """Response shape for PipelineCorrelation rows."""

    id: UUID
    tenant_id: UUID | None
    workflow_run_id: UUID
    provider: str
    external_event_id: str
    external_run_id: str | None
    external_pipeline_id: str | None
    external_commit_sha: str | None
    external_branch: str | None
    external_actor: str | None
    environment: str | None
    callback_url: str | None
    idempotency_key: str

    class Config:
        from_attributes = True


def _corr_to_dict(c: PipelineCorrelation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "tenant_id": str(c.tenant_id) if c.tenant_id else None,
        "workflow_run_id": str(c.workflow_run_id),
        "provider": c.provider,
        "external_event_id": c.external_event_id,
        "external_run_id": c.external_run_id,
        "external_pipeline_id": c.external_pipeline_id,
        "external_commit_sha": c.external_commit_sha,
        "external_branch": c.external_branch,
        "external_actor": c.external_actor,
        "environment": c.environment,
        "callback_url": c.callback_url,
        "idempotency_key": c.idempotency_key,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


# ── Signature extraction helpers ──────────────────────────────────────────────


def _extract_signature(provider: str, request: Request) -> str:
    """Pull the provider-specific signature header from the request."""
    header_map = {
        "github_actions": "X-Hub-Signature-256",
        "gitlab": "X-Gitlab-Token",
        "azure_devops": "X-Hub-Signature",
        "jenkins": "X-Jenkins-Signature",
        "generic_webhook": "X-Signature",
    }
    header_name = header_map.get(provider, "X-Signature")
    sig = request.headers.get(header_name, "")
    if not sig:
        # Also accept a lowercased variant for robustness.
        sig = request.headers.get(header_name.lower(), "")
    return sig


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/webhook/{provider}",
    status_code=201,
    summary="Ingest a signed CI/CD pipeline webhook",
)
async def ingest_webhook(
    provider: str = Path(
        ...,
        description="CI/CD provider slug",
        pattern="^(github_actions|azure_devops|jenkins|gitlab|generic_webhook)$",
    ),
    request: Request = ...,  # type: ignore[assignment]
    body: WebhookIngestRequest = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Accept a signed webhook from an external CI/CD provider.

    Signature verification happens BEFORE any DB access. A bad signature
    returns 401 immediately. A duplicate event (idempotent redelivery)
    returns 200 with the existing correlation. A new event returns 201.
    """
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider {provider!r}. "
            f"Valid: {sorted(_VALID_PROVIDERS)}",
        )

    # Read raw bytes for signature verification.
    try:
        raw_bytes = await request.body()
    except Exception as exc:
        log.warning("pipelines: failed to read request body: %s", exc)
        raise HTTPException(status_code=400, detail="Could not read request body") from exc

    # Extract the provider-specific signature header.
    signature = _extract_signature(provider, request)
    if not signature:
        raise HTTPException(
            status_code=401,
            detail=f"Missing signature header for provider {provider!r}",
        )

    # Resolve secret.
    secret = body.secret
    if not secret and body.secret_ref:
        # In production resolve from vault; stub resolution for now.
        secret = body.secret_ref

    if not secret:
        raise HTTPException(
            status_code=422,
            detail="Either 'secret' or 'secret_ref' must be provided",
        )

    # Parse event_payload from the raw body (it was already deserialized by
    # FastAPI into body; we need the dict for field extraction).
    import json as _json  # noqa: PLC0415

    try:
        event_payload: dict[str, Any] = _json.loads(raw_bytes) if raw_bytes else {}
    except Exception:  # noqa: BLE001
        event_payload = {}

    try:
        correlation, is_new = await ingest_pipeline_event(
            session,
            tenant_id=body.tenant_id,
            workflow_id=body.workflow_id,
            provider=provider,
            event_payload=event_payload,
            signature=signature,
            secret=secret,
            payload_bytes=raw_bytes,
            callback_url=body.callback_url,
            callback_url_secret_ref=body.callback_url_secret_ref,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("pipelines: unexpected error during ingest: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    status_code = 201 if is_new else 200
    return {
        "status_code": status_code,
        "is_new": is_new,
        "correlation": _corr_to_dict(correlation),
    }


@router.get(
    "/correlations/{run_id}",
    summary="Get pipeline correlation for a workflow run",
)
async def get_correlation_for_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the PipelineCorrelation linked to a specific WorkflowRun."""
    correlation = await get_correlation_by_run(session, run_id=run_id)
    if correlation is None:
        raise HTTPException(
            status_code=404,
            detail=f"No pipeline correlation found for run {run_id}",
        )
    return _corr_to_dict(correlation)


@router.get(
    "/correlations",
    summary="List pipeline correlations",
)
async def list_correlations(
    provider: str | None = Query(default=None, description="Filter by provider slug"),
    tenant_id: UUID | None = Query(default=None, description="Filter by tenant"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List PipelineCorrelation rows with optional provider/tenant filtering."""
    stmt = select(PipelineCorrelation)
    if provider is not None:
        stmt = stmt.where(PipelineCorrelation.provider == provider)
    if tenant_id is not None:
        stmt = stmt.where(PipelineCorrelation.tenant_id == tenant_id)
    stmt = stmt.order_by(PipelineCorrelation.created_at.desc()).offset(offset).limit(limit)

    result = await session.exec(stmt)
    rows = result.all()
    return {
        "correlations": [_corr_to_dict(r) for r in rows],
        "count": len(rows),
        "offset": offset,
        "limit": limit,
    }


__all__ = ["router"]
