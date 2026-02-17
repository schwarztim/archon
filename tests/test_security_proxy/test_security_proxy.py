"""Unit tests for security.proxy — SecurityProxy."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from security.proxy.config import (
    ContentClassification,
    DLPPattern,
    EndpointRule,
    LogLevel,
    PolicyAction,
    PolicyRule,
    ProxySettings,
    AuditConfig,
)
from security.proxy.proxy import InteractionLog, ProxyResult, SecurityProxy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_settings() -> ProxySettings:
    """Minimal proxy settings for testing."""
    return ProxySettings(upstream_base_url="https://api.example.com")


@pytest.fixture
def proxy(default_settings: ProxySettings) -> SecurityProxy:
    """SecurityProxy with default settings."""
    return SecurityProxy(default_settings)


@pytest.fixture
def strict_settings() -> ProxySettings:
    """Settings with blocked endpoints and strict policy."""
    return ProxySettings(
        upstream_base_url="https://api.example.com",
        blocked_endpoints=[
            EndpointRule(
                pattern=r"/v1/dangerous",
                action=PolicyAction.BLOCK,
                reason="Dangerous endpoint blocked.",
            ),
        ],
        policy_rules=[
            PolicyRule(
                name="block-restricted",
                classification=ContentClassification.RESTRICTED,
                action=PolicyAction.BLOCK,
                priority=0,
            ),
            PolicyRule(
                name="block-bad-words",
                blocked_keywords=["DROP TABLE"],
                action=PolicyAction.BLOCK,
                priority=1,
            ),
        ],
    )


@pytest.fixture
def strict_proxy(strict_settings: ProxySettings) -> SecurityProxy:
    return SecurityProxy(strict_settings)


# ---------------------------------------------------------------------------
# Config model tests
# ---------------------------------------------------------------------------

class TestProxySettings:
    def test_defaults(self) -> None:
        s = ProxySettings()
        assert s.upstream_base_url == ""
        assert len(s.allowed_endpoints) == 1
        assert len(s.dlp_patterns) == 3
        assert s.audit.enabled is True

    def test_invalid_endpoint_regex(self) -> None:
        with pytest.raises(ValueError, match="Invalid regex"):
            EndpointRule(pattern="[invalid", action=PolicyAction.BLOCK)

    def test_invalid_dlp_regex(self) -> None:
        with pytest.raises(ValueError, match="Invalid DLP regex"):
            DLPPattern(name="bad", regex="[invalid")

    def test_custom_settings(self) -> None:
        s = ProxySettings(
            upstream_base_url="https://custom.api",
            request_timeout_seconds=60.0,
        )
        assert s.upstream_base_url == "https://custom.api"
        assert s.request_timeout_seconds == 60.0


# ---------------------------------------------------------------------------
# DLP tests
# ---------------------------------------------------------------------------

class TestDLP:
    def test_ssn_redaction(self, proxy: SecurityProxy) -> None:
        text = "My SSN is 123-45-6789 please."
        findings, redacted = proxy.apply_dlp(text)
        assert "SSN" in findings
        assert "123-45-6789" not in redacted
        assert "[SSN_REDACTED]" in redacted

    def test_email_redaction(self, proxy: SecurityProxy) -> None:
        text = "Contact me at user@example.com."
        findings, redacted = proxy.apply_dlp(text)
        assert "Email" in findings
        assert "user@example.com" not in redacted
        assert "[EMAIL_REDACTED]" in redacted

    def test_no_findings(self, proxy: SecurityProxy) -> None:
        text = "This is a clean message with no PII."
        findings, redacted = proxy.apply_dlp(text)
        assert findings == []
        assert redacted == text

    def test_multiple_findings(self, proxy: SecurityProxy) -> None:
        text = "SSN: 111-22-3333, email: a@b.com"
        findings, redacted = proxy.apply_dlp(text)
        assert "SSN" in findings
        assert "Email" in findings
        assert "111-22-3333" not in redacted
        assert "a@b.com" not in redacted

    def test_custom_dlp_pattern(self) -> None:
        settings = ProxySettings(
            dlp_patterns=[
                DLPPattern(
                    name="API Key",
                    regex=r"sk-[a-zA-Z0-9]{20,}",
                    replacement="[API_KEY_REDACTED]",
                ),
            ],
        )
        proxy = SecurityProxy(settings)
        text = "Key: sk-abcdefghijklmnopqrstuvwxyz"
        findings, redacted = proxy.apply_dlp(text)
        assert "API Key" in findings
        assert "[API_KEY_REDACTED]" in redacted


# ---------------------------------------------------------------------------
# Policy enforcement tests
# ---------------------------------------------------------------------------

class TestPolicyEnforcement:
    def test_allow_clean_content(self, proxy: SecurityProxy) -> None:
        action = proxy.enforce_policy("Hello world", ContentClassification.PUBLIC)
        assert action == PolicyAction.ALLOW

    def test_block_restricted_content(self, strict_proxy: SecurityProxy) -> None:
        action = strict_proxy.enforce_policy(
            "some text", ContentClassification.RESTRICTED
        )
        assert action == PolicyAction.BLOCK

    def test_block_keyword(self, strict_proxy: SecurityProxy) -> None:
        action = strict_proxy.enforce_policy(
            "Please DROP TABLE users", ContentClassification.PUBLIC
        )
        assert action == PolicyAction.BLOCK

    def test_keyword_case_insensitive(self, strict_proxy: SecurityProxy) -> None:
        action = strict_proxy.enforce_policy(
            "drop table students", ContentClassification.PUBLIC
        )
        assert action == PolicyAction.BLOCK

    def test_no_matching_rule(self, strict_proxy: SecurityProxy) -> None:
        action = strict_proxy.enforce_policy(
            "Normal request", ContentClassification.PUBLIC
        )
        assert action == PolicyAction.ALLOW


# ---------------------------------------------------------------------------
# Endpoint blocking tests
# ---------------------------------------------------------------------------

class TestEndpointBlocking:
    def test_blocked_endpoint(self, strict_proxy: SecurityProxy) -> None:
        reason = strict_proxy._check_endpoint_blocked(
            "https://api.example.com/v1/dangerous/thing"
        )
        assert reason != ""

    def test_allowed_endpoint(self, strict_proxy: SecurityProxy) -> None:
        reason = strict_proxy._check_endpoint_blocked(
            "https://api.example.com/v1/chat/completions"
        )
        assert reason == ""


# ---------------------------------------------------------------------------
# Audit logging tests
# ---------------------------------------------------------------------------

class TestAuditLogging:
    def test_log_interaction(self, proxy: SecurityProxy) -> None:
        entry = InteractionLog(method="POST", path="/v1/chat/completions")
        proxy.log_interaction(entry)
        log = proxy.get_audit_log()
        assert len(log) == 1
        assert log[0].method == "POST"

    def test_disabled_audit(self) -> None:
        settings = ProxySettings(
            audit=AuditConfig(enabled=False),
        )
        p = SecurityProxy(settings)
        entry = InteractionLog(method="POST", path="/test")
        p.log_interaction(entry)
        assert len(p.get_audit_log()) == 0

    def test_headers_only_mode(self) -> None:
        settings = ProxySettings(
            audit=AuditConfig(log_level=LogLevel.HEADERS_ONLY),
        )
        p = SecurityProxy(settings)
        entry = InteractionLog(
            method="POST", path="/test",
            request_body="sensitive data",
            response_body="secret response",
        )
        p.log_interaction(entry)
        logged = p.get_audit_log()[0]
        assert logged.request_body == ""
        assert logged.response_body == ""

    def test_redacted_mode_applies_dlp(self) -> None:
        settings = ProxySettings(
            audit=AuditConfig(log_level=LogLevel.REDACTED),
        )
        p = SecurityProxy(settings)
        entry = InteractionLog(
            method="POST", path="/test",
            request_body="SSN: 123-45-6789",
        )
        p.log_interaction(entry)
        logged = p.get_audit_log()[0]
        assert "123-45-6789" not in logged.request_body

    def test_ring_buffer_limit(self) -> None:
        p = SecurityProxy()
        p._max_audit_entries = 5
        for i in range(10):
            p.log_interaction(InteractionLog(method="GET", path=f"/{i}"))
        assert len(p.get_audit_log()) == 5


# ---------------------------------------------------------------------------
# Header sanitisation tests
# ---------------------------------------------------------------------------

class TestHeaderSanitisation:
    def test_sensitive_headers_masked(self) -> None:
        headers = {
            "Authorization": "Bearer sk-secret",
            "Content-Type": "application/json",
            "X-Api-Key": "my-key",
        }
        sanitised = SecurityProxy._sanitise_headers(headers)
        assert sanitised["Authorization"] == "***"
        assert sanitised["X-Api-Key"] == "***"
        assert sanitised["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Content classification tests
# ---------------------------------------------------------------------------

class TestContentClassification:
    def test_public(self, proxy: SecurityProxy) -> None:
        assert proxy._classify_content("Hello") == ContentClassification.PUBLIC

    def test_restricted(self, proxy: SecurityProxy) -> None:
        assert proxy._classify_content("My password is abc") == ContentClassification.RESTRICTED

    def test_confidential(self, proxy: SecurityProxy) -> None:
        assert proxy._classify_content("This is confidential info") == ContentClassification.CONFIDENTIAL

    def test_internal(self, proxy: SecurityProxy) -> None:
        assert proxy._classify_content("internal document draft") == ContentClassification.INTERNAL


# ---------------------------------------------------------------------------
# Integration: intercept_request
# ---------------------------------------------------------------------------

class TestInterceptRequest:
    @pytest.mark.asyncio
    async def test_blocked_endpoint_returns_403(self, strict_proxy: SecurityProxy) -> None:
        result = await strict_proxy.intercept_request(
            method="POST",
            path="/v1/dangerous/endpoint",
            body=b'{"prompt": "hello"}',
        )
        assert result.blocked is True
        assert result.status_code == 403
        body = json.loads(result.body)
        assert body["errors"][0]["code"] == "ENDPOINT_BLOCKED"

    @pytest.mark.asyncio
    async def test_policy_block_returns_403(self, strict_proxy: SecurityProxy) -> None:
        result = await strict_proxy.intercept_request(
            method="POST",
            path="/v1/chat/completions",
            body=b'{"prompt": "tell me my password"}',
        )
        assert result.blocked is True
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_successful_forward(self, proxy: SecurityProxy) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"choices": [{"message": {"content": "Hi"}}]}'

        with patch.object(proxy, "_forward", return_value=ProxyResult(
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"choices": [{"message": {"content": "Hi"}}]}',
        )):
            result = await proxy.intercept_request(
                method="POST",
                path="/v1/chat/completions",
                headers={"Authorization": "Bearer sk-test"},
                body=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "hello"}]}',
            )
        assert result.status_code == 200
        assert result.blocked is False
        assert result.correlation_id != ""

    @pytest.mark.asyncio
    async def test_dlp_redacts_response(self, proxy: SecurityProxy) -> None:
        with patch.object(proxy, "_forward", return_value=ProxyResult(
            status_code=200,
            headers={},
            body=b'{"response": "Your number is 999-88-7777"}',
        )):
            result = await proxy.intercept_request(
                method="POST",
                path="/v1/chat/completions",
                body=b'{"prompt": "what is my ID number?"}',
            )
        assert b"999-88-7777" not in result.body
        assert b"[SSN_REDACTED]" in result.body

    @pytest.mark.asyncio
    async def test_audit_log_populated(self, proxy: SecurityProxy) -> None:
        with patch.object(proxy, "_forward", return_value=ProxyResult(
            status_code=200, headers={}, body=b"ok",
        )):
            await proxy.intercept_request(
                method="GET", path="/v1/models", body=b"",
            )
        assert len(proxy.get_audit_log()) >= 1


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_close(self, proxy: SecurityProxy) -> None:
        await proxy.start()
        assert proxy._client is not None
        await proxy.close()
        assert proxy._client is None

    @pytest.mark.asyncio
    async def test_double_start(self, proxy: SecurityProxy) -> None:
        await proxy.start()
        client = proxy._client
        await proxy.start()  # should not create a new client
        assert proxy._client is client
        await proxy.close()
