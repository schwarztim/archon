"""HTTP request node executor — performs an HTTP/REST API call via httpx.

ActivityContext entry
---------------------
``execute_http_request(context)`` is the W4a ActivityContext-based entry
point. It reads config from ``context.node_config`` (keys: url, method,
headers, body, timeout_seconds, follow_redirects, allowed_domains) and
returns an ``ActivityResult``.

Egress allowlist: if ``node_config["allowed_domains"]`` is a non-empty list,
any URL whose hostname does not appear in the list is rejected with
``status="failed"`` and ``error_code="domain_not_allowed"``.

Large bodies (> 1 MB) are written as artifacts via ``context.write_artifact``
and excluded from ``output_data`` to keep the output dict lean.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register
from app.services.tracing import set_attr as _trace_set_attr
from app.services.tracing import span as _trace_span

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_LARGE_BODY_THRESHOLD = 1_048_576  # 1 MB


# ── ActivityContext entry ──────────────────────────────────────────────


async def execute_http_request(context: Any) -> Any:
    """W4a: perform an HTTP request, return ActivityResult.

    ``context`` is an ``ActivityContext`` (typed as ``Any`` here to avoid a
    circular import at module load; the runtime guarantees the type).
    """
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415

    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        return ActivityResult(
            status="failed",
            error_code="ImportError",
            error_message="httpx is not installed",
            non_retryable=True,
        )

    config: dict[str, Any] = context.node_config or {}
    method: str = (config.get("method") or "GET").upper()
    url: str | None = config.get("url")
    if not url:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="httpRequestNode: url is required",
            non_retryable=True,
        )

    # Egress allowlist
    allowed_domains: list[str] = config.get("allowed_domains") or []
    if allowed_domains:
        hostname = urlparse(url).hostname or ""
        if hostname not in allowed_domains:
            return ActivityResult(
                status="failed",
                error_code="domain_not_allowed",
                error_message=(
                    f"httpRequestNode: hostname {hostname!r} is not in the "
                    f"allowed_domains list"
                ),
                non_retryable=True,
            )

    # Headers
    headers: dict[str, str] = {}
    raw_headers = config.get("headers") or {}
    if isinstance(raw_headers, dict):
        headers.update(raw_headers)
    elif isinstance(raw_headers, list):
        for h in raw_headers:
            if isinstance(h, dict) and h.get("key"):
                headers[h["key"]] = h.get("value", "")

    # Body
    body: Any = config.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            pass

    timeout: float = float(config.get("timeout_seconds") or _DEFAULT_TIMEOUT)
    follow_redirects: bool = bool(config.get("follow_redirects", True))

    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=follow_redirects
        ) as client:
            if isinstance(body, (dict, list)):
                response = await client.request(
                    method, url, headers=headers, json=body
                )
            elif body:
                response = await client.request(
                    method, url, headers=headers, content=str(body)
                )
            else:
                response = await client.request(method, url, headers=headers)
    except httpx.TimeoutException as exc:
        return ActivityResult(
            status="failed",
            error_code="TimeoutError",
            error_message=f"request timed out after {timeout}s: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("execute_http_request.error", exc_info=True)
        return ActivityResult(
            status="failed",
            error_code=type(exc).__name__,
            error_message=str(exc)[:1024],
        )

    # Parse response body
    try:
        response_body: Any = response.json()
    except Exception:  # noqa: BLE001
        response_body = response.text

    # Write large bodies as artifacts
    artifacts: list[str] = []
    response_body_for_output = response_body
    raw_bytes = response.content
    if len(raw_bytes) > _LARGE_BODY_THRESHOLD:
        try:
            artifact_uri = await context.write_artifact(
                "http_response_body",
                raw_bytes,
                {"url": url, "status_code": response.status_code},
            )
            artifacts.append(artifact_uri)
            response_body_for_output = {"artifact_ref": artifact_uri}
        except Exception:  # noqa: BLE001
            pass  # best-effort; keep the in-memory body

    success = 200 <= response.status_code < 300
    output_data = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body": response_body_for_output,
    }

    if not success:
        return ActivityResult(
            status="failed",
            error_code=f"HTTP_{response.status_code}",
            error_message=f"HTTP {response.status_code}",
            output_data=output_data,
            artifacts=artifacts,
        )

    return ActivityResult(
        status="completed",
        output_data=output_data,
        artifacts=artifacts,
    )


@register("httpRequestNode")
class HTTPRequestNodeExecutor(NodeExecutor):
    """Execute an HTTP request and return the response body."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            return NodeResult(
                status="failed",
                error="httpRequestNode: httpx is not installed",
            )

        config = ctx.config
        method: str = (config.get("method") or "GET").upper()
        url: str | None = config.get("url")
        if not url:
            return NodeResult(
                status="failed",
                error="httpRequestNode: url is required",
            )

        # Headers
        headers: dict[str, str] = {}
        raw_headers = config.get("headers") or []
        if isinstance(raw_headers, list):
            for h in raw_headers:
                if isinstance(h, dict) and h.get("key"):
                    headers[h["key"]] = h.get("value", "")
        elif isinstance(raw_headers, dict):
            headers.update(raw_headers)

        # Auth
        auth_type: str = config.get("authType") or "none"
        if auth_type == "bearer" and config.get("authToken"):
            headers["Authorization"] = f"Bearer {config['authToken']}"
        elif auth_type == "api_key" and config.get("authToken"):
            headers[config.get("authHeader") or "X-API-Key"] = config["authToken"]

        # Body
        body: Any = config.get("body") or config.get("payload")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                pass  # send as raw string

        timeout: float = float(config.get("timeoutSeconds") or config.get("timeout") or _DEFAULT_TIMEOUT)

        if ctx.cancel_check():
            return NodeResult(status="skipped", output={"reason": "cancelled"})

        # W5.2 — wrap the HTTP call in an http.client span so latency
        # and status_code show up in the trace tree.
        async with _trace_span(
            "http.client",
            url=url,
            method=method,
            step_id=ctx.step_id,
            tenant_id=ctx.tenant_id,
        ):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if method in ("GET", "DELETE", "HEAD"):
                        response = await client.request(method, url, headers=headers)
                    else:
                        if isinstance(body, (dict, list)):
                            response = await client.request(method, url, headers=headers, json=body)
                        else:
                            response = await client.request(
                                method, url, headers=headers, content=str(body) if body else None
                            )
            except httpx.TimeoutException as exc:
                _trace_set_attr("error", f"timeout: {exc}"[:200])
                return NodeResult(
                    status="failed",
                    error=f"httpRequestNode: request timed out after {timeout}s: {exc}",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("httpRequestNode.request_error", exc_info=True)
                _trace_set_attr("error", f"{type(exc).__name__}: {exc}"[:200])
                return NodeResult(
                    status="failed",
                    error=f"httpRequestNode: {type(exc).__name__}: {exc}",
                )

            _trace_set_attr("http.status_code", response.status_code)

        # Parse response
        try:
            response_body = response.json()
        except Exception:  # noqa: BLE001
            response_body = response.text

        success = 200 <= response.status_code < 300
        return NodeResult(
            status="completed" if success else "failed",
            output={
                "status_code": response.status_code,
                "body": response_body,
                "headers": dict(response.headers),
            },
            error=None if success else f"HTTP {response.status_code}",
        )
