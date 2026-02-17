"""Configuration models for the Archon Security Proxy.

All settings use Pydantic models (not SQLModel — these are not DB-backed).
Runtime configuration is loaded from environment variables with the ``ARCHON_``
prefix via pydantic-settings, or supplied directly to the constructor.

Usage::

    from security.proxy.config import ProxySettings

    settings = ProxySettings()  # reads env vars
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ContentClassification(str, Enum):
    """Sensitivity level assigned to a request or response."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class PolicyAction(str, Enum):
    """Action taken when a policy rule matches."""

    ALLOW = "allow"
    BLOCK = "block"
    REDACT = "redact"
    LOG_ONLY = "log_only"


class LogLevel(str, Enum):
    """Verbosity of audit logging."""

    HEADERS_ONLY = "headers_only"
    FULL = "full"
    REDACTED = "redacted"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class EndpointRule(BaseModel):
    """Allow/block rule for a specific upstream endpoint pattern."""

    pattern: str = Field(
        ...,
        description="Regex pattern matched against the full upstream URL.",
    )
    action: PolicyAction = PolicyAction.ALLOW
    reason: str = ""

    @field_validator("pattern")
    @classmethod
    def _compile_check(cls, v: str) -> str:
        """Validate that *pattern* is a legal regular expression."""
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {exc}") from exc
        return v


class DLPPattern(BaseModel):
    """A named DLP detection pattern (simplified — real pipeline uses Presidio)."""

    name: str = Field(..., description="Human-readable label, e.g. 'SSN'.")
    regex: str = Field(..., description="Regex used for detection.")
    action: PolicyAction = PolicyAction.REDACT
    replacement: str = "[REDACTED]"

    @field_validator("regex")
    @classmethod
    def _compile_check(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid DLP regex: {exc}") from exc
        return v


class PolicyRule(BaseModel):
    """A single policy enforcement rule evaluated during request processing.

    Rules are evaluated in order; the first matching rule wins.
    """

    name: str
    description: str = ""
    classification: ContentClassification | None = None
    blocked_keywords: list[str] = Field(default_factory=list)
    action: PolicyAction = PolicyAction.BLOCK
    priority: int = Field(default=0, description="Lower = evaluated first.")


class AuditConfig(BaseModel):
    """Controls what and how interactions are logged."""

    enabled: bool = True
    log_level: LogLevel = LogLevel.REDACTED
    log_file: str | None = None
    export_webhook: str | None = None


# ---------------------------------------------------------------------------
# Top-level settings
# ---------------------------------------------------------------------------

class ProxySettings(BaseModel):
    """Complete configuration for the Security Proxy.

    Can be instantiated directly, loaded from a dict/YAML, or (when wrapped
    with pydantic-settings) populated from ``ARCHON_PROXY_*`` env vars.
    """

    # Upstream target (default: no upstream — must be configured)
    upstream_base_url: str = Field(
        default="",
        description="Base URL of the upstream AI API to proxy to.",
    )

    # Endpoint allow/block rules
    allowed_endpoints: list[EndpointRule] = Field(
        default_factory=lambda: [
            EndpointRule(pattern=r".*", action=PolicyAction.ALLOW),
        ],
    )
    blocked_endpoints: list[EndpointRule] = Field(default_factory=list)

    # DLP patterns
    dlp_patterns: list[DLPPattern] = Field(
        default_factory=lambda: [
            DLPPattern(
                name="SSN",
                regex=r"\b\d{3}-\d{2}-\d{4}\b",
                action=PolicyAction.REDACT,
                replacement="[SSN_REDACTED]",
            ),
            DLPPattern(
                name="Credit Card",
                regex=r"\b(?:\d[ -]*?){13,16}\b",
                action=PolicyAction.REDACT,
                replacement="[CC_REDACTED]",
            ),
            DLPPattern(
                name="Email",
                regex=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                action=PolicyAction.REDACT,
                replacement="[EMAIL_REDACTED]",
            ),
        ],
    )

    # Policy rules
    policy_rules: list[PolicyRule] = Field(
        default_factory=lambda: [
            PolicyRule(
                name="block-restricted-content",
                description="Block requests classified as restricted.",
                classification=ContentClassification.RESTRICTED,
                action=PolicyAction.BLOCK,
                priority=0,
            ),
        ],
    )

    # Audit
    audit: AuditConfig = Field(default_factory=AuditConfig)

    # Performance
    request_timeout_seconds: float = 30.0
    max_retries: int = 1
