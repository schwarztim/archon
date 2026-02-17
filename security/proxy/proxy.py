"""Core Security Proxy for Archon.

The :class:`SecurityProxy` intercepts AI API calls and applies DLP scanning,
policy enforcement, and structured audit logging before forwarding to the
upstream provider.

Usage::

    from security.proxy import SecurityProxy
    from security.proxy.config import ProxySettings

    proxy = SecurityProxy(ProxySettings(upstream_base_url="https://api.openai.com"))
    result = await proxy.intercept_request(
        method="POST",
        path="/v1/chat/completions",
        headers={"Authorization": "Bearer sk-..."},
        body=b'{"model":"gpt-4","messages":[...]}',
    )
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from security.proxy.config import (
    AuditConfig,
    ContentClassification,
    DLPPattern,
    LogLevel,
    PolicyAction,
    PolicyRule,
    ProxySettings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class InteractionLog:
    """Structured record of a single proxied interaction.

    Attributes:
        correlation_id: Unique ID tying request/response together.
        timestamp: UTC time the request was received.
        method: HTTP method (GET, POST, …).
        path: Request path on the upstream.
        request_headers: Sanitised request headers.
        request_body: Request body (may be redacted).
        response_status: HTTP status returned by upstream.
        response_body: Response body (may be redacted).
        dlp_findings: List of DLP pattern names that matched.
        policy_action: Final policy decision (allow/block/redact/log_only).
        latency_ms: Round-trip time in milliseconds.
        classification: Content sensitivity classification.
    """

    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    method: str = ""
    path: str = ""
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: str = ""
    response_status: int = 0
    response_body: str = ""
    dlp_findings: list[str] = field(default_factory=list)
    policy_action: PolicyAction = PolicyAction.ALLOW
    latency_ms: float = 0.0
    classification: ContentClassification = ContentClassification.PUBLIC


@dataclass
class ProxyResult:
    """Value returned by :meth:`SecurityProxy.intercept_request`.

    Attributes:
        status_code: HTTP status code to return to the caller.
        headers: Response headers.
        body: Response body bytes.
        blocked: ``True`` when the request was blocked by policy.
        block_reason: Human-readable reason if blocked.
        correlation_id: Correlation ID for audit trail.
    """

    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    blocked: bool = False
    block_reason: str = ""
    correlation_id: str = ""


# ---------------------------------------------------------------------------
# SecurityProxy
# ---------------------------------------------------------------------------

_SENSITIVE_HEADERS = frozenset({"authorization", "x-api-key", "api-key", "cookie"})


class SecurityProxy:
    """Reverse proxy that intercepts AI API traffic and applies Archon's
    security stack: DLP scanning, policy enforcement, and audit logging.

    Parameters:
        settings: Full proxy configuration.
    """

    def __init__(self, settings: ProxySettings | None = None) -> None:
        self._settings = settings or ProxySettings()
        self._client: httpx.AsyncClient | None = None
        # Compiled DLP regexes (lazy-init on first use)
        self._dlp_compiled: list[tuple[DLPPattern, re.Pattern[str]]] | None = None
        # Compiled endpoint rules
        self._blocked_compiled: list[tuple[re.Pattern[str], str]] | None = None
        self._allowed_compiled: list[tuple[re.Pattern[str], str]] | None = None
        # In-memory audit log (bounded ring buffer)
        self._audit_log: list[InteractionLog] = []
        self._max_audit_entries = 10_000

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Create the underlying HTTP client.  Safe to call multiple times."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.request_timeout_seconds),
                follow_redirects=True,
            )

    async def close(self) -> None:
        """Shut down the HTTP client gracefully."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- public API ---------------------------------------------------------

    async def intercept_request(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> ProxyResult:
        """Intercept an outbound AI API request.

        Runs the full security pipeline:
        1. Endpoint allow/block check
        2. DLP scan on request body
        3. Policy enforcement
        4. Forward to upstream (if allowed)
        5. DLP scan on response body
        6. Audit log

        Returns a :class:`ProxyResult` that the caller can forward to the
        original client.
        """
        correlation_id = uuid.uuid4().hex[:12]
        start_time = time.monotonic()
        headers = dict(headers or {})
        body_text = (body or b"").decode("utf-8", errors="replace")

        log_entry = InteractionLog(
            correlation_id=correlation_id,
            method=method.upper(),
            path=path,
            request_headers=self._sanitise_headers(headers),
            request_body=body_text,
        )

        # Step 1: Endpoint rules ------------------------------------------------
        full_url = f"{self._settings.upstream_base_url.rstrip('/')}/{path.lstrip('/')}"

        blocked_reason = self._check_endpoint_blocked(full_url)
        if blocked_reason:
            log_entry.policy_action = PolicyAction.BLOCK
            log_entry.latency_ms = (time.monotonic() - start_time) * 1000
            self.log_interaction(log_entry)
            return ProxyResult(
                status_code=403,
                body=json.dumps({"errors": [{"code": "ENDPOINT_BLOCKED", "message": blocked_reason}]}).encode(),
                blocked=True,
                block_reason=blocked_reason,
                correlation_id=correlation_id,
            )

        # Step 2: DLP scan on request ------------------------------------------
        dlp_findings, redacted_body = self.apply_dlp(body_text)
        log_entry.dlp_findings = dlp_findings

        # Step 3: Policy enforcement -------------------------------------------
        classification = self._classify_content(redacted_body)
        log_entry.classification = classification
        policy_decision = self.enforce_policy(redacted_body, classification)
        log_entry.policy_action = policy_decision

        if policy_decision == PolicyAction.BLOCK:
            log_entry.latency_ms = (time.monotonic() - start_time) * 1000
            self.log_interaction(log_entry)
            return ProxyResult(
                status_code=403,
                body=json.dumps({"errors": [{"code": "POLICY_BLOCKED", "message": "Request blocked by security policy."}]}).encode(),
                blocked=True,
                block_reason="Request blocked by security policy.",
                correlation_id=correlation_id,
            )

        # Step 4: Forward to upstream ------------------------------------------
        forward_body = redacted_body.encode("utf-8") if policy_decision == PolicyAction.REDACT else body
        upstream_result = await self._forward(
            method=method,
            url=full_url,
            headers=headers,
            body=forward_body,
        )

        # Step 5: DLP scan on response -----------------------------------------
        resp_text = upstream_result.body.decode("utf-8", errors="replace")
        resp_dlp_findings, resp_redacted = self.apply_dlp(resp_text)
        log_entry.dlp_findings.extend(resp_dlp_findings)

        final_body = resp_redacted.encode("utf-8") if resp_dlp_findings else upstream_result.body
        log_entry.response_status = upstream_result.status_code
        log_entry.response_body = resp_redacted if resp_dlp_findings else resp_text

        # Step 6: Audit log ----------------------------------------------------
        log_entry.latency_ms = (time.monotonic() - start_time) * 1000
        self.log_interaction(log_entry)

        return ProxyResult(
            status_code=upstream_result.status_code,
            headers=upstream_result.headers,
            body=final_body,
            blocked=False,
            correlation_id=correlation_id,
        )

    # -- DLP ----------------------------------------------------------------

    def apply_dlp(self, text: str) -> tuple[list[str], str]:
        """Scan *text* for sensitive data and redact matches.

        Returns:
            A tuple of ``(finding_names, redacted_text)``.
        """
        if self._dlp_compiled is None:
            self._dlp_compiled = [
                (p, re.compile(p.regex))
                for p in self._settings.dlp_patterns
            ]

        findings: list[str] = []
        redacted = text
        for pattern_def, compiled in self._dlp_compiled:
            if compiled.search(redacted):
                findings.append(pattern_def.name)
                if pattern_def.action == PolicyAction.REDACT:
                    redacted = compiled.sub(pattern_def.replacement, redacted)

        return findings, redacted

    # -- Policy enforcement -------------------------------------------------

    def enforce_policy(
        self,
        text: str,
        classification: ContentClassification | None = None,
    ) -> PolicyAction:
        """Evaluate policy rules against *text* and *classification*.

        Rules are sorted by priority (lower first) and the first match wins.
        Returns :attr:`PolicyAction.ALLOW` when no rule matches.
        """
        sorted_rules: list[PolicyRule] = sorted(
            self._settings.policy_rules, key=lambda r: r.priority
        )
        text_lower = text.lower()

        for rule in sorted_rules:
            # Classification match
            if rule.classification is not None and classification == rule.classification:
                logger.info(
                    "Policy rule '%s' matched on classification=%s",
                    rule.name,
                    classification,
                )
                return rule.action

            # Keyword match
            if rule.blocked_keywords:
                for kw in rule.blocked_keywords:
                    if kw.lower() in text_lower:
                        logger.info(
                            "Policy rule '%s' matched on keyword '%s'",
                            rule.name,
                            kw,
                        )
                        return rule.action

        return PolicyAction.ALLOW

    # -- Audit logging ------------------------------------------------------

    def log_interaction(self, entry: InteractionLog) -> None:
        """Persist an interaction log entry.

        Sensitive header values and request/response bodies are redacted
        based on the audit configuration before storage.
        """
        audit_cfg = self._settings.audit
        if not audit_cfg.enabled:
            return

        # Redact bodies if configured
        if audit_cfg.log_level == LogLevel.HEADERS_ONLY:
            entry.request_body = ""
            entry.response_body = ""
        elif audit_cfg.log_level == LogLevel.REDACTED:
            _, entry.request_body = self.apply_dlp(entry.request_body)
            _, entry.response_body = self.apply_dlp(entry.response_body)

        # Append to ring buffer
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]

        # Structured log output
        logger.info(
            "audit",
            extra={
                "correlation_id": entry.correlation_id,
                "method": entry.method,
                "path": entry.path,
                "policy_action": entry.policy_action.value,
                "classification": entry.classification.value,
                "dlp_findings": entry.dlp_findings,
                "latency_ms": round(entry.latency_ms, 2),
            },
        )

    def get_audit_log(self) -> list[InteractionLog]:
        """Return a copy of the in-memory audit log."""
        return list(self._audit_log)

    # -- internals ----------------------------------------------------------

    def _classify_content(self, text: str) -> ContentClassification:
        """Simple keyword-based content classification.

        Production deployments should replace this with a proper ML classifier
        or OPA integration.
        """
        text_lower = text.lower()
        restricted_signals = ["password", "secret", "private_key", "ssn", "social security"]
        confidential_signals = ["confidential", "internal only", "do not share"]
        internal_signals = ["internal", "draft"]

        for signal in restricted_signals:
            if signal in text_lower:
                return ContentClassification.RESTRICTED

        for signal in confidential_signals:
            if signal in text_lower:
                return ContentClassification.CONFIDENTIAL

        for signal in internal_signals:
            if signal in text_lower:
                return ContentClassification.INTERNAL

        return ContentClassification.PUBLIC

    def _check_endpoint_blocked(self, url: str) -> str:
        """Return a reason string if *url* matches a blocked endpoint rule, else ''."""
        if self._blocked_compiled is None:
            self._blocked_compiled = [
                (re.compile(rule.pattern), rule.reason)
                for rule in self._settings.blocked_endpoints
            ]

        for compiled, reason in self._blocked_compiled:
            if compiled.search(url):
                return reason or f"Endpoint blocked by pattern: {compiled.pattern}"

        return ""

    @staticmethod
    def _sanitise_headers(headers: dict[str, str]) -> dict[str, str]:
        """Return headers with sensitive values masked."""
        return {
            k: ("***" if k.lower() in _SENSITIVE_HEADERS else v)
            for k, v in headers.items()
        }

    async def _forward(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> ProxyResult:
        """Forward the request to the upstream and return a :class:`ProxyResult`."""
        await self.start()
        assert self._client is not None  # noqa: S101 — guarded by start()

        try:
            resp = await self._client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                content=body,
            )
            return ProxyResult(
                status_code=resp.status_code,
                headers=dict(resp.headers),
                body=resp.content,
            )
        except httpx.HTTPError as exc:
            logger.error("Upstream request failed: %s", exc)
            return ProxyResult(
                status_code=502,
                body=json.dumps({"errors": [{"code": "UPSTREAM_ERROR", "message": str(exc)}]}).encode(),
            )
