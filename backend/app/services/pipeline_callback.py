"""Pipeline status callback service (W9c).

Sends status updates to an external pipeline's callback URL after a
WorkflowRun completes (or reaches a notable milestone). This is the outbound
complement to the W8 ingest path: the external pipeline triggered us; we
report back.

Public API:
  send_status_callback(session, *, correlation_id, status, details) -> bool

Retry policy:
  - 3 attempts with exponential backoff: 0s, 5s, 25s delays.
  - After max retries the callback URL is considered dead-lettered and
    a ``pipeline.callback_failed`` event is emitted via event_service.
  - Every attempt (success or failure) is logged as an audit event.

Dead-letter semantics:
  Persistent failure does NOT raise. The function returns False and the
  caller may choose to re-queue or alert. The ``pipeline.callback_failed``
  event provides the observability hook for external alerting.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_DELAYS = (0, 5, 25)  # seconds before each attempt (index = attempt - 1)


async def send_status_callback(
    session: Any,
    *,
    correlation_id: UUID | str,
    status: str,
    details: dict[str, Any] | None = None,
) -> bool:
    """Send a status update to the callback URL recorded in PipelineCorrelation.

    Fetches the correlation row (by ``correlation_id``), reads its
    ``callback_url`` and optional ``callback_url_secret_ref``, then POSTs
    the status payload.

    Returns True if a 2xx response was received on any attempt.
    Returns False if all attempts failed (dead-letter event emitted).

    Args:
        session: AsyncSession for DB access.
        correlation_id: The PipelineCorrelation.id identifying the row.
        status: Canonical status string to report (e.g. "completed", "failed").
        details: Optional additional payload fields (merged into the POST body).
    """
    corr_uuid = _to_uuid(correlation_id)

    from app.models.pipeline import PipelineCorrelation  # noqa: PLC0415

    corr = await session.get(PipelineCorrelation, corr_uuid)
    if corr is None:
        log.warning(
            "pipeline_callback: correlation %s not found; skipping callback",
            correlation_id,
        )
        return False

    callback_url = corr.callback_url
    if not callback_url:
        log.debug(
            "pipeline_callback: correlation %s has no callback_url; skipping",
            correlation_id,
        )
        return True  # Not an error — callback was not configured.

    # Resolve the secret for signing/auth if a ref is stored.
    callback_secret: str | None = None
    if corr.callback_url_secret_ref:
        try:
            callback_secret = await _resolve_vault_secret(corr.callback_url_secret_ref)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "pipeline_callback: failed to resolve callback secret for %s: %s",
                correlation_id,
                exc,
            )

    payload = _build_payload(
        correlation_id=str(corr_uuid),
        provider=corr.provider,
        external_run_id=corr.external_run_id,
        status=status,
        details=details,
    )

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        delay = _BACKOFF_DELAYS[attempt - 1]
        if delay:
            await asyncio.sleep(delay)

        try:
            success, http_status, response_body = await _post_callback(
                url=callback_url,
                payload=payload,
                secret=callback_secret,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "pipeline_callback: attempt %d/%d raised: %s",
                attempt,
                _MAX_ATTEMPTS,
                exc,
            )
            success, http_status, response_body = False, 0, str(exc)

        await _audit_callback_attempt(
            session=session,
            correlation_id=str(corr_uuid),
            attempt=attempt,
            status=status,
            callback_url=callback_url,
            http_status=http_status,
            success=success,
            response_body=response_body,
        )

        if success:
            log.info(
                "pipeline_callback: delivered to %s (attempt %d, status=%s)",
                callback_url,
                attempt,
                http_status,
            )
            return True

        log.warning(
            "pipeline_callback: attempt %d/%d failed (http_status=%s)",
            attempt,
            _MAX_ATTEMPTS,
            http_status,
        )

    # All attempts exhausted — dead-letter.
    log.error(
        "pipeline_callback: max retries exceeded for correlation %s; dead-lettering",
        correlation_id,
    )
    await _emit_dead_letter_event(
        session=session,
        correlation_id=str(corr_uuid),
        callback_url=callback_url,
        status=status,
        details=details,
    )
    return False


# ── Internals ─────────────────────────────────────────────────────────────────


def _build_payload(
    *,
    correlation_id: str,
    provider: str,
    external_run_id: str | None,
    status: str,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the standardised callback POST body."""
    payload: dict[str, Any] = {
        "event": "pipeline.status_update",
        "correlation_id": correlation_id,
        "provider": provider,
        "external_run_id": external_run_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if details:
        payload["details"] = details
    return payload


async def _post_callback(
    *,
    url: str,
    payload: dict[str, Any],
    secret: str | None,
) -> tuple[bool, int, str]:
    """POST *payload* to *url*. Returns (success, http_status, response_body)."""
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        raise RuntimeError("httpx is required for pipeline_callback")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        # HMAC-SHA256 signature for verification by the receiver.
        import hashlib  # noqa: PLC0415
        import hmac as _hmac  # noqa: PLC0415

        body_bytes = json.dumps(payload, sort_keys=True).encode()
        mac = _hmac.new(secret.encode(), body_bytes, hashlib.sha256)
        headers["X-Archon-Signature-256"] = f"sha256={mac.hexdigest()}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=headers)

    try:
        body_text = resp.text
    except Exception:  # noqa: BLE001
        body_text = ""

    success = 200 <= resp.status_code < 300
    return success, resp.status_code, body_text[:512]


async def _audit_callback_attempt(
    *,
    session: Any,
    correlation_id: str,
    attempt: int,
    status: str,
    callback_url: str,
    http_status: int,
    success: bool,
    response_body: str,
) -> None:
    """Log a callback attempt as an audit event (best-effort)."""
    try:
        from app.services.event_service import emit_event  # noqa: PLC0415

        await emit_event(
            session,
            event_type="pipeline.callback_attempt",
            data={
                "correlation_id": correlation_id,
                "attempt": attempt,
                "status": status,
                "callback_url": callback_url,
                "http_status": http_status,
                "success": success,
                "response_body": response_body,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("pipeline_callback: audit event failed: %s", exc)


async def _emit_dead_letter_event(
    *,
    session: Any,
    correlation_id: str,
    callback_url: str,
    status: str,
    details: dict[str, Any] | None,
) -> None:
    """Emit a pipeline.callback_failed dead-letter event (best-effort)."""
    try:
        from app.services.event_service import emit_event  # noqa: PLC0415

        await emit_event(
            session,
            event_type="pipeline.callback_failed",
            data={
                "correlation_id": correlation_id,
                "callback_url": callback_url,
                "status": status,
                "details": details,
                "max_attempts": _MAX_ATTEMPTS,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("pipeline_callback: dead-letter event emit failed: %s", exc)


async def _resolve_vault_secret(secret_ref: str) -> str:
    """Resolve a vault secret reference to its plaintext value.

    Uses the workspace secrets.py service when available; falls back to the
    environment variable convention for test contexts.
    """
    import os  # noqa: PLC0415

    if secret_ref.startswith("env://"):
        env_key = secret_ref[len("env://"):]
        value = os.environ.get(env_key)
        if value is None:
            raise ValueError(f"Environment variable {env_key!r} is not set")
        return value

    # Attempt to use the vault service (may not be available in all contexts).
    try:
        from app.services.auth import resolve_secret_ref  # noqa: PLC0415

        return await resolve_secret_ref(secret_ref)
    except ImportError:
        pass

    raise ValueError(f"Cannot resolve secret ref {secret_ref!r}: vault unavailable")


def _to_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


__all__ = ["send_status_callback"]
