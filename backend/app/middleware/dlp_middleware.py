"""DLP middleware — intercepts execution I/O for real-time scanning.

Scans request bodies on mutating execution endpoints (before LLM call) and
response bodies (after LLM response). Applies configured policy actions:
redact, block, log, or alert.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.services.dlp_service import DLPService
from app.services.guardrail_service import get_guardrail_service

logger = logging.getLogger(__name__)

# Paths that trigger DLP scanning (execution-related endpoints)
_EXECUTION_PATTERNS = re.compile(
    r"^/api/v1/(?:executions|agents/[^/]+/execute|agents/[^/]+/run|chat)"
)

# Paths to skip entirely
_SKIP_PATTERNS = re.compile(r"^/(healthz|readyz|livez|docs|redoc|openapi\.json|static)")

# Only scan mutating methods
_SCAN_METHODS = {"POST", "PUT", "PATCH"}


class DLPScanResult:
    """Lightweight result object for middleware-level DLP scans."""

    __slots__ = (
        "has_findings",
        "risk_level",
        "action",
        "findings_count",
        "scan_time_ms",
    )

    def __init__(
        self,
        has_findings: bool,
        risk_level: str,
        action: str,
        findings_count: int,
        scan_time_ms: float,
    ) -> None:
        self.has_findings = has_findings
        self.risk_level = risk_level
        self.action = action
        self.findings_count = findings_count
        self.scan_time_ms = scan_time_ms


def _extract_text_content(body: bytes) -> str | None:
    """Extract scannable text from a request/response body."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    # Common payload fields that carry user/LLM content
    text_fields = ["content", "input", "message", "prompt", "text", "query", "messages"]
    parts: list[str] = []

    if isinstance(data, dict):
        for field in text_fields:
            val = data.get(field)
            if isinstance(val, str) and val.strip():
                parts.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        msg_content = item.get("content", "")
                        if isinstance(msg_content, str):
                            parts.append(msg_content)

    return "\n".join(parts) if parts else None


def _scan_text(text: str, tenant_id: str, direction: str) -> DLPScanResult:
    """Run the DLP service scan and return a middleware result."""
    start = time.monotonic()
    result = DLPService.scan_content(
        tenant_id=tenant_id,
        content=text,
        direction=direction,
    )
    elapsed_ms = (time.monotonic() - start) * 1000.0

    return DLPScanResult(
        has_findings=len(result.findings) > 0,
        risk_level=result.risk_level.value,
        action=result.action.value,
        findings_count=len(result.findings),
        scan_time_ms=round(elapsed_ms, 2),
    )


def _apply_action(
    action: str,
    text: str,
    direction: str,
    findings_count: int,
    request_id: str,
) -> Response | str | None:
    """Apply the DLP action. Returns a Response if blocked, redacted text, or None."""
    if action == "block":
        logger.warning(
            "DLP middleware blocked request",
            extra={
                "request_id": request_id,
                "direction": direction,
                "findings_count": findings_count,
            },
        )
        return JSONResponse(
            status_code=403,
            content={
                "data": None,
                "meta": {
                    "request_id": request_id,
                    "error": "Content blocked by DLP policy",
                    "findings_count": findings_count,
                },
            },
        )

    if action == "redact":
        secret_findings = DLPService.scan_for_secrets(text)
        pii_findings = DLPService.scan_for_pii(text)
        all_findings = [*secret_findings, *pii_findings]
        redacted = DLPService.redact_content(text, all_findings)
        logger.info(
            "DLP middleware redacted content",
            extra={
                "request_id": request_id,
                "direction": direction,
                "findings_count": findings_count,
            },
        )
        return redacted

    if action == "alert":
        logger.warning(
            "DLP ALERT: sensitive content detected",
            extra={
                "request_id": request_id,
                "direction": direction,
                "findings_count": findings_count,
                "alert": True,
            },
        )
        return None

    # action == "log" or "allow"
    if findings_count > 0:
        logger.info(
            "DLP middleware logged detection",
            extra={
                "request_id": request_id,
                "direction": direction,
                "findings_count": findings_count,
            },
        )
    return None


class DLPMiddleware(BaseHTTPMiddleware):
    """Intercepts execution I/O and applies DLP scanning.

    Before the request reaches the handler: scans input content.
    After the response: scans output content.

    Actions: redact (mask), block (403), log (record), alert (log + warn).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process request through DLP pipeline."""
        # Skip non-execution paths and non-mutating methods
        if _SKIP_PATTERNS.match(request.url.path):
            return await call_next(request)

        if request.method not in _SCAN_METHODS:
            return await call_next(request)

        if not _EXECUTION_PATTERNS.match(request.url.path):
            return await call_next(request)

        request_id = str(uuid4())
        tenant_id = getattr(request.state, "tenant_id", "default")

        # ── Input scan (before handler) ─────────────────────────────
        try:
            body = await request.body()
            input_text = _extract_text_content(body)

            if input_text:
                # Guardrail check: prompt injection / toxicity before DLP
                try:
                    guardrail_svc = get_guardrail_service()
                    gr_result = guardrail_svc.check_input(
                        input_text, tenant_id=tenant_id
                    )
                    if not gr_result.passed:
                        violation_types = [v.type for v in gr_result.violations]
                        logger.warning(
                            "Guardrail blocked request",
                            extra={
                                "request_id": request_id,
                                "violations": violation_types,
                                "confidence": gr_result.confidence,
                            },
                        )
                        return JSONResponse(
                            status_code=400,
                            content={
                                "data": None,
                                "meta": {
                                    "request_id": request_id,
                                    "error": "Request blocked by content guardrails",
                                    "violations": violation_types,
                                },
                            },
                        )
                except Exception as g_exc:
                    logger.warning(
                        "Guardrail check failed — request will proceed unguarded",
                        extra={
                            "request_id": request_id,
                            "error_type": type(g_exc).__name__,
                        },
                    )

                input_result = _scan_text(input_text, tenant_id, "input")

                if input_result.has_findings:
                    action_response = _apply_action(
                        input_result.action,
                        input_text,
                        "input",
                        input_result.findings_count,
                        request_id,
                    )
                    if isinstance(action_response, Response):
                        return action_response
        except Exception as exc:
            logger.warning(
                "DLP middleware: input scan error — request will be passed through unscanned",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "error_type": type(exc).__name__,
                    "impact": "input DLP scan was skipped for this request",
                },
            )

        # ── Call the actual handler ─────────────────────────────────
        response = await call_next(request)

        # ── Output scan (after handler) ─────────────────────────────
        try:
            if response.status_code < 400:
                # Read response body for scanning
                response_body = b""
                async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                    if isinstance(chunk, str):
                        response_body += chunk.encode()
                    else:
                        response_body += chunk

                output_text = _extract_text_content(response_body)

                if output_text:
                    output_result = _scan_text(output_text, tenant_id, "output")

                    if output_result.has_findings:
                        action_response = _apply_action(
                            output_result.action,
                            output_text,
                            "output",
                            output_result.findings_count,
                            request_id,
                        )
                        if isinstance(action_response, Response):
                            return action_response

                # Re-create the response with the original (or redacted) body
                return Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
        except Exception as exc:
            logger.warning(
                "DLP middleware: output scan error — response will be returned unscanned",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "error_type": type(exc).__name__,
                    "impact": "output DLP scan was skipped for this response",
                },
            )

        return response


__all__ = [
    "DLPMiddleware",
]
