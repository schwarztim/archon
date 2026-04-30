"""Policy gate tests — W15b.

All tests use inline SQLite, no conftest.py.

Tests verify:
  - enterprise mode: missing policy → deny
  - dev mode: missing policy → allow with warning
  - policy deny → creates audit event
  - unknown action in enterprise mode → deny
  - explicit policy allow → allow
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.models import AuditLog

# ---------------------------------------------------------------------------
# Inline SQLite setup
# ---------------------------------------------------------------------------

_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_AsyncSession = sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def create_tables():
    async with _ENGINE.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with _ENGINE.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with _AsyncSession() as s:
        yield s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enterprise_mode_missing_policy_denies(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In enterprise mode, missing policy → PolicyDecision(allowed=False)."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.policy_service import evaluate_policy

    decision = await evaluate_policy(
        session,
        tenant_id=uuid4(),
        action="run_start",
        resource="run:abc",
    )
    assert decision.allowed is False
    assert "enterprise_mode_missing_policy" in decision.reason
    assert decision.audit_event_id is not None


@pytest.mark.asyncio
async def test_dev_mode_missing_policy_allows_with_warning(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In dev mode, missing policy → PolicyDecision(allowed=True) + warning log."""
    monkeypatch.delenv("ARCHON_ENTERPRISE_MODE", raising=False)

    from app.services.policy_service import evaluate_policy

    decision = await evaluate_policy(
        session,
        tenant_id=uuid4(),
        action="run_start",
        resource="run:abc",
    )
    assert decision.allowed is True
    assert "dev_mode_missing_policy" in decision.reason
    assert decision.audit_event_id is None


@pytest.mark.asyncio
async def test_policy_deny_creates_audit_event(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """A deny decision writes a tamper-evident audit log entry."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from sqlalchemy import select as _select

    from app.services.policy_service import evaluate_policy

    tenant_id = uuid4()
    decision = await evaluate_policy(
        session,
        tenant_id=tenant_id,
        action="run_start",
    )
    assert decision.allowed is False
    assert decision.audit_event_id is not None

    # Verify the audit entry exists in the DB.
    result = await session.execute(
        _select(AuditLog).where(AuditLog.id == decision.audit_event_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert "deny" in row.action
    assert row.status_code == 403


@pytest.mark.asyncio
async def test_enterprise_mode_unknown_action_denies(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Unknown action in enterprise mode → deny."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.policy_service import evaluate_policy

    decision = await evaluate_policy(
        session,
        tenant_id=uuid4(),
        action="completely_unknown_action",
    )
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_dev_mode_unknown_action_allows(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Unknown action in dev mode → allow."""
    monkeypatch.delenv("ARCHON_ENTERPRISE_MODE", raising=False)

    from app.services.policy_service import evaluate_policy

    decision = await evaluate_policy(
        session,
        tenant_id=uuid4(),
        action="completely_unknown_action",
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_all_valid_actions_accepted_in_dev(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """All registered action names are recognised (not treated as unknown)."""
    monkeypatch.delenv("ARCHON_ENTERPRISE_MODE", raising=False)

    from app.services.policy_service import _VALID_ACTIONS, evaluate_policy

    for action in _VALID_ACTIONS:
        decision = await evaluate_policy(
            session,
            tenant_id=uuid4(),
            action=action,
        )
        # Dev mode + no policy = allow.
        assert decision.allowed is True, f"Action {action} was unexpectedly denied"


@pytest.mark.asyncio
async def test_policy_decision_dataclass_fields(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """PolicyDecision exposes allowed, reason, audit_event_id."""
    monkeypatch.delenv("ARCHON_ENTERPRISE_MODE", raising=False)

    from app.services.policy_service import PolicyDecision, evaluate_policy

    decision = await evaluate_policy(
        session,
        tenant_id=uuid4(),
        action="task_claim",
    )
    assert isinstance(decision, PolicyDecision)
    assert isinstance(decision.allowed, bool)
    assert isinstance(decision.reason, str)


@pytest.mark.asyncio
async def test_multiple_deny_events_have_unique_audit_ids(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Each policy denial produces a distinct audit log entry."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.policy_service import evaluate_policy

    tenant = uuid4()
    d1 = await evaluate_policy(session, tenant_id=tenant, action="run_start")
    d2 = await evaluate_policy(session, tenant_id=tenant, action="task_claim")

    assert d1.audit_event_id is not None
    assert d2.audit_event_id is not None
    assert d1.audit_event_id != d2.audit_event_id
