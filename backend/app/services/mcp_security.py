"""MCP Security Guardian — enterprise security layer for MCP tool interactions.

Provides tool authorization, ephemeral sandbox management,
change detection, and response validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from app.utils.time import utcnow as _utcnow
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.mcp_security import (
    MCPResponseValidation,
    MCPSandboxSession,
    MCPSecurityEvent,
    MCPToolAuthorization,
    MCPToolVersion,
)


def _hash_json(data: Any) -> str:
    """Return SHA-256 hex digest of JSON-serialised data."""
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()


# Patterns that indicate indirect prompt injection in tool responses
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)ignore\s+(all\s+)?previous\s+instructions?"),
    re.compile(r"(?i)system\s*:\s*you\s+are\s+now"),
    re.compile(r"(?i)forget\s+(everything|all)\s+(you|we)"),
    re.compile(r"(?i)act\s+as\s+(if\s+)?you\s+are"),
    re.compile(r"(?i)do\s+not\s+follow\s+(the\s+)?(previous|above)\s+instructions?"),
    re.compile(r"(?i)<\s*/?system\s*>"),
    re.compile(r"(?i)\[INST\]|\[/INST\]"),
    re.compile(r"(?i)BEGIN\s+INJECTION"),
]


class AuthorizationDecision:
    """Result of a tool authorization check."""

    __slots__ = ("allowed", "reason", "risk_level", "requires_approval", "policy_id")

    def __init__(
        self,
        *,
        allowed: bool,
        reason: str,
        risk_level: str = "low",
        requires_approval: bool = False,
        policy_id: UUID | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.risk_level = risk_level
        self.requires_approval = requires_approval
        self.policy_id = policy_id

    def to_dict(self) -> dict[str, Any]:
        """Serialise decision to dict."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "policy_id": str(self.policy_id) if self.policy_id else None,
        }


class ResponseValidationResult:
    """Result of validating an MCP tool response."""

    __slots__ = (
        "is_valid",
        "injection_detected",
        "injection_patterns",
        "anomaly_score",
        "was_truncated",
        "action_taken",
    )

    def __init__(
        self,
        *,
        is_valid: bool = True,
        injection_detected: bool = False,
        injection_patterns: list[str] | None = None,
        anomaly_score: float = 0.0,
        was_truncated: bool = False,
        action_taken: str = "pass",
    ) -> None:
        self.is_valid = is_valid
        self.injection_detected = injection_detected
        self.injection_patterns = injection_patterns or []
        self.anomaly_score = anomaly_score
        self.was_truncated = was_truncated
        self.action_taken = action_taken

    def to_dict(self) -> dict[str, Any]:
        """Serialise result to dict."""
        return {
            "is_valid": self.is_valid,
            "injection_detected": self.injection_detected,
            "injection_patterns": self.injection_patterns,
            "anomaly_score": self.anomaly_score,
            "was_truncated": self.was_truncated,
            "action_taken": self.action_taken,
        }


class MCPSecurityGuardian:
    """Enterprise MCP security engine.

    Provides tool authorization, ephemeral sandbox management,
    tool definition change detection, and response validation.
    All methods are async-first with DB persistence via SQLModel.
    """

    # ── Tool Authorization ──────────────────────────────────────────

    @staticmethod
    async def authorize_tool(
        session: AsyncSession,
        *,
        tool_name: str,
        server_name: str,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        """Check whether a tool call is authorized.

        Evaluates matching authorization policies in priority order.
        Most-specific match wins (user > agent > global).

        Args:
            session: Database session.
            tool_name: Name of the MCP tool being invoked.
            server_name: Name of the MCP server hosting the tool.
            agent_id: Optional agent requesting the call.
            user_id: Optional user requesting the call.
            parameters: Tool call parameters to validate against constraints.

        Returns:
            An AuthorizationDecision with the verdict.
        """
        stmt = (
            select(MCPToolAuthorization)
            .where(
                MCPToolAuthorization.tool_name == tool_name,
                MCPToolAuthorization.server_name == server_name,
                MCPToolAuthorization.is_active == True,  # noqa: E712
            )
            .order_by(MCPToolAuthorization.created_at.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        policies = list(result.all())

        if not policies:
            decision = AuthorizationDecision(
                allowed=True,
                reason="No policy found — default allow",
                risk_level="low",
            )
            await MCPSecurityGuardian._record_event(
                session,
                event_type="auth_granted",
                severity="info",
                tool_name=tool_name,
                server_name=server_name,
                agent_id=agent_id,
                user_id=user_id,
                details={"reason": decision.reason},
            )
            return decision

        # Find most-specific matching policy
        best: MCPToolAuthorization | None = None
        for policy in policies:
            if user_id and policy.user_id == user_id:
                best = policy
                break
            if agent_id and policy.agent_id == agent_id and best is None:
                best = policy
            if policy.user_id is None and policy.agent_id is None and best is None:
                best = policy

        if best is None:
            best = policies[0]

        # Validate parameter constraints
        if parameters and best.allowed_patterns:
            for param_name, pattern_str in best.allowed_patterns.items():
                param_value = str(parameters.get(param_name, ""))
                if param_value and not re.match(pattern_str, param_value):
                    decision = AuthorizationDecision(
                        allowed=False,
                        reason=f"Parameter '{param_name}' violates allowed pattern",
                        risk_level=best.risk_level,
                        policy_id=best.id,
                    )
                    await MCPSecurityGuardian._record_event(
                        session,
                        event_type="auth_denied",
                        severity="warning",
                        tool_name=tool_name,
                        server_name=server_name,
                        agent_id=agent_id,
                        user_id=user_id,
                        details={"reason": decision.reason, "policy_id": str(best.id)},
                    )
                    return decision

        if best.action == "deny":
            decision = AuthorizationDecision(
                allowed=False,
                reason="Denied by policy",
                risk_level=best.risk_level,
                policy_id=best.id,
            )
            event_type = "auth_denied"
            severity = "warning"
        elif best.action == "require_approval":
            decision = AuthorizationDecision(
                allowed=False,
                reason="Requires approval",
                risk_level=best.risk_level,
                requires_approval=True,
                policy_id=best.id,
            )
            event_type = "auth_denied"
            severity = "info"
        else:
            decision = AuthorizationDecision(
                allowed=True,
                reason="Allowed by policy",
                risk_level=best.risk_level,
                policy_id=best.id,
            )
            event_type = "auth_granted"
            severity = "info"

        await MCPSecurityGuardian._record_event(
            session,
            event_type=event_type,
            severity=severity,
            tool_name=tool_name,
            server_name=server_name,
            agent_id=agent_id,
            user_id=user_id,
            details={"reason": decision.reason, "policy_id": str(best.id)},
        )
        return decision

    # ── Authorization Policy CRUD ───────────────────────────────────

    @staticmethod
    async def create_authorization(
        session: AsyncSession, auth: MCPToolAuthorization
    ) -> MCPToolAuthorization:
        """Persist a new tool authorization policy."""
        session.add(auth)
        await session.commit()
        await session.refresh(auth)
        return auth

    @staticmethod
    async def get_authorization(
        session: AsyncSession, auth_id: UUID
    ) -> MCPToolAuthorization | None:
        """Return an authorization policy by ID."""
        return await session.get(MCPToolAuthorization, auth_id)

    @staticmethod
    async def list_authorizations(
        session: AsyncSession,
        *,
        tool_name: str | None = None,
        server_name: str | None = None,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPToolAuthorization], int]:
        """Return paginated authorization policies with optional filters."""
        base = select(MCPToolAuthorization)
        if tool_name is not None:
            base = base.where(MCPToolAuthorization.tool_name == tool_name)
        if server_name is not None:
            base = base.where(MCPToolAuthorization.server_name == server_name)
        if is_active is not None:
            base = base.where(MCPToolAuthorization.is_active == is_active)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                MCPToolAuthorization.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update_authorization(
        session: AsyncSession,
        auth_id: UUID,
        data: dict[str, Any],
    ) -> MCPToolAuthorization | None:
        """Partial-update an authorization policy. Returns None if not found."""
        auth = await session.get(MCPToolAuthorization, auth_id)
        if auth is None:
            return None
        for key, value in data.items():
            if hasattr(auth, key):
                setattr(auth, key, value)
        auth.updated_at = _utcnow()
        session.add(auth)
        await session.commit()
        await session.refresh(auth)
        return auth

    @staticmethod
    async def delete_authorization(session: AsyncSession, auth_id: UUID) -> bool:
        """Delete an authorization policy. Returns True if deleted."""
        auth = await session.get(MCPToolAuthorization, auth_id)
        if auth is None:
            return False
        await session.delete(auth)
        await session.commit()
        return True

    # ── Ephemeral Sandbox Management ────────────────────────────────

    @staticmethod
    async def create_sandbox(
        session: AsyncSession,
        *,
        tool_name: str,
        server_name: str,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        input_data: dict[str, Any] | None = None,
        resource_limits: dict[str, Any] | None = None,
        network_policy: dict[str, Any] | None = None,
        timeout_seconds: int = 30,
    ) -> MCPSandboxSession:
        """Create a new ephemeral sandbox session for an MCP tool call.

        Args:
            session: Database session.
            tool_name: Name of the tool to execute.
            server_name: MCP server name.
            agent_id: Agent requesting the execution.
            user_id: User requesting the execution.
            input_data: Tool input parameters (hashed, never stored raw).
            resource_limits: CPU/memory/network/disk limits.
            network_policy: Allowed outbound endpoints.
            timeout_seconds: Max execution time.

        Returns:
            Created MCPSandboxSession record.
        """
        sandbox = MCPSandboxSession(
            tool_name=tool_name,
            server_name=server_name,
            agent_id=agent_id,
            user_id=user_id,
            status="pending",
            resource_limits=resource_limits
            or {
                "cpu": "0.5",
                "memory_mb": 256,
                "network": "restricted",
                "disk_mb": 100,
            },
            network_policy=network_policy or {"allowed_endpoints": []},
            timeout_seconds=timeout_seconds,
            input_hash=_hash_json(input_data) if input_data else None,
        )
        session.add(sandbox)
        await session.commit()
        await session.refresh(sandbox)

        await MCPSecurityGuardian._record_event(
            session,
            event_type="sandbox_created",
            severity="info",
            tool_name=tool_name,
            server_name=server_name,
            agent_id=agent_id,
            user_id=user_id,
            sandbox_session_id=sandbox.id,
            details={"timeout_seconds": timeout_seconds},
        )
        return sandbox

    @staticmethod
    async def complete_sandbox(
        session: AsyncSession,
        sandbox_id: UUID,
        *,
        output_data: dict[str, Any] | None = None,
        exit_code: int = 0,
        error_message: str | None = None,
    ) -> MCPSandboxSession | None:
        """Mark a sandbox session as completed and destroyed.

        Returns:
            Updated sandbox session, or None if not found.
        """
        sandbox = await session.get(MCPSandboxSession, sandbox_id)
        if sandbox is None:
            return None

        now = _utcnow()
        sandbox.status = "completed" if exit_code == 0 else "failed"
        sandbox.output_hash = _hash_json(output_data) if output_data else None
        sandbox.exit_code = exit_code
        sandbox.error_message = error_message
        sandbox.completed_at = now
        sandbox.destroyed_at = now  # ephemeral: destroyed immediately

        session.add(sandbox)
        await session.commit()
        await session.refresh(sandbox)

        await MCPSecurityGuardian._record_event(
            session,
            event_type="sandbox_destroyed",
            severity="info" if exit_code == 0 else "warning",
            tool_name=sandbox.tool_name,
            server_name=sandbox.server_name,
            agent_id=sandbox.agent_id,
            user_id=sandbox.user_id,
            sandbox_session_id=sandbox.id,
            details={"exit_code": exit_code, "status": sandbox.status},
        )
        return sandbox

    @staticmethod
    async def get_sandbox(
        session: AsyncSession, sandbox_id: UUID
    ) -> MCPSandboxSession | None:
        """Return a sandbox session by ID."""
        return await session.get(MCPSandboxSession, sandbox_id)

    @staticmethod
    async def list_sandboxes(
        session: AsyncSession,
        *,
        status: str | None = None,
        tool_name: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPSandboxSession], int]:
        """Return paginated sandbox sessions with optional filters."""
        base = select(MCPSandboxSession)
        if status is not None:
            base = base.where(MCPSandboxSession.status == status)
        if tool_name is not None:
            base = base.where(MCPSandboxSession.tool_name == tool_name)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                MCPSandboxSession.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    # ── Change Detection & Version Management ───────────────────────

    @staticmethod
    async def detect_changes(
        session: AsyncSession,
        *,
        tool_name: str,
        server_name: str,
        current_definition: dict[str, Any],
        version: str = "latest",
    ) -> dict[str, Any]:
        """Compare a tool's current definition against the last recorded version.

        Args:
            session: Database session.
            tool_name: MCP tool name.
            server_name: MCP server name.
            current_definition: Current tool definition to compare.
            version: Version label for the new snapshot.

        Returns:
            Dict with change_type, diff_summary, and version info.
        """
        current_hash = _hash_json(current_definition)

        # Fetch the latest stored version
        stmt = (
            select(MCPToolVersion)
            .where(
                MCPToolVersion.tool_name == tool_name,
                MCPToolVersion.server_name == server_name,
            )
            .order_by(MCPToolVersion.created_at.desc())  # type: ignore[union-attr]
            .limit(1)
        )
        result = await session.exec(stmt)
        previous = result.first()

        if previous is None:
            # First time seeing this tool
            new_version = MCPToolVersion(
                tool_name=tool_name,
                server_name=server_name,
                version=version,
                definition=current_definition,
                definition_hash=current_hash,
                change_type="added",
                diff_summary="New tool added",
            )
            session.add(new_version)
            await session.commit()
            await session.refresh(new_version)

            await MCPSecurityGuardian._record_event(
                session,
                event_type="tool_added",
                severity="info",
                tool_name=tool_name,
                server_name=server_name,
                details={"version": version},
            )
            return {
                "change_type": "added",
                "diff_summary": "New tool added",
                "version_id": str(new_version.id),
                "previous_version_id": None,
                "changed": True,
            }

        if previous.definition_hash == current_hash:
            return {
                "change_type": "unchanged",
                "diff_summary": "No changes detected",
                "version_id": str(previous.id),
                "previous_version_id": None,
                "changed": False,
            }

        # Definition changed — compute diff summary
        diff_parts: list[str] = []
        prev_def = previous.definition or {}
        for key in set(list(prev_def.keys()) + list(current_definition.keys())):
            old_val = prev_def.get(key)
            new_val = current_definition.get(key)
            if old_val != new_val:
                if old_val is None:
                    diff_parts.append(f"Added '{key}'")
                elif new_val is None:
                    diff_parts.append(f"Removed '{key}'")
                else:
                    diff_parts.append(f"Modified '{key}'")
        diff_summary = "; ".join(diff_parts) or "Definition changed"

        new_version = MCPToolVersion(
            tool_name=tool_name,
            server_name=server_name,
            version=version,
            definition=current_definition,
            definition_hash=current_hash,
            change_type="modified",
            previous_version_id=previous.id,
            diff_summary=diff_summary,
        )
        session.add(new_version)
        await session.commit()
        await session.refresh(new_version)

        await MCPSecurityGuardian._record_event(
            session,
            event_type="tool_changed",
            severity="warning",
            tool_name=tool_name,
            server_name=server_name,
            details={
                "version": version,
                "diff_summary": diff_summary,
                "previous_version_id": str(previous.id),
            },
        )
        return {
            "change_type": "modified",
            "diff_summary": diff_summary,
            "version_id": str(new_version.id),
            "previous_version_id": str(previous.id),
            "changed": True,
        }

    @staticmethod
    async def list_tool_versions(
        session: AsyncSession,
        *,
        tool_name: str | None = None,
        server_name: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPToolVersion], int]:
        """Return paginated tool versions with optional filters."""
        base = select(MCPToolVersion)
        if tool_name is not None:
            base = base.where(MCPToolVersion.tool_name == tool_name)
        if server_name is not None:
            base = base.where(MCPToolVersion.server_name == server_name)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                MCPToolVersion.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def pin_version(
        session: AsyncSession, version_id: UUID, *, pin: bool = True
    ) -> MCPToolVersion | None:
        """Pin or unpin a tool version. Returns None if not found."""
        version = await session.get(MCPToolVersion, version_id)
        if version is None:
            return None
        version.is_pinned = pin
        session.add(version)
        await session.commit()
        await session.refresh(version)
        return version

    # ── Response Validation ─────────────────────────────────────────

    @staticmethod
    async def validate_response(
        session: AsyncSession,
        *,
        tool_name: str,
        server_name: str,
        response_text: str,
        sandbox_session_id: UUID | None = None,
        max_response_bytes: int = 1_048_576,
    ) -> ResponseValidationResult:
        """Validate an MCP tool response for injection and anomalies.

        Checks for:
        - Indirect prompt injection patterns
        - Response size limits
        - Anomalous content patterns

        Args:
            session: Database session.
            tool_name: Tool that produced the response.
            server_name: MCP server name.
            response_text: The raw response content.
            sandbox_session_id: Optional linked sandbox session.
            max_response_bytes: Maximum allowed response size.

        Returns:
            ResponseValidationResult with findings.
        """
        response_bytes = len(response_text.encode("utf-8"))
        was_truncated = response_bytes > max_response_bytes

        # Check for indirect prompt injection
        found_patterns: list[str] = []
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(response_text):
                found_patterns.append(pattern.pattern)

        injection_detected = len(found_patterns) > 0

        # Anomaly score: simple heuristic based on suspicious patterns
        anomaly_score = 0.0
        if injection_detected:
            anomaly_score += 0.5 * len(found_patterns)
        if was_truncated:
            anomaly_score += 0.2
        anomaly_score = min(anomaly_score, 1.0)

        # Determine action
        if injection_detected and anomaly_score >= 0.5:
            action_taken = "block"
            is_valid = False
        elif injection_detected:
            action_taken = "warn"
            is_valid = True
        elif was_truncated:
            action_taken = "warn"
            is_valid = True
        else:
            action_taken = "pass"
            is_valid = True

        # Persist validation record
        record = MCPResponseValidation(
            sandbox_session_id=sandbox_session_id,
            tool_name=tool_name,
            server_name=server_name,
            is_valid=is_valid,
            response_size_bytes=response_bytes,
            was_truncated=was_truncated,
            injection_detected=injection_detected,
            injection_patterns=found_patterns,
            anomaly_score=anomaly_score,
            action_taken=action_taken,
        )
        session.add(record)
        await session.commit()

        if injection_detected:
            await MCPSecurityGuardian._record_event(
                session,
                event_type="injection_detected",
                severity="critical" if action_taken == "block" else "warning",
                tool_name=tool_name,
                server_name=server_name,
                details={
                    "patterns": found_patterns,
                    "anomaly_score": anomaly_score,
                    "action_taken": action_taken,
                },
            )

        return ResponseValidationResult(
            is_valid=is_valid,
            injection_detected=injection_detected,
            injection_patterns=found_patterns,
            anomaly_score=anomaly_score,
            was_truncated=was_truncated,
            action_taken=action_taken,
        )

    # ── Security Events ─────────────────────────────────────────────

    @staticmethod
    async def list_events(
        session: AsyncSession,
        *,
        event_type: str | None = None,
        severity: str | None = None,
        tool_name: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPSecurityEvent], int]:
        """Return paginated security events with optional filters."""
        base = select(MCPSecurityEvent)
        if event_type is not None:
            base = base.where(MCPSecurityEvent.event_type == event_type)
        if severity is not None:
            base = base.where(MCPSecurityEvent.severity == severity)
        if tool_name is not None:
            base = base.where(MCPSecurityEvent.tool_name == tool_name)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                MCPSecurityEvent.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def get_event(
        session: AsyncSession, event_id: UUID
    ) -> MCPSecurityEvent | None:
        """Return a security event by ID."""
        return await session.get(MCPSecurityEvent, event_id)

    # ── Internal Helpers ────────────────────────────────────────────

    @staticmethod
    async def _record_event(
        session: AsyncSession,
        *,
        event_type: str,
        severity: str = "info",
        tool_name: str | None = None,
        server_name: str | None = None,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        sandbox_session_id: UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> MCPSecurityEvent:
        """Create and persist a security event."""
        event = MCPSecurityEvent(
            event_type=event_type,
            severity=severity,
            tool_name=tool_name,
            server_name=server_name,
            agent_id=agent_id,
            user_id=user_id,
            sandbox_session_id=sandbox_session_id,
            details=details or {},
        )
        session.add(event)
        await session.commit()
        return event


__all__ = [
    "AuthorizationDecision",
    "MCPSecurityGuardian",
    "ResponseValidationResult",
]
