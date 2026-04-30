"""HTTP request node executor — performs an HTTP/REST API call via httpx."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register
from app.services.tracing import set_attr as _trace_set_attr
from app.services.tracing import span as _trace_span

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


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
