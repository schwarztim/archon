"""Async database engine and session management for Archon."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

# SQLite (used in tests + local dev) does not support pool_size / max_overflow
# — the StaticPool implementation rejects those kwargs. Apply pool tuning only
# for non-SQLite backends. Production (Postgres) gets the full 20+10 pool.
_engine_kwargs: dict = {"echo": False}
if not settings.DATABASE_URL.startswith(("sqlite", "sqlite+")):
    _engine_kwargs.update(pool_size=20, max_overflow=10, pool_pre_ping=True)

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for FastAPI dependency injection."""
    async with async_session_factory() as session:
        yield session


async def get_session_with_tenant() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session pre-bound to the current tenant context.

    Phase 4 / WS12 — DB-level tenant isolation.

    Same dependency contract as :func:`get_session` but applies the
    Postgres ``SET LOCAL app.tenant_id`` for RLS enforcement before
    yielding control to the route. The contextvar is read via
    :func:`app.services.tenant_context.get_current_tenant`; it is set
    upstream by ``TenantMiddleware`` on every authenticated request.

    On SQLite this is functionally identical to ``get_session`` —
    ``apply_tenant_session`` is a no-op for non-Postgres engines, so
    tests using in-memory SQLite still pass while production gains the
    full RLS guarantee.

    If no tenant context is bound, the session is yielded with no
    ``app.tenant_id`` set; RLS policies then evaluate
    ``current_setting('app.tenant_id', true)`` to NULL and the policy's
    ``USING`` clause hides all rows. The route should reject the
    request via :func:`require_tenant` before issuing queries.
    """
    # Local imports avoid a circular dependency between this module and
    # ``app.services``; database.py is imported very early during app
    # startup, before the services package is fully resolved.
    from app.services.rls import apply_tenant_session  # noqa: PLC0415
    from app.services.tenant_context import get_current_tenant  # noqa: PLC0415

    async with async_session_factory() as session:
        tid = get_current_tenant()
        await apply_tenant_session(session, tid)
        if tid is None:
            logger.debug(
                "get_session_with_tenant: no tenant context bound; "
                "RLS will fail-closed for tenant-scoped tables"
            )
        yield session


async def init_db() -> None:
    """Initialize the database safely — creates tables if they do not exist.

    This function NEVER drops existing tables or data. It is safe to call on
    every application startup. For schema migrations, use Alembic:

        alembic upgrade head

    If the environment variable ARCHON_AUTO_MIGRATE=true, this function will
    attempt to run ``alembic upgrade head`` via subprocess instead of using
    SQLModel.metadata.create_all. This is opt-in and off by default.
    """
    if os.environ.get("ARCHON_AUTO_MIGRATE", "").lower() == "true":
        import subprocess  # noqa: PLC0415

        result = subprocess.run(  # noqa: S603
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"alembic upgrade head failed:\n{result.stderr}"
            )
        return

    # Default: create tables that are missing, leave existing ones untouched.
    # This is NOT a replacement for Alembic — it only adds new tables, never
    # drops or alters columns. Run `make migrate-up` for full schema management.
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def drop_and_recreate_db() -> None:
    """DESTRUCTIVE: drop all tables then recreate them from SQLModel metadata.

    This wipes ALL data. Intended only for the `make db-reset` target and
    local development teardown. NEVER call this from application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)


# Legacy alias kept for any callers that have not been updated yet.
# Marked for removal once all call sites migrate to init_db().
async def create_db_and_tables() -> None:
    """Deprecated: use init_db() instead. Retained for backward compatibility."""
    await init_db()
