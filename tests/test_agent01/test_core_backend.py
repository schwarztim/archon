"""Tests for Agent schemas, execute endpoint, audit logs auth, and health alias."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.schemas.agent_schemas import (
    AgentCreate,
    AgentStep,
    AgentUpdate,
    ExecuteAgentRequest,
    LLMConfig,
    MCPConfig,
    RAGConfig,
    SecurityPolicy,
    ToolBinding,
)


# ── AgentStep schema ────────────────────────────────────────────────


class TestAgentStep:
    """Tests for AgentStep Pydantic model."""

    def test_minimal_step(self) -> None:
        step = AgentStep(name="input")
        assert step.name == "input"
        assert step.type == "action"
        assert step.config == {}
        assert step.next is None

    def test_full_step(self) -> None:
        step = AgentStep(name="llm_call", type="llm", config={"model": "gpt-4"}, next="output")
        assert step.type == "llm"
        assert step.config == {"model": "gpt-4"}
        assert step.next == "output"


# ── ToolBinding schema ──────────────────────────────────────────────


class TestToolBinding:
    """Tests for ToolBinding Pydantic model."""

    def test_minimal_binding(self) -> None:
        tb = ToolBinding(name="search")
        assert tb.name == "search"
        assert tb.type == "function"
        assert tb.required is False

    def test_required_tool(self) -> None:
        tb = ToolBinding(name="calculator", type="builtin", required=True)
        assert tb.required is True
        assert tb.type == "builtin"


# ── LLMConfig schema ───────────────────────────────────────────────


class TestLLMConfig:
    """Tests for LLMConfig Pydantic model."""

    def test_defaults(self) -> None:
        cfg = LLMConfig()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096
        assert cfg.top_p == 1.0
        assert cfg.extra == {}

    def test_custom(self) -> None:
        cfg = LLMConfig(provider="anthropic", model="claude-3", temperature=0.0)
        assert cfg.provider == "anthropic"
        assert cfg.temperature == 0.0


# ── RAGConfig schema ───────────────────────────────────────────────


class TestRAGConfig:
    """Tests for RAGConfig Pydantic model."""

    def test_defaults(self) -> None:
        cfg = RAGConfig()
        assert cfg.enabled is False
        assert cfg.top_k == 5

    def test_enabled(self) -> None:
        cfg = RAGConfig(enabled=True, collection_id="abc", top_k=10)
        assert cfg.enabled is True
        assert cfg.collection_id == "abc"


# ── MCPConfig schema ───────────────────────────────────────────────


class TestMCPConfig:
    """Tests for MCPConfig Pydantic model."""

    def test_defaults(self) -> None:
        cfg = MCPConfig()
        assert cfg.enabled is False
        assert cfg.tools == []

    def test_with_tools(self) -> None:
        cfg = MCPConfig(enabled=True, server_url="http://mcp", tools=["tool1"])
        assert cfg.tools == ["tool1"]


# ── SecurityPolicy schema ──────────────────────────────────────────


class TestSecurityPolicy:
    """Tests for SecurityPolicy Pydantic model."""

    def test_defaults(self) -> None:
        sp = SecurityPolicy()
        assert sp.max_tokens_per_request == 10000
        assert sp.require_approval is False
        assert sp.dlp_enabled is False

    def test_custom_policy(self) -> None:
        sp = SecurityPolicy(
            max_tokens_per_request=500,
            allowed_tools=["search"],
            blocked_tools=["shell"],
            require_approval=True,
            dlp_enabled=True,
        )
        assert sp.max_tokens_per_request == 500
        assert "search" in sp.allowed_tools
        assert sp.require_approval is True


# ── AgentCreate schema ─────────────────────────────────────────────


class TestAgentCreate:
    """Tests for AgentCreate Pydantic model with typed sub-schemas."""

    def test_minimal_create(self) -> None:
        ac = AgentCreate(name="test-agent")
        assert ac.name == "test-agent"
        assert ac.status == "draft"
        assert ac.steps is None
        assert ac.llm_config is None

    def test_with_typed_subschemas(self) -> None:
        ac = AgentCreate(
            name="advanced-agent",
            definition={"type": "langgraph"},
            steps=[AgentStep(name="s1")],
            tools=[ToolBinding(name="t1")],
            llm_config=LLMConfig(provider="openai"),
            rag_config=RAGConfig(enabled=True),
            mcp_config=MCPConfig(enabled=False),
            security_policy=SecurityPolicy(require_approval=True),
        )
        assert ac.steps is not None
        assert len(ac.steps) == 1
        assert isinstance(ac.steps[0], AgentStep)
        assert isinstance(ac.llm_config, LLMConfig)
        assert isinstance(ac.security_policy, SecurityPolicy)

    def test_serialization_round_trip(self) -> None:
        ac = AgentCreate(
            name="rt-agent",
            definition={"type": "linear"},
            llm_config=LLMConfig(provider="azure", model="gpt-4o"),
        )
        data = ac.model_dump(mode="json")
        assert data["llm_config"]["provider"] == "azure"
        assert data["llm_config"]["model"] == "gpt-4o"

    def test_empty_tags(self) -> None:
        ac = AgentCreate(name="no-tags")
        assert ac.tags == []


# ── AgentUpdate schema ─────────────────────────────────────────────


class TestAgentUpdate:
    """Tests for AgentUpdate Pydantic model with typed sub-schemas."""

    def test_partial_update(self) -> None:
        au = AgentUpdate(name="renamed")
        data = au.model_dump(exclude_unset=True)
        assert "name" in data
        assert "description" not in data

    def test_update_with_llm_config(self) -> None:
        au = AgentUpdate(llm_config=LLMConfig(temperature=0.1))
        data = au.model_dump(exclude_unset=True, mode="json")
        assert data["llm_config"]["temperature"] == 0.1

    def test_update_with_security_policy(self) -> None:
        au = AgentUpdate(security_policy=SecurityPolicy(dlp_enabled=True))
        data = au.model_dump(exclude_unset=True, mode="json")
        assert data["security_policy"]["dlp_enabled"] is True


# ── ExecuteAgentRequest schema ──────────────────────────────────────


class TestExecuteAgentRequest:
    """Tests for ExecuteAgentRequest Pydantic model."""

    def test_defaults(self) -> None:
        req = ExecuteAgentRequest()
        assert req.input == {}
        assert req.config_overrides == {}

    def test_with_input(self) -> None:
        req = ExecuteAgentRequest(input={"query": "hello"}, config_overrides={"temperature": 0.5})
        assert req.input["query"] == "hello"
        assert req.config_overrides["temperature"] == 0.5

    def test_empty_input(self) -> None:
        req = ExecuteAgentRequest(input={})
        assert req.input == {}


# ── Health endpoint ─────────────────────────────────────────────────


class TestHealthEndpoint:
    """Tests for the /api/v1/health alias endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_timestamp(self) -> None:
        from app.health import health_check

        result = await health_check()
        assert result["status"] == "healthy"
        assert "timestamp" in result
        assert "version" in result

    @pytest.mark.asyncio
    async def test_health_v1_alias_exists(self) -> None:
        """Verify the /api/v1/health route is registered in the health router."""
        from app.health import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/api/v1/health" in paths


# ── Execute endpoint logic ──────────────────────────────────────────


class TestExecuteEndpointLogic:
    """Tests for the agent execution stub logic."""

    def test_simulate_execution_sets_completed(self) -> None:
        from app.routes.agents import _simulate_execution
        from app.models import Execution

        execution = Execution(
            agent_id=uuid4(),
            input_data={"query": "test"},
        )
        _simulate_execution(execution)
        assert execution.status == "completed"
        assert execution.output_data is not None
        assert execution.started_at is not None
        assert execution.completed_at is not None
        assert execution.metrics is not None
        assert "duration_ms" in execution.metrics
        assert execution.steps is not None

    def test_simulate_execution_has_mock_output(self) -> None:
        from app.routes.agents import _simulate_execution
        from app.models import Execution

        execution = Execution(
            agent_id=uuid4(),
            input_data={"query": "test"},
        )
        _simulate_execution(execution)
        assert execution.output_data["response"] == "Agent execution completed successfully"


# ── Audit logs auth dependency ──────────────────────────────────────


class TestAuditLogsAuth:
    """Tests that audit log routes have auth dependency."""

    def test_list_endpoint_requires_auth(self) -> None:
        """Verify that list_audit_logs has get_current_user dependency."""
        from app.routes.audit_logs import list_audit_logs
        import inspect

        sig = inspect.signature(list_audit_logs)
        param_names = list(sig.parameters.keys())
        assert "_user" in param_names

    def test_export_endpoint_requires_auth(self) -> None:
        """Verify that export_audit_logs has get_current_user dependency."""
        from app.routes.audit_logs import export_audit_logs
        import inspect

        sig = inspect.signature(export_audit_logs)
        param_names = list(sig.parameters.keys())
        assert "_user" in param_names


# ── Audit logs empty DB handling ────────────────────────────────────


class TestAuditLogsEmptyDB:
    """Tests that audit logs handle empty database gracefully."""

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self) -> None:
        """_fetch_entries should return empty list when DB is empty."""
        from app.routes.audit_logs import _fetch_entries

        mock_session = AsyncMock()

        with patch.object(
            __import__("app.services.audit_log_service", fromlist=["AuditLogService"]).AuditLogService,
            "list_all",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            entries, total = await _fetch_entries(
                mock_session,
                resource_type=None,
                resource_id=None,
                actor_id=None,
                limit=20,
                offset=0,
            )
            assert entries == []
            assert total == 0
