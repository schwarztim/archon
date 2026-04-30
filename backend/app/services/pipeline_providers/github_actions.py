"""GitHub Actions pipeline provider adapter (W9a).

Triggers workflows via the ``workflow_dispatch`` event and polls run status
via the GitHub REST API (Workflow Runs endpoint).

Required credentials keys:
  ``token``   — GitHub personal access token or installation token (Bearer)
  ``owner``   — repository owner (user or org)
  ``repo``    — repository name

Required config keys (for start_pipeline):
  ``workflow_id``   — workflow file name (e.g. "ci.yml") or numeric ID
  ``ref``           — git ref to run on (branch or tag name)
  ``inputs``        — optional dict of workflow_dispatch inputs

Required config keys (for get_pipeline_status / cancel_pipeline):
  ``owner`` and ``repo`` may be in config instead of credentials.

GitHub run status -> canonical mapping:
  queued / in_progress / waiting  -> "running"
  completed + conclusion=success   -> "completed"
  completed + conclusion=failure   -> "failed"
  completed + conclusion=cancelled -> "cancelled"
  completed + other conclusion     -> "failed"
  all others                       -> "unknown"
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"

# Raw GitHub workflow run statuses that mean "still going".
_RUNNING_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}

# Map raw conclusion values to canonical status.
_CONCLUSION_MAP: dict[str, str] = {
    "success": "completed",
    "failure": "failed",
    "neutral": "failed",
    "cancelled": "cancelled",
    "timed_out": "failed",
    "action_required": "failed",
    "skipped": "failed",
    "stale": "failed",
}


class GitHubActionsProvider:
    """Provider adapter for GitHub Actions workflow_dispatch + status polling."""

    # ── Protocol implementation ───────────────────────────────────────────────

    async def start_pipeline(
        self,
        *,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a workflow_dispatch event and return the triggered run's ID.

        GitHub's workflow_dispatch endpoint returns 204 with no body. We
        immediately poll the recent runs list to find the run we just created,
        matching by ref and triggering commit (workflow_run.head_branch or
        head_sha from config if provided).

        In this implementation the HTTP calls are delegated through
        ``_http_post`` / ``_http_get`` so tests can inject fakes by
        subclassing or by patching those methods.
        """
        token = credentials["token"]
        owner = credentials.get("owner") or config.get("owner", "")
        repo = credentials.get("repo") or config.get("repo", "")
        workflow_id = config["workflow_id"]
        ref = config.get("ref", "main")
        inputs: dict[str, Any] = config.get("inputs") or {}

        dispatch_url = (
            f"{_GITHUB_API}/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
        )
        body = {"ref": ref, "inputs": inputs}
        headers = _auth_headers(token)

        log.info(
            "github_actions.start_pipeline owner=%s repo=%s workflow=%s ref=%s",
            owner,
            repo,
            workflow_id,
            ref,
        )

        dispatch_resp = await self._http_post(dispatch_url, headers=headers, json=body)
        # 204 No Content is success; anything else is an error.
        if dispatch_resp.get("status_code", 204) not in (204, 200):
            raise RuntimeError(
                f"GitHub workflow_dispatch returned {dispatch_resp.get('status_code')}: "
                f"{dispatch_resp.get('body')}"
            )

        # Fetch the most recent run on this workflow + ref to get the run_id.
        runs_url = (
            f"{_GITHUB_API}/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
            f"?branch={ref}&per_page=1&event=workflow_dispatch"
        )
        runs_resp = await self._http_get(runs_url, headers=headers)
        runs = runs_resp.get("body", {})
        run_list = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
        if not run_list:
            # Return a synthetic run_id; caller can poll later once the run
            # appears in GitHub's index (typically < 5s delay).
            return {
                "external_run_id": "pending",
                "external_run_url": None,
                "owner": owner,
                "repo": repo,
                "workflow_id": workflow_id,
                "ref": ref,
            }

        latest_run = run_list[0]
        run_id = str(latest_run.get("id", ""))
        run_url = latest_run.get("html_url")
        return {
            "external_run_id": run_id,
            "external_run_url": run_url,
            "owner": owner,
            "repo": repo,
            "workflow_id": workflow_id,
            "ref": ref,
        }

    async def get_pipeline_status(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Poll a workflow run via GET /repos/{owner}/{repo}/actions/runs/{run_id}."""
        cfg = config or {}
        token = credentials["token"]
        owner = credentials.get("owner") or cfg.get("owner", "")
        repo = credentials.get("repo") or cfg.get("repo", "")

        url = f"{_GITHUB_API}/repos/{owner}/{repo}/actions/runs/{external_run_id}"
        resp = await self._http_get(url, headers=_auth_headers(token))
        run = resp.get("body", {}) if isinstance(resp.get("body"), dict) else {}

        raw_status: str = run.get("status", "unknown") or "unknown"
        conclusion: str | None = run.get("conclusion")
        canonical = self.normalize_status(raw_status)
        # When the run is "completed", the real outcome is determined by conclusion.
        if canonical == "completed" and conclusion:
            canonical = _CONCLUSION_MAP.get(conclusion.lower(), "failed")
        elif canonical == "completed" and not conclusion:
            # completed with no conclusion yet — still being finalised
            canonical = "running"

        error: dict[str, Any] | None = None
        if canonical == "failed":
            error = self.normalize_error(
                {"conclusion": conclusion, "run": run, "message": f"Run concluded: {conclusion}"}
            )

        return {
            "status": canonical,
            "raw_status": raw_status,
            "conclusion": conclusion,
            "error": error,
            "run_url": run.get("html_url"),
            "run_number": run.get("run_number"),
        }

    async def cancel_pipeline(
        self,
        *,
        external_run_id: str,
        credentials: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> bool:
        """POST /repos/{owner}/{repo}/actions/runs/{run_id}/cancel."""
        cfg = config or {}
        token = credentials["token"]
        owner = credentials.get("owner") or cfg.get("owner", "")
        repo = credentials.get("repo") or cfg.get("repo", "")

        url = (
            f"{_GITHUB_API}/repos/{owner}/{repo}/actions/runs/{external_run_id}/cancel"
        )
        try:
            resp = await self._http_post(url, headers=_auth_headers(token), json={})
            return resp.get("status_code", 0) in (202, 204, 200)
        except Exception as exc:  # noqa: BLE001
            log.warning("github_actions.cancel_pipeline failed: %s", exc)
            return False

    def normalize_status(self, raw_status: str) -> str:
        """Map GitHub workflow run status to canonical status."""
        lower = (raw_status or "").lower()
        if lower in _RUNNING_STATUSES:
            return "running"
        if lower == "completed":
            # Caller must also examine conclusion to get the real canonical value.
            # For normalize_status alone, completed => "completed"; the
            # get_pipeline_status method resolves conclusion separately.
            return "completed"
        return "unknown"

    def normalize_error(self, raw_error: dict[str, Any]) -> dict[str, Any]:
        """Extract a canonical error dict from a GitHub error payload."""
        return {
            "message": raw_error.get("message") or str(raw_error.get("conclusion")),
            "code": raw_error.get("conclusion") or "github_run_failure",
            "details": raw_error,
        }

    # ── HTTP helpers (injectable in tests) ───────────────────────────────────

    async def _http_post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> dict[str, Any]:
        """POST *url* with JSON body. Returns {status_code, body}."""
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("httpx is required for GitHubActionsProvider")

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
        """GET *url*. Returns {status_code, body}."""
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("httpx is required for GitHubActionsProvider")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
        try:
            body: Any = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return {"status_code": resp.status_code, "body": body}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


__all__ = ["GitHubActionsProvider"]
