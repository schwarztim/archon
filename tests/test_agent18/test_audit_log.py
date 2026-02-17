"""Tests for Agent 18 — Audit Log system (routes, service, middleware)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models import AuditLog
from app.services.audit_log_service import AuditLogService


# ── Helpers ──────────────────────────────────────────────────────────

def _make_entry(**overrides: Any) -> AuditLog:
    """Build a fake AuditLog instance for testing."""
    defaults: dict[str, Any] = {
        "id": uuid4(),
        "actor_id": uuid4(),
        "action": "agent.created",
        "resource_type": "agents",
        "resource_id": uuid4(),
        "details": {"status_code": 201, "outcome": "success"},
        "created_at": datetime(2025, 1, 15, 12, 0, 0),
    }
    defaults.update(overrides)
    return AuditLog(**defaults)


# ── AuditLogService tests ────────────────────────────────────────────

class TestAuditLogServiceCreate:
    """AuditLogService.create persists and returns an entry."""

    @pytest.mark.asyncio
    async def test_create_returns_entry(self) -> None:
        """create() adds entry to session and returns it."""
        session = AsyncMock()
        entry_data = {
            "actor_id": uuid4(),
            "action": "agent.created",
            "resource_type": "agents",
            "resource_id": uuid4(),
            "details": {"foo": "bar"},
        }
        result = await AuditLogService.create(session, **entry_data)
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()
        assert result.action == "agent.created"

    @pytest.mark.asyncio
    async def test_create_without_details(self) -> None:
        """create() works when details=None."""
        session = AsyncMock()
        result = await AuditLogService.create(
            session,
            actor_id=uuid4(),
            action="user.removed",
            resource_type="users",
            resource_id=uuid4(),
        )
        assert result.details is None


class TestAuditLogServiceListAll:
    """AuditLogService.list_all returns paginated entries."""

    @pytest.mark.asyncio
    async def test_list_all_returns_tuple(self) -> None:
        """list_all returns (entries, total)."""
        entries = [_make_entry(), _make_entry()]
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = entries
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_all(session, limit=10, offset=0)
        assert total == 2
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_all_empty(self) -> None:
        """list_all returns ([], 0) for empty DB."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_all(session)
        assert result == []
        assert total == 0


class TestAuditLogServiceListFiltered:
    """AuditLogService.list_filtered applies combined filters."""

    @pytest.mark.asyncio
    async def test_filtered_by_action(self) -> None:
        """list_filtered with action filter."""
        entry = _make_entry(action="agent.created")
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_filtered(
            session, action="agent.created",
        )
        assert total == 1
        assert result[0].action == "agent.created"

    @pytest.mark.asyncio
    async def test_filtered_by_resource_type(self) -> None:
        """list_filtered with resource_type filter."""
        entry = _make_entry(resource_type="secrets")
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_filtered(
            session, resource_type="secrets",
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_filtered_by_date_range(self) -> None:
        """list_filtered with date_from and date_to."""
        entry = _make_entry()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_filtered(
            session,
            date_from=datetime(2025, 1, 1),
            date_to=datetime(2025, 12, 31),
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_filtered_by_search(self) -> None:
        """list_filtered with search text."""
        entry = _make_entry(action="agent.created")
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_filtered(
            session, search="agent",
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_filtered_empty_result(self) -> None:
        """list_filtered returns empty when nothing matches."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_filtered(session)
        assert result == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_filtered_all_params(self) -> None:
        """list_filtered with every parameter set."""
        actor = uuid4()
        rid = uuid4()
        entry = _make_entry(actor_id=actor, resource_id=rid)
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_filtered(
            session,
            resource_type="agents",
            resource_id=rid,
            actor_id=actor,
            action="agent.created",
            search="agent",
            date_from=datetime(2025, 1, 1),
            date_to=datetime(2025, 12, 31),
            limit=5,
            offset=0,
        )
        assert total == 1


class TestAuditLogServiceListByResource:
    """AuditLogService.list_by_resource filters by type + id."""

    @pytest.mark.asyncio
    async def test_list_by_resource(self) -> None:
        """Returns entries matching resource_type and resource_id."""
        rid = uuid4()
        entry = _make_entry(resource_type="agents", resource_id=rid)
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_by_resource(
            session, resource_type="agents", resource_id=rid,
        )
        assert total == 1
        assert result[0].resource_id == rid


class TestAuditLogServiceListByActor:
    """AuditLogService.list_by_actor filters by actor_id."""

    @pytest.mark.asyncio
    async def test_list_by_actor(self) -> None:
        """Returns entries matching actor_id."""
        actor = uuid4()
        entry = _make_entry(actor_id=actor)
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        result, total = await AuditLogService.list_by_actor(
            session, actor_id=actor,
        )
        assert total == 1
        assert result[0].actor_id == actor


# ── Audit middleware tests ───────────────────────────────────────────

class TestAuditMiddleware:
    """AuditMiddleware auto-logs mutations."""

    def test_extract_resource_agents(self) -> None:
        """Extracts resource type and ID from /api/v1/agents/{uuid}."""
        from app.middleware.audit_middleware import _extract_resource

        uid = uuid4()
        rtype, rid = _extract_resource(f"/api/v1/agents/{uid}")
        assert rtype == "agents"
        assert rid == uid

    def test_extract_resource_no_id(self) -> None:
        """Extracts resource type without ID from /api/v1/agents."""
        from app.middleware.audit_middleware import _extract_resource

        rtype, rid = _extract_resource("/api/v1/agents")
        assert rtype == "agents"
        assert rid is None

    def test_extract_resource_unknown(self) -> None:
        """Returns 'unknown' for non-matching paths."""
        from app.middleware.audit_middleware import _extract_resource

        rtype, rid = _extract_resource("/healthz")
        assert rtype == "unknown"
        assert rid is None

    def test_derive_action_known(self) -> None:
        """Known method+resource maps to human-readable action."""
        from app.middleware.audit_middleware import _derive_action

        assert _derive_action("POST", "agents") == "agent.created"
        assert _derive_action("DELETE", "agents") == "agent.deleted"
        assert _derive_action("PUT", "policies") == "policy.updated"
        assert _derive_action("POST", "secrets") == "secret.created"

    def test_derive_action_unknown_resource(self) -> None:
        """Unknown resources fall back to resource.verb pattern."""
        from app.middleware.audit_middleware import _derive_action

        result = _derive_action("POST", "widgets")
        assert result == "widget.created"

    def test_skip_patterns_match(self) -> None:
        """Healthz and audit-logs paths are skipped."""
        from app.middleware.audit_middleware import _SKIP_PATTERNS

        assert _SKIP_PATTERNS.match("/healthz")
        assert _SKIP_PATTERNS.match("/api/v1/audit-logs")
        assert _SKIP_PATTERNS.match("/api/v1/audit-logs/export")
        assert not _SKIP_PATTERNS.match("/api/v1/agents")

    def test_mutation_methods(self) -> None:
        """Only POST/PUT/PATCH/DELETE are considered mutations."""
        from app.middleware.audit_middleware import _MUTATION_METHODS

        assert "POST" in _MUTATION_METHODS
        assert "PUT" in _MUTATION_METHODS
        assert "PATCH" in _MUTATION_METHODS
        assert "DELETE" in _MUTATION_METHODS
        assert "GET" not in _MUTATION_METHODS

    def test_action_map_coverage(self) -> None:
        """Action map covers required event types from build prompt."""
        from app.middleware.audit_middleware import _ACTION_MAP

        required_actions = {
            "agent.created", "agent.updated", "agent.deleted",
            "user.invited", "user.updated", "user.removed",
            "secret.created", "secret.rotated",
            "policy.created", "policy.updated",
            "deployment.created", "deployment.promoted",
            "connector.created", "workflow.created",
            "login.success", "sso.configured",
            "budget.created", "template.instantiated",
            "approval.submitted", "approval.approved",
        }
        mapped_actions = set(_ACTION_MAP.values())
        for action in required_actions:
            assert action in mapped_actions, f"Missing action: {action}"


# ── Routes tests ─────────────────────────────────────────────────────

class TestAuditRoutes:
    """Test audit_logs route helpers."""

    def test_meta_has_required_fields(self) -> None:
        """_meta() returns request_id and timestamp."""
        from app.routes.audit_logs import _meta

        meta = _meta()
        assert "request_id" in meta
        assert "timestamp" in meta

    def test_meta_custom_request_id(self) -> None:
        """_meta() accepts custom request_id."""
        from app.routes.audit_logs import _meta

        meta = _meta(request_id="custom-123")
        assert meta["request_id"] == "custom-123"

    def test_meta_extra_kwargs(self) -> None:
        """_meta() passes through extra keyword arguments."""
        from app.routes.audit_logs import _meta

        meta = _meta(pagination={"total": 0})
        assert meta["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_fetch_entries_empty_db(self) -> None:
        """_fetch_entries returns ([], 0) on exception (empty DB)."""
        from app.routes.audit_logs import _fetch_entries

        session = AsyncMock()
        session.exec.side_effect = Exception("no such table")

        entries, total = await _fetch_entries(
            session,
            resource_type=None,
            resource_id=None,
            actor_id=None,
            limit=20,
            offset=0,
        )
        assert entries == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_fetch_entries_returns_data(self) -> None:
        """_fetch_entries returns entries when service succeeds."""
        from app.routes.audit_logs import _fetch_entries

        entry = _make_entry()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        entries, total = await _fetch_entries(
            session,
            resource_type=None,
            resource_id=None,
            actor_id=None,
            limit=20,
            offset=0,
        )
        assert total == 1
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_fetch_entries_with_action_filter(self) -> None:
        """_fetch_entries passes action filter through."""
        from app.routes.audit_logs import _fetch_entries

        entry = _make_entry(action="agent.created")
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        entries, total = await _fetch_entries(
            session,
            resource_type=None,
            resource_id=None,
            actor_id=None,
            action="agent.created",
            limit=20,
            offset=0,
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_fetch_entries_with_search(self) -> None:
        """_fetch_entries passes search through."""
        from app.routes.audit_logs import _fetch_entries

        entry = _make_entry()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [entry]
        session.exec.return_value = mock_result

        entries, total = await _fetch_entries(
            session,
            resource_type=None,
            resource_id=None,
            actor_id=None,
            search="agent",
            limit=20,
            offset=0,
        )
        assert total == 1


class TestAuditImmutability:
    """Audit logs must not allow PUT/DELETE."""

    @pytest.mark.asyncio
    async def test_block_mutations_returns_405(self) -> None:
        """block_mutations returns 405 JSONResponse."""
        from app.routes.audit_logs import block_mutations

        user = MagicMock()
        response = await block_mutations(_user=user)
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_block_mutations_body(self) -> None:
        """block_mutations returns proper error envelope."""
        from app.routes.audit_logs import block_mutations
        import json

        user = MagicMock()
        response = await block_mutations(_user=user)
        body = json.loads(response.body)
        assert body["data"] is None
        assert body["errors"][0]["code"] == "METHOD_NOT_ALLOWED"
        assert "immutable" in body["errors"][0]["message"].lower()


# ── Record audit helper tests ───────────────────────────────────────

class TestRecordAudit:
    """_record_audit persists entries without raising."""

    @pytest.mark.asyncio
    async def test_record_audit_success(self) -> None:
        """_record_audit creates an entry in a new session."""
        from app.middleware.audit_middleware import _record_audit

        mock_session = AsyncMock()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.database.async_session_factory", mock_factory):
            await _record_audit(
                actor_id=uuid4(),
                action="agent.created",
                resource_type="agents",
                resource_id=uuid4(),
                details={"status_code": 201},
            )
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_audit_failure_does_not_raise(self) -> None:
        """_record_audit swallows exceptions (fire-and-forget)."""
        from app.middleware.audit_middleware import _record_audit

        with patch(
            "app.database.async_session_factory",
            side_effect=Exception("db down"),
        ):
            # Should not raise
            await _record_audit(
                actor_id=uuid4(),
                action="agent.created",
                resource_type="agents",
                resource_id=uuid4(),
            )
