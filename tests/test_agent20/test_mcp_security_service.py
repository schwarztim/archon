"""Tests for MCPSecurityService — authorization, sandbox, consent, DLP, scoring, kill switch."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.mcp_security import (
    AuthMatrix,
    AuthorizationResult,
    ConsentStatus,
    MCPTool,
    MCPToolDefinition,
    RiskLevel,
    SecurityScore,
    ToolExecutionResult,
    ToolVersionDiff,
    ValidationResult,
)
from app.services.mcp_security_service import (
    MCPSecurityService,
    _consent_store,
    _tool_registry,
)

# ── Fixtures ────────────────────────────────────────────────────────

TENANT = "tenant-mcpsec-test"


def _user(**overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="sec@example.com",
        tenant_id=TENANT,
        roles=["admin"],
        permissions=[],
        session_id="sess-sec",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _tool_def(**overrides: Any) -> MCPToolDefinition:
    defaults: dict[str, Any] = dict(
        name="file_reader",
        description="Reads files from sandbox",
        input_schema={"properties": {"path": {"type": "string"}}},
        output_schema={"properties": {"content": {"type": "string"}}},
        required_scopes=["files:read"],
        risk_level=RiskLevel.LOW,
    )
    defaults.update(overrides)
    return MCPToolDefinition(**defaults)


@pytest.fixture(autouse=True)
def _clear_stores() -> None:
    _tool_registry.clear()
    _consent_store.clear()


async def _register_and_consent(
    user: AuthenticatedUser | None = None,
) -> tuple[str, AuthenticatedUser]:
    """Helper: register a tool and grant consent; returns (tool_id, user)."""
    user = user or _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    await MCPSecurityService.manage_consent(
        TENANT, user, tool.id, "grant", ["files:read"],
    )
    return tool.id, user


# ── authorize_tool_call ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authorize_tool_call_granted() -> None:
    tool_id, user = await _register_and_consent()
    result = await MCPSecurityService.authorize_tool_call(
        TENANT, user, tool_id, ["files:read"],
    )
    assert isinstance(result, AuthorizationResult)
    assert result.authorized is True


@pytest.mark.asyncio
async def test_authorize_tool_call_missing_scopes() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    result = await MCPSecurityService.authorize_tool_call(
        TENANT, user, tool.id, ["files:read"],
    )
    assert result.authorized is False
    assert "files:read" in result.missing_scopes


@pytest.mark.asyncio
async def test_authorize_tool_call_unregistered_tool() -> None:
    user = _user()
    result = await MCPSecurityService.authorize_tool_call(
        TENANT, user, "nonexistent", ["read"],
    )
    assert result.authorized is False
    assert "not registered" in result.reason.lower()


# ── execute_tool_sandboxed ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_sandboxed_active_tool() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    result = await MCPSecurityService.execute_tool_sandboxed(
        TENANT, user, tool.id, {"path": "/tmp/test.txt"},
    )
    assert isinstance(result, ToolExecutionResult)
    assert result.output["result"] == "executed"
    assert result.sandbox_id != ""
    assert result.execution_time_ms >= 0


@pytest.mark.asyncio
async def test_execute_sandboxed_inactive_tool() -> None:
    user = _user()
    result = await MCPSecurityService.execute_tool_sandboxed(
        TENANT, user, "missing-tool", {},
    )
    assert result.output == {"error": "Tool not available"}


# ── register_tool ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_tool_returns_mcp_tool() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    assert isinstance(tool, MCPTool)
    assert tool.name == "file_reader"
    assert tool.status == "active"
    assert tool.version == "1.0.0"
    assert tool.scopes == ["files:read"]


@pytest.mark.asyncio
async def test_register_tool_stored_in_registry() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    assert tool.id in _tool_registry[TENANT]


# ── manage_consent ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_grant() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    status = await MCPSecurityService.manage_consent(
        TENANT, user, tool.id, "grant", ["files:read", "files:write"],
    )
    assert isinstance(status, ConsentStatus)
    assert "files:read" in status.granted_scopes
    assert "files:write" in status.granted_scopes


@pytest.mark.asyncio
async def test_consent_revoke() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    await MCPSecurityService.manage_consent(
        TENANT, user, tool.id, "grant", ["files:read"],
    )
    status = await MCPSecurityService.manage_consent(
        TENANT, user, tool.id, "revoke", ["files:read"],
    )
    assert "files:read" in status.revoked_scopes


# ── validate_tool_response ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_response_clean() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    result = await MCPSecurityService.validate_tool_response(
        TENANT, tool.id, {"content": "hello"},
    )
    assert isinstance(result, ValidationResult)
    assert result.valid is True
    assert result.dlp_findings == []


@pytest.mark.asyncio
async def test_validate_response_dlp_pii_detected() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    result = await MCPSecurityService.validate_tool_response(
        TENANT, tool.id, {"content": "SSN: 123-45-6789"},
    )
    assert result.valid is False
    assert any("ssn" in f for f in result.dlp_findings)
    assert result.risk_level == RiskLevel.HIGH


@pytest.mark.asyncio
async def test_validate_response_unexpected_fields() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    result = await MCPSecurityService.validate_tool_response(
        TENANT, tool.id, {"content": "ok", "extra_field": "unexpected"},
    )
    assert any("extra_field" in e for e in result.schema_errors)


# ── compute_security_score ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_security_score_registered_tool() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    score = await MCPSecurityService.compute_security_score(TENANT, tool.id)

    assert isinstance(score, SecurityScore)
    assert score.overall > 0
    assert len(score.factors) >= 3


@pytest.mark.asyncio
async def test_security_score_unregistered_tool() -> None:
    score = await MCPSecurityService.compute_security_score(TENANT, "ghost")
    assert score.overall == 0.0
    assert any("Register" in r for r in score.recommendations)


# ── get_authorization_matrix ────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_matrix_contains_roles() -> None:
    user = _user()
    await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    matrix = await MCPSecurityService.get_authorization_matrix(TENANT)

    assert isinstance(matrix, AuthMatrix)
    assert "admin" in matrix.roles
    assert "viewer" in matrix.roles


@pytest.mark.asyncio
async def test_auth_matrix_empty_tenant() -> None:
    matrix = await MCPSecurityService.get_authorization_matrix("empty-tenant")
    assert matrix.roles["admin"] == []
    assert matrix.roles["viewer"] == []


# ── emergency_kill_switch ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_kill_switch_disables_tool() -> None:
    user = _user()
    tool = await MCPSecurityService.register_tool(TENANT, user, _tool_def())
    result = await MCPSecurityService.emergency_kill_switch(TENANT, user, tool.id)

    assert result["killed"] is True
    assert result["status"] == "killed"
    assert result["previous_status"] == "active"
    assert _tool_registry[TENANT][tool.id]["status"] == "killed"


@pytest.mark.asyncio
async def test_kill_switch_not_found() -> None:
    user = _user()
    result = await MCPSecurityService.emergency_kill_switch(TENANT, user, "ghost")
    assert result["killed"] is False
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_killed_tool_cannot_be_authorized() -> None:
    tool_id, user = await _register_and_consent()
    await MCPSecurityService.emergency_kill_switch(TENANT, user, tool_id)
    result = await MCPSecurityService.authorize_tool_call(
        TENANT, user, tool_id, ["files:read"],
    )
    assert result.authorized is False
    assert "disabled" in result.reason.lower()
