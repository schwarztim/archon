"""Unit tests for AuditService — tamper-evident hash-chain audit logging.

Tests cover:
- _compute_hash determinism and uniqueness
- log_action persists entry with correct hash chain linkage
- log_action with optional fields (None actor, no resource, no details)
- verify_chain returns valid for empty tenant
- verify_chain returns valid for a correctly-linked chain
- verify_chain detects prev_hash mismatch (tampered chain)
- verify_chain detects hash mismatch (tampered entry)
- verify_chain reports all errors, not just the first
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.audit_service import AuditService, _compute_hash
from app.models import AuditLog


# ── Fixed IDs ───────────────────────────────────────────────────────

TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
ACTOR_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NOW = datetime(2025, 6, 1, 12, 0, 0)


# ── Helpers ─────────────────────────────────────────────────────────


def _mock_session(prev_hash: str = "genesis") -> AsyncMock:
    """Create a mock AsyncSession that returns a scalar prev_hash."""
    session = AsyncMock()
    session.add = MagicMock()

    # scalar() simulates the hash query result
    scalar_result = MagicMock()
    scalar_result.scalar = MagicMock(return_value=prev_hash)
    session.execute = AsyncMock(return_value=scalar_result)
    return session


def _make_audit_log(
    *,
    tenant_id: str = TENANT_A,
    action: str = "GET /api/v1/agents",
    hash: str = "abc123",
    prev_hash: str = "genesis",
    actor_id: UUID | None = ACTOR_ID,
    resource_type: str | None = "agent",
    resource_id: str | None = "res-1",
    status_code: int | None = 200,
    ip_address: str | None = "127.0.0.1",
    user_agent: str | None = "pytest",
    created_at: datetime = NOW,
) -> AuditLog:
    return AuditLog(
        id=uuid4(),
        tenant_id=tenant_id,
        correlation_id=str(uuid4()),
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status_code=status_code,
        ip_address=ip_address,
        user_agent=user_agent,
        details=None,
        hash=hash,
        prev_hash=prev_hash,
        created_at=created_at,
    )


# ═══════════════════════════════════════════════════════════════════
# _compute_hash
# ═══════════════════════════════════════════════════════════════════


def test_compute_hash_is_deterministic() -> None:
    """Same inputs produce the same SHA-256 hash."""
    data = {"action": "create", "resource": "agent"}
    h1 = _compute_hash("genesis", data)
    h2 = _compute_hash("genesis", data)
    assert h1 == h2


def test_compute_hash_returns_hex_string() -> None:
    """_compute_hash returns a lowercase hex string."""
    h = _compute_hash("genesis", {"key": "value"})
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256 produces 64 hex chars
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_hash_different_prev_hash_gives_different_result() -> None:
    """Different prev_hash values produce different hashes."""
    data = {"action": "create"}
    h1 = _compute_hash("genesis", data)
    h2 = _compute_hash("some-other-hash", data)
    assert h1 != h2


def test_compute_hash_different_entry_data_gives_different_result() -> None:
    """Different entry_data produces different hashes."""
    h1 = _compute_hash("genesis", {"action": "create"})
    h2 = _compute_hash("genesis", {"action": "delete"})
    assert h1 != h2


def test_compute_hash_matches_manual_computation() -> None:
    """_compute_hash output matches a manually computed SHA-256."""
    prev = "genesis"
    data = {"action": "test", "tenant_id": "t1"}
    content = json.dumps(data, sort_keys=True, default=str)
    expected = hashlib.sha256(f"{prev}{content}".encode()).hexdigest()
    assert _compute_hash(prev, data) == expected


def test_compute_hash_handles_none_values() -> None:
    """_compute_hash serialises None values without raising."""
    h = _compute_hash("genesis", {"actor_id": None, "resource": None})
    assert isinstance(h, str)
    assert len(h) == 64


# ═══════════════════════════════════════════════════════════════════
# AuditService.log_action
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_log_action_returns_audit_log() -> None:
    """log_action returns an AuditLog instance."""
    session = _mock_session()
    session.refresh = AsyncMock()

    result = await AuditService.log_action(
        session=session,
        tenant_id=TENANT_A,
        correlation_id="corr-1",
        actor_id=ACTOR_ID,
        action="POST /api/v1/agents",
    )

    assert isinstance(result, AuditLog)
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_action_sets_prev_hash_from_db() -> None:
    """log_action reads the previous chain hash from the DB."""
    prev = "000abc"
    session = _mock_session(prev_hash=prev)
    session.refresh = AsyncMock()

    result = await AuditService.log_action(
        session=session,
        tenant_id=TENANT_A,
        correlation_id="corr-2",
        actor_id=None,
        action="GET /api/v1/agents",
    )

    assert result.prev_hash == prev


@pytest.mark.asyncio
async def test_log_action_uses_genesis_when_no_previous_hash() -> None:
    """log_action defaults prev_hash to 'genesis' for the first entry."""
    session = _mock_session(prev_hash=None)  # scalar() returns None
    session.execute = AsyncMock(
        return_value=MagicMock(scalar=MagicMock(return_value=None))
    )
    session.refresh = AsyncMock()

    result = await AuditService.log_action(
        session=session,
        tenant_id=TENANT_A,
        correlation_id="corr-3",
        actor_id=ACTOR_ID,
        action="POST /api/v1/users",
    )

    assert result.prev_hash == "genesis"


@pytest.mark.asyncio
async def test_log_action_hash_is_non_empty() -> None:
    """log_action computes and stores a non-empty hash."""
    session = _mock_session()
    session.refresh = AsyncMock()

    result = await AuditService.log_action(
        session=session,
        tenant_id=TENANT_A,
        correlation_id="corr-4",
        actor_id=ACTOR_ID,
        action="DELETE /api/v1/agents/123",
    )

    assert result.hash
    assert len(result.hash) == 64


@pytest.mark.asyncio
async def test_log_action_preserves_optional_fields() -> None:
    """log_action stores optional fields (resource_type, details, etc.)."""
    session = _mock_session()
    session.refresh = AsyncMock()

    result = await AuditService.log_action(
        session=session,
        tenant_id=TENANT_B,
        correlation_id="corr-5",
        actor_id=ACTOR_ID,
        action="PATCH /api/v1/agents/456",
        resource_type="agent",
        resource_id="456",
        status_code=200,
        ip_address="10.0.0.1",
        user_agent="Mozilla/5.0",
        details={"name": "updated"},
    )

    assert result.resource_type == "agent"
    assert result.resource_id == "456"
    assert result.status_code == 200
    assert result.ip_address == "10.0.0.1"
    assert result.details == {"name": "updated"}


@pytest.mark.asyncio
async def test_log_action_with_null_actor_id() -> None:
    """log_action handles actor_id=None for system/anonymous calls."""
    session = _mock_session()
    session.refresh = AsyncMock()

    result = await AuditService.log_action(
        session=session,
        tenant_id=TENANT_A,
        correlation_id="corr-6",
        actor_id=None,
        action="SYSTEM /startup",
    )

    assert result.actor_id is None
    assert isinstance(result, AuditLog)


# ═══════════════════════════════════════════════════════════════════
# AuditService.verify_chain
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_verify_chain_empty_tenant_is_valid() -> None:
    """An empty tenant has a valid (trivially intact) chain."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result_mock)

    result = await AuditService.verify_chain(session=session, tenant_id=TENANT_A)

    assert result["valid"] is True
    assert result["entries"] == 0
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_verify_chain_single_valid_entry() -> None:
    """A single correctly-hashed entry passes verification."""
    # Build an entry with explicit, known field values so the hash can be
    # reproduced exactly the same way verify_chain will recompute it.
    entry = _make_audit_log(
        hash="placeholder",
        prev_hash="genesis",
        action="GET /health",
        actor_id=ACTOR_ID,
        resource_type=None,
        resource_id=None,
        status_code=200,
        ip_address=None,
        user_agent=None,
    )
    entry.correlation_id = "corr-1"

    # entry_data must match exactly what verify_chain uses to recompute the hash
    entry_data = {
        "tenant_id": entry.tenant_id,
        "correlation_id": entry.correlation_id,
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "status_code": entry.status_code,
        "ip_address": entry.ip_address,
        "user_agent": entry.user_agent,
        "created_at": entry.created_at.isoformat(),
    }
    entry.hash = _compute_hash("genesis", entry_data)

    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [entry]
    session.execute = AsyncMock(return_value=result_mock)

    result = await AuditService.verify_chain(session=session, tenant_id=TENANT_A)

    assert result["entries"] == 1
    assert result["errors"] == []
    assert result["valid"] is True


@pytest.mark.asyncio
async def test_verify_chain_detects_prev_hash_mismatch() -> None:
    """verify_chain flags an entry whose prev_hash doesn't match the chain."""
    entry = _make_audit_log(hash="real-hash", prev_hash="wrong-prev-hash")

    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [entry]
    session.execute = AsyncMock(return_value=result_mock)

    result = await AuditService.verify_chain(session=session, tenant_id=TENANT_A)

    assert result["valid"] is False
    assert len(result["errors"]) >= 1
    error = result["errors"][0]
    assert "prev_hash" in error["error"]


@pytest.mark.asyncio
async def test_verify_chain_detects_hash_tampering() -> None:
    """verify_chain flags an entry whose hash doesn't match the recomputed value."""
    # Entry with correct prev_hash but wrong hash (tampered data)
    entry = _make_audit_log(hash="tampered-hash", prev_hash="genesis")

    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [entry]
    session.execute = AsyncMock(return_value=result_mock)

    result = await AuditService.verify_chain(session=session, tenant_id=TENANT_A)

    assert result["valid"] is False
    assert any("hash mismatch" in e["error"] for e in result["errors"])


@pytest.mark.asyncio
async def test_verify_chain_reports_entry_count() -> None:
    """verify_chain returns the correct total entry count."""
    entries = [
        _make_audit_log(hash=f"h{i}", prev_hash="genesis" if i == 0 else f"h{i - 1}")
        for i in range(3)
    ]

    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = entries
    session.execute = AsyncMock(return_value=result_mock)

    result = await AuditService.verify_chain(session=session, tenant_id=TENANT_A)

    assert result["entries"] == 3
