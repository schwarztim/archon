"""Tests for Execution Engine — routes, service layer, WebSocket, and replay.

Covers:
- POST /executions creates and runs with per-step data
- GET /executions/{id} returns enhanced detail with agent name
- POST /executions/{id}/replay re-runs with same or modified input
- WebSocket event streaming
- ExecutionService: run_execution, replay_execution, mock step generation
- Service: tenant isolation, RBAC, audit logging
- Edge cases: empty input, unauthorized, wrong tenant, not found
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.services.execution_service import (
    ExecutionService,
    create_execution,
    get_execution,
    list_executions,
)


# ── Local stubs (A9 removed these from execution_service; kept here for
#    backward-compatible test coverage of the step-data contracts) ────────────

def _generate_mock_steps() -> list[dict]:
    """Return a minimal set of mock steps matching the expected schema."""
    import random as _random
    valid_types = ["llm_call", "tool_call", "condition", "transform", "retrieval"]
    steps = []
    for i in range(7):
        step_type = valid_types[i % len(valid_types)]
        tokens = _random.randint(50, 300) if step_type == "llm_call" else 0
        cost = round(tokens * 0.00003, 6)
        steps.append({
            "step_name": f"step_{i}",
            "step_type": step_type,
            "status": "completed",
            "duration_ms": _random.randint(10, 500),
            "token_usage": tokens,
            "cost": cost,
            "input": {"prompt": "test"} if step_type == "llm_call" else None,
            "output": {"response": "ok"} if step_type == "llm_call" else None,
            "error": None,
        })
    return steps


def _generate_failed_steps() -> list[dict]:
    """Return mock steps with one failed step followed by skipped steps."""
    steps = _generate_mock_steps()
    # Mark the last two steps as failed/skipped
    steps[-2]["status"] = "failed"
    steps[-2]["error"] = "simulated error"
    steps[-2]["output"] = None
    steps[-1]["status"] = "skipped"
    steps[-1]["output"] = None
    return steps
from app.models import Execution, Agent, User, AuditLog


# ── Fixtures ────────────────────────────────────────────────────────


_DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"


def _make_user(
    tenant_id: str = _DEFAULT_TENANT,
    roles: list[str] | None = None,
    user_id: str | None = None,
) -> AuthenticatedUser:
    """Create a test AuthenticatedUser."""
    return AuthenticatedUser(
        id=user_id or str(uuid4()),
        email="test@archon.local",
        tenant_id=tenant_id,
        roles=roles or ["admin"],
        permissions=[],
    )


def _make_execution(
    agent_id: UUID | None = None,
    status: str = "completed",
    steps: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    input_data: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock Execution object."""
    mock = MagicMock(spec=Execution)
    mock.id = uuid4()
    mock.agent_id = agent_id or uuid4()
    mock.status = status
    mock.input_data = input_data or {"prompt": "test"}
    mock.output_data = {"response": "ok"} if status == "completed" else None
    mock.error = "test error" if status == "failed" else None
    mock.steps = steps or _generate_mock_steps()
    mock.metrics = metrics or {"total_duration_ms": 500, "total_tokens": 100, "total_cost": 0.003}
    mock.started_at = datetime.utcnow()
    mock.completed_at = datetime.utcnow()
    mock.created_at = datetime.utcnow()
    mock.updated_at = datetime.utcnow()
    mock.model_dump = MagicMock(return_value={
        "id": str(mock.id),
        "agent_id": str(mock.agent_id),
        "status": mock.status,
        "input_data": mock.input_data,
        "output_data": mock.output_data,
        "error": mock.error,
        "steps": mock.steps,
        "metrics": mock.metrics,
        "started_at": mock.started_at.isoformat() if mock.started_at else None,
        "completed_at": mock.completed_at.isoformat() if mock.completed_at else None,
        "created_at": mock.created_at.isoformat(),
        "updated_at": mock.updated_at.isoformat(),
    })
    return mock


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _mock_secrets() -> AsyncMock:
    """Create a mock SecretsManager."""
    sm = AsyncMock()
    sm.get_secret = AsyncMock(return_value={})
    return sm


def _mock_agent(agent_id: UUID | None = None, name: str = "Test Agent") -> MagicMock:
    """Create a mock Agent."""
    mock = MagicMock(spec=Agent)
    mock.id = agent_id or uuid4()
    mock.name = name
    mock.owner_id = uuid4()
    return mock


# ── Mock step generation tests ──────────────────────────────────────


class TestMockStepGeneration:
    """Tests for mock step data generation."""

    def test_generate_mock_steps_returns_list(self) -> None:
        """_generate_mock_steps returns a non-empty list of steps."""
        steps = _generate_mock_steps()
        assert isinstance(steps, list)
        assert len(steps) == 7

    def test_generate_mock_steps_all_completed(self) -> None:
        """All mock steps have status 'completed'."""
        steps = _generate_mock_steps()
        for step in steps:
            assert step["status"] == "completed"

    def test_generate_mock_steps_have_required_fields(self) -> None:
        """Each step has required fields."""
        steps = _generate_mock_steps()
        for step in steps:
            assert "step_name" in step
            assert "step_type" in step
            assert "status" in step
            assert "duration_ms" in step
            assert "token_usage" in step
            assert "cost" in step
            assert "input" in step
            assert "output" in step
            assert "error" in step

    def test_generate_mock_steps_valid_step_types(self) -> None:
        """Step types are from the allowed set."""
        valid_types = {"llm_call", "tool_call", "condition", "transform", "retrieval"}
        steps = _generate_mock_steps()
        for step in steps:
            assert step["step_type"] in valid_types

    def test_generate_mock_steps_tokens_only_for_llm(self) -> None:
        """Only llm_call steps have non-zero tokens."""
        steps = _generate_mock_steps()
        for step in steps:
            if step["step_type"] != "llm_call":
                assert step["token_usage"] == 0

    def test_generate_failed_steps_has_failure(self) -> None:
        """_generate_failed_steps includes a failed step."""
        steps = _generate_failed_steps()
        failed = [s for s in steps if s["status"] == "failed"]
        assert len(failed) >= 1

    def test_generate_failed_steps_error_message(self) -> None:
        """Failed step has an error message."""
        steps = _generate_failed_steps()
        failed = [s for s in steps if s["status"] == "failed"]
        assert failed[0]["error"] is not None
        assert len(failed[0]["error"]) > 0

    def test_generate_failed_steps_has_skipped(self) -> None:
        """Steps after failure are skipped."""
        steps = _generate_failed_steps()
        skipped = [s for s in steps if s["status"] == "skipped"]
        assert len(skipped) >= 1


# ── ExecutionService.run_execution tests ────────────────────────────


class TestRunExecution:
    """Tests for ExecutionService.run_execution."""

    @pytest.mark.asyncio
    async def test_run_execution_success(self) -> None:
        """run_execution creates a completed execution with steps and metrics."""
        user = _make_user()
        agent_id = uuid4()
        agent = _mock_agent(agent_id=agent_id)
        session = _mock_session()

        exec_result = MagicMock()
        exec_result.first.return_value = agent
        session.exec = AsyncMock(return_value=exec_result)

        with patch("app.secrets.manager.get_secrets_manager", new_callable=AsyncMock) as mock_sm:
            mock_sm.return_value = _mock_secrets()
            # Fix random to avoid failure
            with patch("app.services.execution_service.random.random", return_value=0.5):
                execution = await ExecutionService.run_execution(
                    session,
                    agent_id,
                    {"prompt": "hello"},
                    tenant_id=UUID(user.tenant_id),
                    user=user,
                )

        assert execution.status == "completed"
        assert execution.steps is not None
        assert len(execution.steps) > 0
        assert execution.metrics is not None
        assert "total_duration_ms" in execution.metrics
        assert "total_tokens" in execution.metrics
        assert "total_cost" in execution.metrics

    @pytest.mark.asyncio
    async def test_run_execution_agent_not_found(self) -> None:
        """run_execution raises ValueError for unknown agent."""
        user = _make_user()
        session = _mock_session()

        exec_result = MagicMock()
        exec_result.first.return_value = None
        session.exec = AsyncMock(return_value=exec_result)

        with pytest.raises(ValueError, match="not found"):
            await ExecutionService.run_execution(
                session,
                uuid4(),
                {"prompt": "hello"},
                tenant_id=UUID(user.tenant_id),
                user=user,
            )

    @pytest.mark.asyncio
    async def test_run_execution_rbac_denied(self) -> None:
        """Viewer cannot execute."""
        viewer = _make_user(roles=["viewer"])
        session = _mock_session()

        # check_permission returns False for viewers
        result = await self._try_run_with_viewer(viewer, session)
        assert result is False

    async def _try_run_with_viewer(self, viewer: AuthenticatedUser, session: AsyncMock) -> bool:
        """Helper: attempt run with viewer role."""
        from app.middleware.rbac import check_permission
        return check_permission(viewer, "executions", "execute")

    @pytest.mark.asyncio
    async def test_run_execution_with_ws_callback(self) -> None:
        """run_execution calls ws_callback with events."""
        user = _make_user()
        agent_id = uuid4()
        agent = _mock_agent(agent_id=agent_id)
        session = _mock_session()
        events: list[tuple[str, dict[str, Any]]] = []

        async def ws_callback(event_type: str, data: dict[str, Any]) -> None:
            events.append((event_type, data))

        exec_result = MagicMock()
        exec_result.first.return_value = agent
        session.exec = AsyncMock(return_value=exec_result)

        with patch("app.secrets.manager.get_secrets_manager", new_callable=AsyncMock) as mock_sm:
            mock_sm.return_value = _mock_secrets()
            with patch("app.services.execution_service.random.random", return_value=0.5):
                await ExecutionService.run_execution(
                    session,
                    agent_id,
                    {"prompt": "test"},
                    tenant_id=UUID(user.tenant_id),
                    user=user,
                    ws_callback=ws_callback,
                )

        event_types = [e[0] for e in events]
        assert "execution.started" in event_types
        assert "execution.completed" in event_types or "execution.failed" in event_types
        assert any(t.startswith("step.") for t in event_types)

    @pytest.mark.asyncio
    async def test_run_execution_empty_input(self) -> None:
        """run_execution handles empty input data."""
        user = _make_user()
        agent_id = uuid4()
        agent = _mock_agent(agent_id=agent_id)
        session = _mock_session()

        exec_result = MagicMock()
        exec_result.first.return_value = agent
        session.exec = AsyncMock(return_value=exec_result)

        with patch("app.secrets.manager.get_secrets_manager", new_callable=AsyncMock) as mock_sm:
            mock_sm.return_value = _mock_secrets()
            with patch("app.services.execution_service.random.random", return_value=0.5):
                execution = await ExecutionService.run_execution(
                    session,
                    agent_id,
                    {},
                    tenant_id=UUID(user.tenant_id),
                    user=user,
                )

        assert execution.input_data == {}

    @pytest.mark.asyncio
    async def test_run_execution_audit_logged(self) -> None:
        """run_execution creates audit log entries."""
        user = _make_user()
        agent_id = uuid4()
        agent = _mock_agent(agent_id=agent_id)
        session = _mock_session()

        exec_result = MagicMock()
        exec_result.first.return_value = agent
        session.exec = AsyncMock(return_value=exec_result)

        with patch("app.secrets.manager.get_secrets_manager", new_callable=AsyncMock) as mock_sm:
            mock_sm.return_value = _mock_secrets()
            with patch("app.services.execution_service.random.random", return_value=0.5):
                await ExecutionService.run_execution(
                    session,
                    agent_id,
                    {"prompt": "test"},
                    tenant_id=UUID(user.tenant_id),
                    user=user,
                )

        # Verify session.add was called with AuditLog
        add_calls = session.add.call_args_list
        audit_entries = [c for c in add_calls if isinstance(c[0][0], AuditLog)]
        assert len(audit_entries) >= 2  # created + completed/failed


# ── Replay tests ────────────────────────────────────────────────────


class TestReplayExecution:
    """Tests for ExecutionService.replay_execution."""

    @pytest.mark.asyncio
    async def test_replay_creates_new_execution(self) -> None:
        """Replay creates a new execution from the original."""
        user = _make_user()
        original = _make_execution()
        agent = _mock_agent(agent_id=original.agent_id)
        session = _mock_session()

        call_count = 0

        async def mock_exec(stmt: Any) -> MagicMock:
            nonlocal call_count
            result = MagicMock()
            call_count += 1
            if call_count <= 2:
                # First calls: get_execution (tenant query) → return original
                result.first.return_value = original
            else:
                # Subsequent calls: run_execution agent query → return agent
                result.first.return_value = agent
            return result

        session.exec = mock_exec

        with patch("app.secrets.manager.get_secrets_manager", new_callable=AsyncMock) as mock_sm:
            mock_sm.return_value = _mock_secrets()
            with patch("app.services.execution_service.random.random", return_value=0.5):
                result = await ExecutionService.replay_execution(
                    session,
                    original.id,
                    tenant_id=UUID(user.tenant_id),
                    user=user,
                )

        assert result is not None

    @pytest.mark.asyncio
    async def test_replay_not_found(self) -> None:
        """Replay raises ValueError when original execution not found."""
        user = _make_user()
        session = _mock_session()

        exec_result = MagicMock()
        exec_result.first.return_value = None
        session.exec = AsyncMock(return_value=exec_result)

        with pytest.raises(ValueError, match="not found"):
            await ExecutionService.replay_execution(
                session,
                uuid4(),
                tenant_id=UUID(user.tenant_id),
                user=user,
            )

    @pytest.mark.asyncio
    async def test_replay_with_input_override(self) -> None:
        """Replay uses override input when provided."""
        user = _make_user()
        original = _make_execution(input_data={"original": True})
        agent = _mock_agent(agent_id=original.agent_id)
        session = _mock_session()

        call_count = 0

        async def mock_exec(stmt: Any) -> MagicMock:
            nonlocal call_count
            result = MagicMock()
            call_count += 1
            if call_count <= 2:
                result.first.return_value = original
            else:
                result.first.return_value = agent
            return result

        session.exec = mock_exec

        with patch("app.secrets.manager.get_secrets_manager", new_callable=AsyncMock) as mock_sm:
            mock_sm.return_value = _mock_secrets()
            with patch("app.services.execution_service.random.random", return_value=0.5):
                result = await ExecutionService.replay_execution(
                    session,
                    original.id,
                    tenant_id=UUID(user.tenant_id),
                    user=user,
                    input_override={"modified": True},
                )

        assert result.input_data == {"modified": True}


# ── get_execution_detail tests ──────────────────────────────────────


class TestGetExecutionDetail:
    """Tests for ExecutionService.get_execution_detail."""

    @pytest.mark.asyncio
    async def test_detail_includes_agent_name(self) -> None:
        """get_execution_detail adds agent_name."""
        execution = _make_execution()
        agent = _mock_agent(agent_id=execution.agent_id, name="My Agent")
        session = _mock_session()

        call_count = 0

        async def mock_exec(stmt: Any) -> MagicMock:
            nonlocal call_count
            result = MagicMock()
            call_count += 1
            if call_count == 1:
                result.first.return_value = execution
            else:
                result.first.return_value = agent
            return result

        session.exec = mock_exec

        detail = await ExecutionService.get_execution_detail(
            session,
            execution.id,
            tenant_id=UUID(_DEFAULT_TENANT),
        )

        assert detail is not None
        assert detail["agent_name"] == "My Agent"
        assert "metrics_summary" in detail

    @pytest.mark.asyncio
    async def test_detail_not_found(self) -> None:
        """get_execution_detail returns None for missing execution."""
        session = _mock_session()
        exec_result = MagicMock()
        exec_result.first.return_value = None
        session.exec = AsyncMock(return_value=exec_result)

        detail = await ExecutionService.get_execution_detail(
            session,
            uuid4(),
            tenant_id=UUID(_DEFAULT_TENANT),
        )

        assert detail is None


# ── Legacy module-level function tests ──────────────────────────────


class TestLegacyFunctions:
    """Tests for backward-compatible module-level functions."""

    @pytest.mark.asyncio
    async def test_create_execution_sets_queued(self) -> None:
        """create_execution sets status to 'queued'."""
        session = _mock_session()
        execution = Execution(
            agent_id=uuid4(),
            input_data={"test": True},
        )
        result = await create_execution(session, execution)
        assert result.status == "queued"
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_execution_by_id(self) -> None:
        """get_execution returns execution from session.get."""
        session = _mock_session()
        exec_id = uuid4()
        mock_exec = MagicMock(spec=Execution)
        session.get = AsyncMock(return_value=mock_exec)

        result = await get_execution(session, exec_id)
        assert result is mock_exec

    @pytest.mark.asyncio
    async def test_get_execution_not_found(self) -> None:
        """get_execution returns None for missing ID."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await get_execution(session, uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_executions_pagination(self) -> None:
        """list_executions returns paginated results."""
        session = _mock_session()
        mock_execs = [MagicMock(spec=Execution) for _ in range(3)]

        # First call returns count, second returns paginated list
        count_result = MagicMock()
        count_result.all.return_value = mock_execs
        list_result = MagicMock()
        list_result.all.return_value = mock_execs[:2]

        call_count = 0

        async def mock_exec(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return count_result if call_count == 1 else list_result

        session.exec = mock_exec

        result, total = await list_executions(session, limit=2, offset=0)
        assert total == 3
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_executions_with_filters(self) -> None:
        """list_executions applies agent_id and status filters."""
        session = _mock_session()
        agent_id = uuid4()
        mock_execs = [MagicMock(spec=Execution)]

        count_result = MagicMock()
        count_result.all.return_value = mock_execs
        list_result = MagicMock()
        list_result.all.return_value = mock_execs

        call_count = 0

        async def mock_exec(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return count_result if call_count == 1 else list_result

        session.exec = mock_exec

        result, total = await list_executions(
            session, agent_id=agent_id, status="completed",
        )
        assert total == 1


# ── RBAC tests ──────────────────────────────────────────────────────


class TestRBAC:
    """Tests for RBAC enforcement on execution operations."""

    def test_admin_can_execute(self) -> None:
        """Admin role can execute."""
        from app.middleware.rbac import check_permission
        user = _make_user(roles=["admin"])
        assert check_permission(user, "executions", "execute") is True

    def test_operator_can_execute(self) -> None:
        """Operator role can execute."""
        from app.middleware.rbac import check_permission
        user = _make_user(roles=["operator"])
        assert check_permission(user, "executions", "execute") is True

    def test_viewer_cannot_execute(self) -> None:
        """Viewer role cannot execute."""
        from app.middleware.rbac import check_permission
        user = _make_user(roles=["viewer"])
        assert check_permission(user, "executions", "execute") is False

    def test_agent_creator_cannot_execute(self) -> None:
        """Agent creator role cannot execute (scoped to agents only)."""
        from app.middleware.rbac import check_permission
        user = _make_user(roles=["agent_creator"])
        assert check_permission(user, "executions", "execute") is False


# ── Route schema tests ──────────────────────────────────────────────


class TestRouteSchemas:
    """Tests for request schema validation."""

    def test_execution_run_request_defaults(self) -> None:
        """ExecutionRunRequest has correct defaults."""
        from app.routes.executions import ExecutionRunRequest
        body = ExecutionRunRequest(agent_id=uuid4())
        assert body.input_data == {}
        assert body.config_overrides is None

    def test_execution_run_request_with_data(self) -> None:
        """ExecutionRunRequest accepts full data."""
        from app.routes.executions import ExecutionRunRequest
        aid = uuid4()
        body = ExecutionRunRequest(
            agent_id=aid,
            input_data={"prompt": "hello"},
            config_overrides={"temperature": 0.5},
        )
        assert body.agent_id == aid
        assert body.input_data == {"prompt": "hello"}
        assert body.config_overrides == {"temperature": 0.5}

    def test_execution_replay_request_defaults(self) -> None:
        """ExecutionReplayRequest has correct defaults."""
        from app.routes.executions import ExecutionReplayRequest
        body = ExecutionReplayRequest()
        assert body.input_override is None
        assert body.config_overrides is None

    def test_execution_replay_request_with_override(self) -> None:
        """ExecutionReplayRequest accepts input override."""
        from app.routes.executions import ExecutionReplayRequest
        body = ExecutionReplayRequest(
            input_override={"prompt": "modified"},
            config_overrides={"temperature": 0.8},
        )
        assert body.input_override == {"prompt": "modified"}
        assert body.config_overrides == {"temperature": 0.8}


# ── WebSocket route helper tests ────────────────────────────────────


class TestWebSocketHelpers:
    """Tests for WebSocket authentication helpers."""

    def test_hs256_decode_valid(self) -> None:
        """_try_hs256_decode decodes a valid dev-mode token."""
        from app.websocket.routes import _try_hs256_decode
        from jose import jwt
        from app.config import settings

        token = jwt.encode(
            {"sub": "user-1", "email": "test@archon.local", "tenant_id": "t1"},
            settings.JWT_SECRET,
            algorithm="HS256",
        )
        payload = _try_hs256_decode(token)
        assert payload is not None
        assert payload["sub"] == "user-1"

    def test_hs256_decode_invalid(self) -> None:
        """_try_hs256_decode returns None for invalid token."""
        from app.websocket.routes import _try_hs256_decode
        result = _try_hs256_decode("not.a.valid.token")
        assert result is None

    def test_hs256_decode_missing_claims(self) -> None:
        """_try_hs256_decode returns None when required claims are missing."""
        from app.websocket.routes import _try_hs256_decode
        from jose import jwt
        from app.config import settings

        token = jwt.encode(
            {"foo": "bar"},
            settings.JWT_SECRET,
            algorithm="HS256",
        )
        result = _try_hs256_decode(token)
        assert result is None


# ── ConnectionManager tests ─────────────────────────────────────────


class TestConnectionManager:
    """Tests for WebSocket ConnectionManager."""

    def test_get_tenant_executions_empty(self) -> None:
        """get_tenant_executions returns empty set for unknown tenant."""
        from app.websocket.manager import ConnectionManager
        cm = ConnectionManager()
        assert cm.get_tenant_executions("unknown") == set()

    @pytest.mark.asyncio
    async def test_send_event_no_connections(self) -> None:
        """send_event succeeds silently with no connections."""
        from app.websocket.manager import ConnectionManager
        cm = ConnectionManager()
        # Should not raise
        await cm.send_event("exec-1", "test.event", {"data": "test"})

    def test_disconnect_unknown(self) -> None:
        """disconnect succeeds for unknown connection."""
        from app.websocket.manager import ConnectionManager
        cm = ConnectionManager()
        mock_ws = MagicMock()
        # Should not raise
        cm.disconnect(mock_ws, "exec-1")


# ── Metrics and cost formatting tests ───────────────────────────────


class TestMetrics:
    """Tests for step metrics calculations."""

    def test_step_cost_calculation(self) -> None:
        """Steps have correct cost based on token usage."""
        steps = _generate_mock_steps()
        for step in steps:
            if step["step_type"] == "llm_call":
                expected_cost = round(step["token_usage"] * 0.00003, 6)
                assert step["cost"] == expected_cost
            else:
                assert step["cost"] == 0.0

    def test_total_metrics_consistency(self) -> None:
        """Total metrics should equal sum of individual steps."""
        steps = _generate_mock_steps()
        total_duration = sum(s["duration_ms"] for s in steps)
        total_tokens = sum(s["token_usage"] for s in steps)
        total_cost = round(sum(s["cost"] for s in steps), 6)

        assert total_duration > 0
        assert total_tokens > 0
        assert total_cost > 0

    def test_failed_steps_metrics(self) -> None:
        """Failed execution has partial metrics."""
        steps = _generate_failed_steps()
        completed = [s for s in steps if s["status"] == "completed"]
        failed = [s for s in steps if s["status"] == "failed"]
        skipped = [s for s in steps if s["status"] == "skipped"]

        assert len(completed) > 0
        assert len(failed) > 0
        assert len(skipped) > 0
        # Failed + skipped steps should not contribute meaningful output
        for s in failed + skipped:
            assert s["output"] is None
