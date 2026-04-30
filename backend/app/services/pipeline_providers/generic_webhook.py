"""Generic webhook pipeline provider adapter (W9a).

Triggers a remote pipeline by POSTing a configurable JSON body to a webhook
URL, then polls a separate callback/status URL until a terminal state is
reached.

This adapter is intentionally minimal: it assumes the remote system accepts
a POST to ``trigger_url`` and exposes a ``status_url`` that returns a JSON
object with a ``status`` field. Both URLs and the status-field mapping are
fully configurable so the adapter can drive any HTTP-based pipeline system.

Required credentials keys (all optional — may also come from config):
  ``token``  — bearer token for Authorization header (omitted if absent)

Required config keys (start_pipeline):
  ``trigger_url``     — URL to POST to
  ``trigger_body``    — dict to send as JSON body (default: {})
  ``trigger_headers`` — extra headers to include (default: {})

Required config keys (get_pipeline_status):
  ``status_url``          — URL to GET for status
  ``status_field``        — dot-separated path to the status value (default: "status")
  ``running_values``      — list of status values meaning "still running"
  ``completed_values``    — list of status values meaning "completed"
  ``failed_values``       — list of status values meaning "failed"
  ``cancelled_values``    — list of status values meaning "cancelled"

Required config keys (cancel_pipeline):
  ``cancel_url``      — URL to POST/DELETE to cancel (default: None; returns False)
  ``cancel_method``   — HTTP method for cancel (default: "POST")
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class GenericWebhookProvider:
    """Provider adapter for a generic HTTP webhook-based pipeline system."""

    # ── Protocol implementation ───────────────────────────────────────────────

    async def start_pipeline(
        self,
        *,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """POST to ``config["trigger_url"]`` to start the external pipeline."""
        trigger_url = config["trigger_url"]
        body = config.get("trigger_body") or {}
        extra_headers: dict[str, str] = config.get("trigger_headers") or {}
        headers = {**_maybe_auth_header(credentials), **extra_headers}

        log.info("generic_webhook.start_pipeline url=%s", trigger_url)

        resp = await self._http_post(trigger_url, headers=headers, json=body)
        if resp.get("status_code", 0) not in (200, 201, 202, 204):
            raise RuntimeError(
                f"Generic webhook trigger returned {resp.get('status_code')}: "
                f"{resp.get('body')}"
            )

        resp_body = resp.get("body") or {}
        # The remote system may return a run ID in a configurable field.
        id_field = config.get("run_id_field", "id")
        run_id = (
            str(_extract_field(resp_body, id_field))
            if id_field and isinstance(resp_body, dict)
            else "webhook_triggered"
        )

        return {
            "external_run_id": run_id,
            "external_run_url": None,
            "trigger_url": trigger_url,
            "status_url": config.get("status_url"),
        }

    async def get_pipeline_status(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET ``config["status_url"]`` and map the response to canonical status."""
        cfg = config or {}
        status_url = cfg.get("status_url")
        if not status_url:
            # No status URL configured — caller must handle polling externally.
            return {
                "status": "running",
                "raw_status": "unknown",
                "conclusion": None,
                "error": None,
            }

        # Optionally substitute the run_id into the URL template.
        status_url = status_url.replace("{run_id}", external_run_id)
        headers = _maybe_auth_header(credentials)

        resp = await self._http_get(status_url, headers=headers)
        resp_body = resp.get("body") or {}

        status_field = cfg.get("status_field", "status")
        raw_status = str(_extract_field(resp_body, status_field) or "unknown")
        canonical = self.normalize_status(raw_status, config=cfg)

        error: dict[str, Any] | None = None
        if canonical == "failed":
            error = self.normalize_error({"status": raw_status, "body": resp_body})

        return {
            "status": canonical,
            "raw_status": raw_status,
            "conclusion": raw_status,
            "error": error,
        }

    async def cancel_pipeline(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> bool:
        """POST/DELETE to ``config["cancel_url"]`` if configured."""
        cfg = config or {}
        cancel_url = cfg.get("cancel_url")
        if not cancel_url:
            log.debug("generic_webhook.cancel_pipeline: no cancel_url configured")
            return False

        cancel_url = cancel_url.replace("{run_id}", external_run_id)
        method = (cfg.get("cancel_method") or "POST").upper()
        headers = _maybe_auth_header(credentials)

        try:
            if method == "DELETE":
                resp = await self._http_delete(cancel_url, headers=headers)
            else:
                resp = await self._http_post(cancel_url, headers=headers, json={})
            return resp.get("status_code", 0) in (200, 202, 204)
        except Exception as exc:  # noqa: BLE001
            log.warning("generic_webhook.cancel_pipeline failed: %s", exc)
            return False

    def normalize_status(
        self,
        raw_status: str,
        *,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Map raw status string to canonical status using config-defined value lists."""
        cfg = config or {}
        lower = (raw_status or "").lower()

        running_values = [v.lower() for v in (cfg.get("running_values") or [])]
        completed_values = [v.lower() for v in (cfg.get("completed_values") or [])]
        failed_values = [v.lower() for v in (cfg.get("failed_values") or [])]
        cancelled_values = [v.lower() for v in (cfg.get("cancelled_values") or [])]

        if running_values and lower in running_values:
            return "running"
        if completed_values and lower in completed_values:
            return "completed"
        if failed_values and lower in failed_values:
            return "failed"
        if cancelled_values and lower in cancelled_values:
            return "cancelled"

        # Default heuristic when no explicit lists are configured.
        if lower in ("running", "in_progress", "queued", "pending"):
            return "running"
        if lower in ("success", "completed", "done", "finished"):
            return "completed"
        if lower in ("failure", "failed", "error"):
            return "failed"
        if lower in ("cancelled", "canceled", "aborted"):
            return "cancelled"
        return "unknown"

    def normalize_error(self, raw_error: dict[str, Any]) -> dict[str, Any]:
        """Extract a canonical error dict from a generic error payload."""
        body = raw_error.get("body") or {}
        message = (
            body.get("message") or body.get("error") or raw_error.get("status") or "Pipeline failed"
        )
        return {
            "message": str(message),
            "code": "generic_webhook_failure",
            "details": raw_error,
        }

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _http_post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("httpx is required for GenericWebhookProvider")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=json)
        try:
            body: Any = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return {"status_code": resp.status_code, "body": body}

    async def _http_get(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("httpx is required for GenericWebhookProvider")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
        try:
            body: Any = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return {"status_code": resp.status_code, "body": body}

    async def _http_delete(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("httpx is required for GenericWebhookProvider")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(url, headers=headers)
        try:
            body: Any = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return {"status_code": resp.status_code, "body": body}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _maybe_auth_header(credentials: dict[str, Any]) -> dict[str, str]:
    """Return an Authorization header dict if a token is present."""
    token = credentials.get("token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _extract_field(obj: Any, field_path: str) -> Any:
    """Extract a value from *obj* using a dot-separated *field_path*."""
    if not isinstance(obj, dict):
        return None
    parts = field_path.split(".")
    current: Any = obj
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


__all__ = ["GenericWebhookProvider"]
