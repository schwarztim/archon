"""Azure DevOps pipeline provider adapter (W9a).

Triggers pipelines via the Azure DevOps Pipelines REST API (run) and polls
build status via GET /builds/{buildId}.

Required credentials keys:
  ``token``         — PAT or Azure AD access token (Basic or Bearer)
  ``organization``  — Azure DevOps organization name
  ``project``       — Azure DevOps project name

Required config keys (start_pipeline):
  ``pipeline_id``   — numeric pipeline definition ID
  ``branch``        — source ref / branch (e.g. "refs/heads/main")
  ``variables``     — optional dict of variable name → value
  ``parameters``    — optional dict for YAML-template parameters

Azure DevOps status -> canonical mapping:
  notStarted / inProgress / cancelling -> "running"
  succeeded                            -> "completed"
  failed / partiallySucceeded          -> "failed"
  cancelled                            -> "cancelled"
  all others                           -> "unknown"
"""

from __future__ import annotations

import base64
import logging
from typing import Any

log = logging.getLogger(__name__)

_ADO_API_VERSION = "7.1"

_STATUS_MAP: dict[str, str] = {
    "notstarted": "running",
    "inprogress": "running",
    "cancelling": "running",
    "succeeded": "completed",
    "failed": "failed",
    "partiallySucceeded": "failed",
    "partiallysucceeded": "failed",
    "cancelled": "cancelled",
}


class AzureDevOpsProvider:
    """Provider adapter for Azure DevOps Pipelines REST API."""

    # ── Protocol implementation ───────────────────────────────────────────────

    async def start_pipeline(
        self,
        *,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Trigger a pipeline run via POST /pipelines/{pipelineId}/runs."""
        org = credentials.get("organization") or config.get("organization", "")
        project = credentials.get("project") or config.get("project", "")
        pipeline_id = config["pipeline_id"]
        branch = config.get("branch", "refs/heads/main")
        variables: dict[str, Any] = config.get("variables") or {}
        parameters: dict[str, Any] = config.get("parameters") or {}

        url = (
            f"https://dev.azure.com/{org}/{project}/_apis/pipelines"
            f"/{pipeline_id}/runs?api-version={_ADO_API_VERSION}"
        )
        headers = _auth_headers(credentials["token"])

        body: dict[str, Any] = {
            "resources": {"repositories": {"self": {"refName": branch}}},
        }
        if variables:
            body["variables"] = {k: {"value": v} for k, v in variables.items()}
        if parameters:
            body["templateParameters"] = parameters

        log.info(
            "azure_devops.start_pipeline org=%s project=%s pipeline=%s branch=%s",
            org,
            project,
            pipeline_id,
            branch,
        )

        resp = await self._http_post(url, headers=headers, json=body)
        if resp.get("status_code", 0) not in (200, 201):
            raise RuntimeError(
                f"Azure DevOps pipeline trigger returned {resp.get('status_code')}: "
                f"{resp.get('body')}"
            )

        run_data = resp.get("body", {}) if isinstance(resp.get("body"), dict) else {}
        run_id = str(run_data.get("id", ""))
        run_url = run_data.get("_links", {}).get("web", {}).get("href")

        return {
            "external_run_id": run_id,
            "external_run_url": run_url,
            "organization": org,
            "project": project,
            "pipeline_id": pipeline_id,
            "branch": branch,
        }

    async def get_pipeline_status(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Poll build status via GET /build/builds/{buildId}."""
        cfg = config or {}
        org = credentials.get("organization") or cfg.get("organization", "")
        project = credentials.get("project") or cfg.get("project", "")

        url = (
            f"https://dev.azure.com/{org}/{project}/_apis/build/builds"
            f"/{external_run_id}?api-version={_ADO_API_VERSION}"
        )
        resp = await self._http_get(url, headers=_auth_headers(credentials["token"]))
        build = resp.get("body", {}) if isinstance(resp.get("body"), dict) else {}

        raw_status: str = build.get("status", "unknown") or "unknown"
        result: str | None = build.get("result")
        canonical = self.normalize_status(raw_status)

        # When ADO marks a build "completed" the final verdict is in `result`.
        if raw_status.lower() == "completed" and result:
            canonical = self.normalize_status(result)

        error: dict[str, Any] | None = None
        if canonical == "failed":
            error = self.normalize_error(
                {"result": result, "status": raw_status, "build": build}
            )

        return {
            "status": canonical,
            "raw_status": raw_status,
            "conclusion": result,
            "error": error,
            "run_url": build.get("_links", {}).get("web", {}).get("href"),
            "build_number": build.get("buildNumber"),
        }

    async def cancel_pipeline(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> bool:
        """PATCH /build/builds/{buildId} with status=cancelling."""
        cfg = config or {}
        org = credentials.get("organization") or cfg.get("organization", "")
        project = credentials.get("project") or cfg.get("project", "")

        url = (
            f"https://dev.azure.com/{org}/{project}/_apis/build/builds"
            f"/{external_run_id}?api-version={_ADO_API_VERSION}"
        )
        try:
            resp = await self._http_patch(
                url,
                headers=_auth_headers(credentials["token"]),
                json={"status": "cancelling"},
            )
            return resp.get("status_code", 0) in (200, 204)
        except Exception as exc:  # noqa: BLE001
            log.warning("azure_devops.cancel_pipeline failed: %s", exc)
            return False

    def normalize_status(self, raw_status: str) -> str:
        """Map Azure DevOps build status/result to canonical status."""
        return _STATUS_MAP.get((raw_status or "").lower(), "unknown")

    def normalize_error(self, raw_error: dict[str, Any]) -> dict[str, Any]:
        """Extract a canonical error dict from an Azure DevOps error payload."""
        result = raw_error.get("result") or "failed"
        return {
            "message": f"Azure DevOps build {result}",
            "code": raw_error.get("result") or "ado_build_failure",
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
            raise RuntimeError("httpx is required for AzureDevOpsProvider")

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
            raise RuntimeError("httpx is required for AzureDevOpsProvider")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
        try:
            body: Any = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return {"status_code": resp.status_code, "body": body}

    async def _http_patch(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("httpx is required for AzureDevOpsProvider")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(url, headers=headers, json=json)
        try:
            body: Any = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return {"status_code": resp.status_code, "body": body}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _auth_headers(token: str) -> dict[str, str]:
    """Return headers for PAT (Basic) or Bearer token authentication."""
    # If the token is already a Bearer token (JWT-shaped), use Bearer; otherwise
    # encode as a PAT using the Azure DevOps Basic auth convention.
    if token.count(".") >= 2:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    # PAT: Basic base64(":<pat>")
    encoded = base64.b64encode(f":{token}".encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
    }


__all__ = ["AzureDevOpsProvider"]
