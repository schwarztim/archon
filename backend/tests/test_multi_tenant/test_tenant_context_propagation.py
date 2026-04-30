"""Phase 4 / WS12 — tenant context propagation across async boundaries.

The contextvar must:
  * persist through ``await`` chains within the same task
  * be reset cleanly by ``tenant_scope``
  * isolate concurrent tasks (each ``asyncio.gather`` participant sees
    only its own tenant)
  * apply ``SET LOCAL app.tenant_id`` on Postgres sessions when wired
    into ``get_session_with_tenant``
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import pytest

from app.services.tenant_context import (
    TenantContextRequired,
    get_current_tenant,
    require_tenant,
    reset_tenant,
    set_current_tenant,
    tenant_scope,
)

# ── Fixed UUIDs ────────────────────────────────────────────────────────

TENANT_A = UUID("aa000001-0001-0001-0001-000000000001")
TENANT_B = UUID("bb000002-0002-0002-0002-000000000002")
TENANT_C = UUID("cc000003-0003-0003-0003-000000000003")


# ── Single-task chain propagation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_set_current_tenant_persists_in_async_function_chain() -> None:
    """A tenant set at the top survives await-chains."""

    async def _inner() -> UUID:
        # Multiple awaits between set() and read()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return require_tenant()

    async def _middle() -> UUID:
        await asyncio.sleep(0)
        return await _inner()

    token = set_current_tenant(TENANT_A)
    try:
        result = await _middle()
        assert result == TENANT_A
    finally:
        reset_tenant(token)


@pytest.mark.asyncio
async def test_tenant_scope_context_manager_resets_on_exit() -> None:
    """tenant_scope cleans up even when the body raises."""
    assert get_current_tenant() is None

    async with tenant_scope(TENANT_A):
        assert get_current_tenant() == TENANT_A

    assert get_current_tenant() is None

    with pytest.raises(RuntimeError, match="boom"):
        async with tenant_scope(TENANT_B):
            assert get_current_tenant() == TENANT_B
            raise RuntimeError("boom")

    # Even after an exception, the tenant binding is restored.
    assert get_current_tenant() is None


@pytest.mark.asyncio
async def test_nested_tenant_scopes_unwind_correctly() -> None:
    """Inner scope shadows outer; outer is restored on exit."""
    async with tenant_scope(TENANT_A):
        assert require_tenant() == TENANT_A
        async with tenant_scope(TENANT_B):
            assert require_tenant() == TENANT_B
        assert require_tenant() == TENANT_A
    assert get_current_tenant() is None


# ── Concurrency isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_scope_isolates_concurrent_tasks() -> None:
    """Three concurrent tasks each see their own tenant.

    asyncio.gather runs the tasks on the same loop with independent
    context snapshots (taken at create_task time). If contextvars were
    leaking we would see one task observing another's tenant.
    """
    barrier = asyncio.Event()
    observations: dict[UUID, UUID | None] = {}

    async def _task(tid: UUID) -> None:
        async with tenant_scope(tid):
            # Force interleaving to make accidental leaks visible.
            await asyncio.sleep(0)
            await barrier.wait()
            await asyncio.sleep(0)
            observations[tid] = require_tenant()

    runners = [
        asyncio.create_task(_task(TENANT_A)),
        asyncio.create_task(_task(TENANT_B)),
        asyncio.create_task(_task(TENANT_C)),
    ]
    # Let each task hit the barrier wait, then release them all together.
    await asyncio.sleep(0.01)
    barrier.set()
    await asyncio.gather(*runners)

    assert observations == {
        TENANT_A: TENANT_A,
        TENANT_B: TENANT_B,
        TENANT_C: TENANT_C,
    }


@pytest.mark.asyncio
async def test_outer_task_unaffected_by_subtask_changes() -> None:
    """Mutations inside an awaited subtask should not bleed to the outer task."""

    async def _subtask() -> None:
        # Create_task captures a snapshot, so set() inside doesn't propagate
        # back to the outer task (this is the asyncio contract we rely on).
        async with tenant_scope(TENANT_B):
            assert require_tenant() == TENANT_B

    async with tenant_scope(TENANT_A):
        assert require_tenant() == TENANT_A
        await asyncio.create_task(_subtask())
        assert require_tenant() == TENANT_A


# ── DB binding ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_with_tenant_yields_session_on_sqlite() -> None:
    """get_session_with_tenant wires the contextvar tenant onto a SQLite session.

    The global engine is configured for Postgres by default, so we
    monkeypatch ``async_session_factory`` with an in-memory SQLite
    factory for this test. The contract we verify is that the
    dependency reads the contextvar and applies tenant scoping (no-op
    on SQLite, since ``apply_tenant_session`` short-circuits on
    non-Postgres engines).
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    import app.database as db_mod

    # Build an isolated SQLite engine just for this test.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    original_factory = db_mod.async_session_factory
    db_mod.async_session_factory = factory  # type: ignore[assignment]

    try:
        async with tenant_scope(TENANT_A):
            gen = db_mod.get_session_with_tenant()
            session = await gen.__anext__()
            assert session is not None
            # SET LOCAL is a no-op on SQLite, so no exception.
            assert get_current_tenant() == TENANT_A
            try:
                await gen.__anext__()
            except StopAsyncIteration:
                pass
    finally:
        db_mod.async_session_factory = original_factory  # type: ignore[assignment]
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_session_with_tenant_applies_set_local_on_postgres() -> None:
    """When a real Postgres URL is configured, SET LOCAL fires.

    Skipped unless ARCHON_TEST_POSTGRES_URL is set — most CI runs use
    SQLite. We exercise apply_tenant_session directly against a fresh
    Postgres engine to keep the test independent of the global one.
    """
    pg_url = os.getenv("ARCHON_TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("ARCHON_TEST_POSTGRES_URL not set; skipping Postgres test")

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.rls import apply_tenant_session

    engine = create_async_engine(pg_url, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            result = await session.execute(
                text("SELECT current_setting('app.tenant_id', true)")
            )
            row = result.scalar_one()
            assert str(row) == str(TENANT_A)
            await session.rollback()
    finally:
        await engine.dispose()


# ── Strict-mode + ContextVar interplay ────────────────────────────────


@pytest.mark.asyncio
async def test_require_tenant_inside_unbound_task_raises() -> None:
    """A task with no tenant scope must raise if it touches require_tenant()."""

    async def _orphan() -> None:
        require_tenant()

    with pytest.raises(TenantContextRequired):
        await asyncio.create_task(_orphan())
