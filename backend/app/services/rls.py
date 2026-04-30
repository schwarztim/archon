"""Postgres Row-Level-Security helpers for tenant isolation.

Phase 4 / WS12 — DB-level tenant isolation.

The ``0002_add_router_cost_dlp_tables`` migration enables RLS on every
tenant-scoped table with the policy::

    CREATE POLICY tenant_isolation ON <table>
        USING (tenant_id::text = current_setting('app.tenant_id', true))

This module is the runtime side of that contract: it sets
``app.tenant_id`` on each acquired connection so the policy actually
filters reads/writes for the current request.

Behaviour by backend
--------------------
* **Postgres**: ``SET LOCAL app.tenant_id = '<uuid>'`` — scoped to the
  transaction. ``SET LOCAL`` is required (not plain ``SET``) so the
  setting does not leak to other sessions sharing the connection
  through pgbouncer / the SQLAlchemy pool.
* **SQLite**: no-op. SQLite has no RLS; tests rely on application-level
  filters (``WHERE tenant_id = :tid``) for the same protection.

The helper is idempotent and safe to call multiple times per session;
``apply_tenant_session`` only emits SQL when a real Postgres connection
is available.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────


def _is_postgres(session: AsyncSession) -> bool:
    """Return ``True`` if the session's bind is a Postgres engine.

    Looks at the SQLAlchemy bind's dialect rather than the URL string so
    we get the right answer for forks / clones of the engine.
    """
    bind = session.get_bind()
    if bind is None:
        return False
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", "") if dialect else ""
    return name == "postgresql"


# ── Public API ────────────────────────────────────────────────────────


async def apply_tenant_session(
    session: AsyncSession, tenant_id: UUID | str | None,
) -> None:
    """Bind ``app.tenant_id`` for the current Postgres transaction.

    No-op on SQLite. No-op when ``tenant_id`` is ``None`` — leaving
    ``app.tenant_id`` unset means RLS evaluates ``current_setting`` to
    ``NULL`` and the ``USING`` clause yields ``NULL`` (treated as false
    by Postgres), so no rows match. That is the correct fail-closed
    behaviour for unauthenticated probes that accidentally reach a
    tenant-scoped table.

    Args:
        session: The SQLModel async session whose underlying connection
            should receive the ``SET LOCAL``.
        tenant_id: The tenant whose data the session may see. May be a
            ``UUID`` instance, a string in UUID form, or ``None``.
    """
    if not _is_postgres(session):
        return
    if tenant_id is None:
        return
    tid_str = str(tenant_id)
    await session.execute(
        text("SET LOCAL app.tenant_id = :tid"),
        {"tid": tid_str},
    )
    logger.debug("rls.apply_tenant_session: app.tenant_id=%s", tid_str)


async def clear_tenant_session(session: AsyncSession) -> None:
    """Reset ``app.tenant_id`` to NULL for the current transaction.

    Useful when a long-lived session changes tenant mid-flight (rare —
    typically a new session is preferred). No-op on SQLite.
    """
    if not _is_postgres(session):
        return
    await session.execute(text("SET LOCAL app.tenant_id = DEFAULT"))
    logger.debug("rls.clear_tenant_session: app.tenant_id reset")


async def assert_isolation(
    session: AsyncSession,
    *,
    model: Any,
    tenant_id_a: UUID,
    tenant_id_b: UUID,
) -> None:
    """Verify that rows written under tenant A are invisible to tenant B.

    Test helper. Inserts no data — assumes the caller has populated the
    table for tenant A. Switches the session's bound tenant to B,
    executes ``SELECT * FROM model WHERE tenant_id = tenant_id_a``, and
    asserts no rows come back.

    On Postgres this exercises both the application filter and the RLS
    policy. On SQLite only the application filter is exercised
    (``apply_tenant_session`` is a no-op).

    Args:
        session: An active session bound to tenant A initially.
        model: The SQLModel class to query. Must have a ``tenant_id``
            column.
        tenant_id_a: Tenant whose data should be hidden.
        tenant_id_b: Tenant whose context will be applied for the test.

    Raises:
        AssertionError: if any row written under tenant A is visible
            after switching to tenant B.
    """
    from sqlalchemy import select  # noqa: PLC0415  -- localised to avoid hard import

    # Switch session to tenant B before querying.
    await apply_tenant_session(session, tenant_id_b)

    stmt = select(model).where(model.tenant_id == tenant_id_a)
    result = await session.exec(stmt) if hasattr(session, "exec") else await session.execute(stmt)
    rows = result.all()

    if rows:
        raise AssertionError(
            f"tenant isolation breach: {len(rows)} rows belonging to "
            f"tenant_id_a={tenant_id_a} were visible while session was "
            f"scoped to tenant_id_b={tenant_id_b}"
        )


__all__ = [
    "apply_tenant_session",
    "assert_isolation",
    "clear_tenant_session",
]
