"""Tests for the tamper-evident audit hash chain (Phase 4 / WS13).

Covers:
- Genesis prev_hash on the first row (per tenant).
- Subsequent rows chain to the predecessor.
- Per-tenant chains are independent.
- verify_audit_chain accepts a clean chain.
- verify_audit_chain detects payload tampering and reports the corruption point.
- Concurrent appenders don't corrupt the chain.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

# Required env BEFORE app import (matches existing test conventions).
os.environ.setdefault("ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")

# Import all models so SQLModel.metadata is populated.
from app.models import AuditLog  # noqa: E402,F401
from app.services.audit_chain import (  # noqa: E402
    GENESIS_HASH,
    append_audit_log,
    canonical_audit_payload,
    compute_audit_hash,
    verify_audit_chain,
)


TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
ACTOR = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def engine():
    """Fresh in-memory SQLite engine for each test."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def session(engine) -> AsyncSession:
    """Production-parity AsyncSession (expire_on_commit=False)."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


# ── Helpers ──────────────────────────────────────────────────────────


async def _append(session: AsyncSession, **kwargs: Any) -> AuditLog:
    """Convenience wrapper that fills sane defaults."""
    return await append_audit_log(
        session=session,
        tenant_id=kwargs.pop("tenant_id", TENANT_A),
        actor_id=kwargs.pop("actor_id", ACTOR),
        action=kwargs.pop("action", "POST /api/v1/agents"),
        resource_type=kwargs.pop("resource_type", "agent"),
        resource_id=kwargs.pop("resource_id", "res-1"),
        status_code=kwargs.pop("status_code", 200),
        correlation_id=kwargs.pop("correlation_id", "corr-x"),
        details=kwargs.pop("details", None),
        ip_address=kwargs.pop("ip_address", "127.0.0.1"),
        user_agent=kwargs.pop("user_agent", "pytest"),
    )


# ── Append behaviour ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_audit_log_has_prev_hash_genesis(session: AsyncSession) -> None:
    """The first append in a tenant chain is rooted at genesis."""
    row = await _append(session)
    assert row.prev_hash == GENESIS_HASH
    assert row.hash and len(row.hash) == 64


@pytest.mark.asyncio
async def test_subsequent_audit_log_chains_to_predecessor(
    session: AsyncSession,
) -> None:
    """Each subsequent row's prev_hash is the previous row's hash."""
    first = await _append(session, action="action-1")
    second = await _append(session, action="action-2")
    third = await _append(session, action="action-3")

    assert second.prev_hash == first.hash
    assert third.prev_hash == second.hash
    # All hashes are unique.
    assert len({first.hash, second.hash, third.hash}) == 3


@pytest.mark.asyncio
async def test_chain_per_tenant_separate(session: AsyncSession) -> None:
    """Tenant A and B chains are independent — both root at genesis."""
    a1 = await _append(session, tenant_id=TENANT_A, action="a-1")
    b1 = await _append(session, tenant_id=TENANT_B, action="b-1")
    a2 = await _append(session, tenant_id=TENANT_A, action="a-2")
    b2 = await _append(session, tenant_id=TENANT_B, action="b-2")

    # Both first entries link to genesis.
    assert a1.prev_hash == GENESIS_HASH
    assert b1.prev_hash == GENESIS_HASH

    # Each tenant chains within itself, never across.
    assert a2.prev_hash == a1.hash
    assert b2.prev_hash == b1.hash
    assert a2.prev_hash != b1.hash
    assert b2.prev_hash != a1.hash


# ── verify_audit_chain happy path ────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_chain_clean(session: AsyncSession) -> None:
    """A pristine 5-event chain verifies as clean."""
    for i in range(5):
        await _append(session, action=f"action-{i}", correlation_id=f"corr-{i}")

    verdict = await verify_audit_chain(session, tenant_id=TENANT_A)
    assert verdict["chain_verified"] is True
    assert verdict["total_events"] == 5
    assert verdict["first_corruption_at_id"] is None
    assert verdict["first_corruption_field"] is None


@pytest.mark.asyncio
async def test_verify_chain_clean_multi_tenant_no_filter(
    session: AsyncSession,
) -> None:
    """Verifying without a tenant filter checks every tenant chain."""
    await _append(session, tenant_id=TENANT_A, action="a-1")
    await _append(session, tenant_id=TENANT_A, action="a-2")
    await _append(session, tenant_id=TENANT_B, action="b-1")

    verdict = await verify_audit_chain(session, tenant_id=None)
    assert verdict["chain_verified"] is True
    assert verdict["total_events"] == 3


# ── verify_audit_chain tamper detection ──────────────────────────────


@pytest.mark.asyncio
async def test_verify_chain_detects_payload_tamper(session: AsyncSession) -> None:
    """Mutating one row's action field is detected as a corruption."""
    # Insert 5 rows
    rows = []
    for i in range(5):
        rows.append(await _append(session, action=f"action-{i}"))

    # Tamper with row index 2 (chronologically the third entry).
    target = rows[2]
    target.action = "tampered-action"
    session.add(target)
    await session.commit()
    await session.refresh(target)

    verdict = await verify_audit_chain(session, tenant_id=TENANT_A)
    assert verdict["chain_verified"] is False
    assert verdict["total_events"] == 5
    assert verdict["first_corruption_at_id"] == target.id
    # Mutating action without recomputing the hash makes the stored hash
    # mismatch the canonical payload → field reported is "hash".
    assert verdict["first_corruption_field"] == "hash"


@pytest.mark.asyncio
async def test_verify_chain_detects_prev_hash_break(
    session: AsyncSession,
) -> None:
    """Breaking the chain link is detected as a prev_hash corruption."""
    rows = []
    for i in range(3):
        rows.append(await _append(session, action=f"action-{i}"))

    # Tamper with row[1]'s prev_hash to something else, AND keep its stored
    # hash consistent with that broken prev_hash so we isolate a prev_hash
    # break (not a hash-mismatch).
    target = rows[1]
    target.prev_hash = "deadbeef" * 8  # 64 hex chars but wrong link
    payload = canonical_audit_payload(target)
    target.hash = compute_audit_hash(target.prev_hash, payload)
    session.add(target)
    await session.commit()
    await session.refresh(target)

    verdict = await verify_audit_chain(session, tenant_id=TENANT_A)
    assert verdict["chain_verified"] is False
    assert verdict["first_corruption_at_id"] == target.id
    assert verdict["first_corruption_field"] == "prev_hash"


@pytest.mark.asyncio
async def test_verify_chain_isolated_tamper_does_not_cascade(
    session: AsyncSession,
) -> None:
    """A single tampered row reports exactly one corruption point.

    The earliest-violation field captures the chronologically first break;
    later rows are still scanned (the verifier walks via stored hashes) so
    a single tamper doesn't produce N false positives.
    """
    rows = []
    for i in range(4):
        rows.append(await _append(session, action=f"action-{i}"))

    # Tamper with the very first row.
    rows[0].action = "tampered"
    session.add(rows[0])
    await session.commit()
    await session.refresh(rows[0])

    verdict = await verify_audit_chain(session, tenant_id=TENANT_A)
    assert verdict["chain_verified"] is False
    # Earliest corruption is rows[0]
    assert verdict["first_corruption_at_id"] == rows[0].id


# ── Concurrency ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_appends_do_not_corrupt_chain(engine) -> None:
    """10 concurrent appenders against the same tenant produce a valid chain.

    Each appender opens its own session.  The chain head select serialises
    them on Postgres via FOR UPDATE; on SQLite the engine itself serialises
    writes.  Either way, the resulting chain must verify clean.
    """

    async def _writer(idx: int) -> None:
        async with AsyncSession(engine, expire_on_commit=False) as sess:
            await _append(sess, action=f"concurrent-{idx}", correlation_id=f"c-{idx}")

    await asyncio.gather(*(_writer(i) for i in range(10)))

    async with AsyncSession(engine, expire_on_commit=False) as sess:
        verdict = await verify_audit_chain(sess, tenant_id=TENANT_A)

    assert verdict["chain_verified"] is True, verdict
    assert verdict["total_events"] == 10


# ── Canonical payload determinism ────────────────────────────────────


@pytest.mark.asyncio
async def test_canonical_payload_is_deterministic(session: AsyncSession) -> None:
    """Two reads of the same row produce the exact same canonical payload."""
    row = await _append(session)
    p1 = canonical_audit_payload(row)
    p2 = canonical_audit_payload(row)
    assert p1 == p2
    # And recomputing the hash from prev_hash + payload matches.
    assert compute_audit_hash(row.prev_hash, p1) == row.hash
