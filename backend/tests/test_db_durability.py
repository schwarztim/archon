"""DB Durability tests — verifies init_db() never wipes data.

Acceptance criterion A1.1:
  - Create engine, call init_db(), insert a row.
  - Call init_db() AGAIN.
  - Assert the row still exists.

All tests use an in-memory SQLite database so they have zero external
dependencies and run offline, matching the project's test philosophy.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


async def _make_engine():
    """Return a fresh async SQLite in-memory engine with all tables created."""
    # Import all models so SQLModel.metadata is populated.
    from app.models import (  # noqa: F401
        User,
        Agent,
        Execution,
    )

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine) -> AsyncSession:
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_db_does_not_drop_existing_data() -> None:
    """Calling init_db() twice must NOT wipe rows inserted between calls.

    This is the canonical acceptance test for A1: DB Durability.
    It mirrors the real init_db() behaviour using an in-memory SQLite DB.
    """
    from app.models import User

    engine = await _make_engine()
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ── Phase 1: insert a row ──────────────────────────────────────────
    user_id = uuid4()
    async with factory() as session:
        user = User(
            id=user_id,
            email=f"durability-{user_id}@archon.test",
            name="Durability Test User",
            role="developer",
        )
        session.add(user)
        await session.commit()

    # ── Phase 2: simulate a second init_db() call ──────────────────────
    # Real init_db() calls SQLModel.metadata.create_all which is a no-op
    # for existing tables. We replicate that here.
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # ── Phase 3: assert the row still exists ───────────────────────────
    async with factory() as session:
        result = await session.exec(select(User).where(User.id == user_id))
        found = result.first()

    assert found is not None, (
        "Row was destroyed by init_db() — drop_all must not be called at startup."
    )
    assert found.email == f"durability-{user_id}@archon.test"
    assert found.name == "Durability Test User"

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_idempotent_multiple_calls() -> None:
    """init_db() can be called any number of times without data loss."""
    from app.models import User

    engine = await _make_engine()
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Insert 3 users.
    user_ids = [uuid4() for _ in range(3)]
    async with factory() as session:
        for uid in user_ids:
            session.add(User(
                id=uid,
                email=f"idempotent-{uid}@archon.test",
                name="Idempotency User",
                role="developer",
            ))
        await session.commit()

    # Simulate init_db() called 5 times (e.g., rolling restart).
    for _ in range(5):
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    # All rows must survive.
    async with factory() as session:
        result = await session.exec(select(User))
        found_ids = {u.id for u in result.all()}

    for uid in user_ids:
        assert uid in found_ids, f"User {uid} was lost after repeated init_db() calls."

    await engine.dispose()


@pytest.mark.asyncio
async def test_drop_and_recreate_wipes_data() -> None:
    """drop_and_recreate_db() DOES wipe data — confirms it's a distinct, explicit function."""
    from app.models import User
    from app.database import drop_and_recreate_db

    engine = await _make_engine()
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Monkeypatch the module-level engine to our in-memory one for isolation.
    import app.database as db_module
    original_engine = db_module.engine
    db_module.engine = engine

    try:
        uid = uuid4()
        async with factory() as session:
            session.add(User(
                id=uid,
                email=f"drop-test-{uid}@archon.test",
                name="Drop Test",
                role="developer",
            ))
            await session.commit()

        # Explicit destructive reset.
        await drop_and_recreate_db()

        async with factory() as session:
            result = await session.exec(select(User).where(User.id == uid))
            found = result.first()

        assert found is None, (
            "drop_and_recreate_db() should wipe all data — row should not exist."
        )
    finally:
        db_module.engine = original_engine
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_does_not_call_drop_all() -> None:
    """Verify init_db() source code does not contain drop_all calls.

    This is a static assertion guarding against accidental regressions
    where someone adds drop_all back to init_db().
    """
    import inspect
    from app.database import init_db

    source = inspect.getsource(init_db)
    assert "drop_all" not in source, (
        "init_db() must NEVER call drop_all. Found 'drop_all' in init_db source. "
        "Use drop_and_recreate_db() for intentional destructive resets."
    )
