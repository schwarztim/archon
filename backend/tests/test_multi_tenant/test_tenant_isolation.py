"""Phase 4 / WS12 — tenant isolation tests.

Two layers of protection are exercised:

1. **Application-level filtering** (always, on SQLite + Postgres):
   queries that include ``WHERE tenant_id = :tid`` must not return rows
   belonging to other tenants. Verified by inserting rows for tenant A
   then asserting that ``SELECT ... WHERE tenant_id = B`` returns 0
   rows.

2. **Row-Level-Security** (Postgres only — skipped on SQLite):
   the ``tenant_isolation`` policy created by migration 0002 must hide
   tenant A's rows from a session that has ``app.tenant_id`` set to B.
   These tests run against a real Postgres database when
   ``ARCHON_TEST_POSTGRES_URL`` is configured; they are skipped
   otherwise.
"""

from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.rls import apply_tenant_session

# ── Fixed UUIDs ────────────────────────────────────────────────────────

TENANT_A = UUID("aa000001-0001-0001-0001-000000000001")
TENANT_B = UUID("bb000002-0002-0002-0002-000000000002")
USER_A = UUID("11000001-0001-0001-0001-000000000001")
USER_B = UUID("22000002-0002-0002-0002-000000000002")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ── Helpers ────────────────────────────────────────────────────────────


async def _make_sqlite():
    """Build an in-memory SQLite engine with all SQLModel tables created."""
    # Importing the models module registers the metadata.
    from app import models  # noqa: F401  -- registers SQLModel tables

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _pg_url() -> str | None:
    """Return the Postgres URL for RLS tests, or None to skip."""
    return os.getenv("ARCHON_TEST_POSTGRES_URL")


# ═══════════════════════════════════════════════════════════════════════
# Application-level isolation (SQLite + Postgres)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_workflow_runs_isolated_between_tenants_app_layer() -> None:
    """WHERE tenant_id = B must return 0 rows for a tenant-A run."""
    from app.models.workflow import Workflow, WorkflowRun

    engine, factory = await _make_sqlite()
    try:
        async with factory() as session:
            wf = Workflow(name="iso-wf", steps=[], graph_definition={})
            session.add(wf)
            await session.commit()
            await session.refresh(wf)

            run_a = WorkflowRun(
                id=uuid4(),
                workflow_id=wf.id,
                kind="workflow",
                tenant_id=TENANT_A,
                status="queued",
                definition_snapshot={"kind": "workflow", "steps": []},
            )
            session.add(run_a)
            await session.commit()

            # Tenant A sees its own row.
            stmt_a = select(WorkflowRun).where(WorkflowRun.tenant_id == TENANT_A)
            result_a = await session.exec(stmt_a)
            rows_a = result_a.all()
            assert len(rows_a) == 1

            # Tenant B sees nothing.
            stmt_b = select(WorkflowRun).where(WorkflowRun.tenant_id == TENANT_B)
            result_b = await session.exec(stmt_b)
            rows_b = result_b.all()
            assert len(rows_b) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agents_isolated_between_tenants() -> None:
    """Agents written for tenant A must be hidden behind a tenant-B filter."""
    from app.models import Agent, User

    engine, factory = await _make_sqlite()
    try:
        async with factory() as session:
            session.add(User(id=USER_A, email="a@example.com", name="Alice"))
            session.add(User(id=USER_B, email="b@example.com", name="Bob"))
            await session.commit()

            session.add(
                Agent(
                    id=uuid4(),
                    name="agent-A",
                    definition={"model": "gpt-4"},
                    owner_id=USER_A,
                    tenant_id=str(TENANT_A),
                )
            )
            session.add(
                Agent(
                    id=uuid4(),
                    name="agent-B",
                    definition={"model": "gpt-4"},
                    owner_id=USER_B,
                    tenant_id=str(TENANT_B),
                )
            )
            await session.commit()

            stmt_a = select(Agent).where(Agent.tenant_id == str(TENANT_A))
            result_a = await session.exec(stmt_a)
            rows_a = result_a.all()
            assert len(rows_a) == 1
            assert rows_a[0].name == "agent-A"

            stmt_b = select(Agent).where(Agent.tenant_id == str(TENANT_B))
            result_b = await session.exec(stmt_b)
            rows_b = result_b.all()
            assert len(rows_b) == 1
            assert rows_b[0].name == "agent-B"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cost_data_isolated_between_tenants() -> None:
    """TokenLedger entries are filtered by tenant_id."""
    from app.models.cost import TokenLedger

    engine, factory = await _make_sqlite()
    try:
        async with factory() as session:
            session.add(
                TokenLedger(
                    id=uuid4(),
                    tenant_id=str(TENANT_A),
                    provider="openai",
                    model_id="gpt-4o",
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                    total_cost=0.01,
                )
            )
            session.add(
                TokenLedger(
                    id=uuid4(),
                    tenant_id=str(TENANT_B),
                    provider="openai",
                    model_id="gpt-4o",
                    input_tokens=20,
                    output_tokens=8,
                    total_tokens=28,
                    total_cost=0.02,
                )
            )
            await session.commit()

            stmt_a = select(TokenLedger).where(
                TokenLedger.tenant_id == str(TENANT_A)
            )
            result_a = await session.exec(stmt_a)
            rows_a = result_a.all()
            assert len(rows_a) == 1
            assert rows_a[0].input_tokens == 10

            stmt_b = select(TokenLedger).where(
                TokenLedger.tenant_id == str(TENANT_B)
            )
            result_b = await session.exec(stmt_b)
            rows_b = result_b.all()
            assert len(rows_b) == 1
            assert rows_b[0].input_tokens == 20
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_secrets_isolated_between_tenants() -> None:
    """SecretRegistration rows are filtered by tenant_id (UUID)."""
    from app.models.secrets import SecretRegistration
    from app.models.tenancy import Tenant

    engine, factory = await _make_sqlite()
    try:
        async with factory() as session:
            # The SecretRegistration FK requires real Tenant rows.
            session.add(
                Tenant(
                    id=TENANT_A,
                    name="A",
                    slug="a",
                    tier="free",
                    status="active",
                    owner_email="a@example.com",
                    settings={},
                )
            )
            session.add(
                Tenant(
                    id=TENANT_B,
                    name="B",
                    slug="b",
                    tier="free",
                    status="active",
                    owner_email="b@example.com",
                    settings={},
                )
            )
            await session.commit()

            session.add(
                SecretRegistration(
                    id=uuid4(),
                    path="kv/a/secret",
                    tenant_id=TENANT_A,
                    secret_type="api_key",
                )
            )
            session.add(
                SecretRegistration(
                    id=uuid4(),
                    path="kv/b/secret",
                    tenant_id=TENANT_B,
                    secret_type="api_key",
                )
            )
            await session.commit()

            stmt_a = select(SecretRegistration).where(
                SecretRegistration.tenant_id == TENANT_A
            )
            result_a = await session.exec(stmt_a)
            rows_a = result_a.all()
            assert len(rows_a) == 1
            assert rows_a[0].path == "kv/a/secret"

            stmt_b = select(SecretRegistration).where(
                SecretRegistration.tenant_id == TENANT_B
            )
            result_b = await session.exec(stmt_b)
            rows_b = result_b.all()
            assert len(rows_b) == 1
            assert rows_b[0].path == "kv/b/secret"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_logs_isolated_between_tenants() -> None:
    """AuditLog entries are filtered by tenant_id (string column)."""
    from app.models import AuditLog

    engine, factory = await _make_sqlite()
    try:
        async with factory() as session:
            session.add(
                AuditLog(
                    id=uuid4(),
                    tenant_id=str(TENANT_A),
                    action="agent.create",
                    resource_type="agent",
                    hash="hash-a",
                    prev_hash="genesis",
                )
            )
            session.add(
                AuditLog(
                    id=uuid4(),
                    tenant_id=str(TENANT_B),
                    action="agent.delete",
                    resource_type="agent",
                    hash="hash-b",
                    prev_hash="genesis",
                )
            )
            await session.commit()

            stmt_a = select(AuditLog).where(AuditLog.tenant_id == str(TENANT_A))
            result_a = await session.exec(stmt_a)
            rows_a = result_a.all()
            assert len(rows_a) == 1
            assert rows_a[0].action == "agent.create"

            stmt_b = select(AuditLog).where(AuditLog.tenant_id == str(TENANT_B))
            result_b = await session.exec(stmt_b)
            rows_b = result_b.all()
            assert len(rows_b) == 1
            assert rows_b[0].action == "agent.delete"
    finally:
        await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════
# Postgres RLS — skipped unless ARCHON_TEST_POSTGRES_URL is set
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_postgres_rls_blocks_cross_tenant_select_when_session_scoped() -> None:
    """SET LOCAL app.tenant_id = B → tenant A's rows are invisible.

    Requires a Postgres database where migration 0002 has run (RLS
    policies enabled on token_ledger and friends). We use token_ledger
    because it has a string tenant_id column and matching RLS policy.
    """
    pg_url = _pg_url()
    if not pg_url:
        pytest.skip("ARCHON_TEST_POSTGRES_URL not set; skipping RLS test")

    engine = create_async_engine(pg_url, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    a_id = uuid4()
    b_id = uuid4()
    try:
        # ── Insert row under tenant A ─────────────────────────────────
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            await session.execute(
                text(
                    "INSERT INTO token_ledger "
                    "(id, tenant_id, provider, model_id, input_tokens, output_tokens, total_tokens, total_cost) "
                    "VALUES (:id, :tid, 'openai', 'gpt-4o', 10, 5, 15, 0.01)"
                ),
                {"id": str(a_id), "tid": str(TENANT_A)},
            )
            await session.commit()

        # ── Select under tenant B → 0 rows ────────────────────────────
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_B)
            result = await session.execute(
                text("SELECT id FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            rows = result.fetchall()
            assert len(rows) == 0, (
                f"RLS leak: tenant B saw tenant A's row {a_id}"
            )
            await session.rollback()

        # ── Select under tenant A → 1 row ─────────────────────────────
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            result = await session.execute(
                text("SELECT id FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            rows = result.fetchall()
            assert len(rows) == 1
            await session.rollback()

        # ── Cleanup (under tenant A) ──────────────────────────────────
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            await session.execute(
                text("DELETE FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_rls_blocks_cross_tenant_update() -> None:
    """A session scoped to tenant B must not be able to UPDATE tenant A's rows."""
    pg_url = _pg_url()
    if not pg_url:
        pytest.skip("ARCHON_TEST_POSTGRES_URL not set; skipping RLS test")

    engine = create_async_engine(pg_url, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    a_id = uuid4()
    try:
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            await session.execute(
                text(
                    "INSERT INTO token_ledger "
                    "(id, tenant_id, provider, model_id, input_tokens, output_tokens, total_tokens, total_cost) "
                    "VALUES (:id, :tid, 'openai', 'gpt-4o', 10, 5, 15, 0.01)"
                ),
                {"id": str(a_id), "tid": str(TENANT_A)},
            )
            await session.commit()

        # Attempt cross-tenant UPDATE
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_B)
            result = await session.execute(
                text(
                    "UPDATE token_ledger SET total_cost = 99.99 "
                    "WHERE id = :id"
                ),
                {"id": str(a_id)},
            )
            # Postgres reports rowcount==0 because RLS hid the row.
            assert result.rowcount == 0
            await session.commit()

        # Verify the value is unchanged when read back under tenant A.
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            result = await session.execute(
                text("SELECT total_cost FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            cost = result.scalar_one()
            assert float(cost) == pytest.approx(0.01)

            # Cleanup
            await session.execute(
                text("DELETE FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_rls_blocks_cross_tenant_delete() -> None:
    """A session scoped to tenant B must not be able to DELETE tenant A's rows."""
    pg_url = _pg_url()
    if not pg_url:
        pytest.skip("ARCHON_TEST_POSTGRES_URL not set; skipping RLS test")

    engine = create_async_engine(pg_url, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    a_id = uuid4()
    try:
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            await session.execute(
                text(
                    "INSERT INTO token_ledger "
                    "(id, tenant_id, provider, model_id, input_tokens, output_tokens, total_tokens, total_cost) "
                    "VALUES (:id, :tid, 'openai', 'gpt-4o', 10, 5, 15, 0.01)"
                ),
                {"id": str(a_id), "tid": str(TENANT_A)},
            )
            await session.commit()

        # Cross-tenant DELETE attempt
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_B)
            result = await session.execute(
                text("DELETE FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            assert result.rowcount == 0
            await session.commit()

        # Row still present under tenant A
        async with factory() as session:
            await session.begin()
            await apply_tenant_session(session, TENANT_A)
            result = await session.execute(
                text("SELECT id FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            assert len(result.fetchall()) == 1

            # Cleanup
            await session.execute(
                text("DELETE FROM token_ledger WHERE id = :id"),
                {"id": str(a_id)},
            )
            await session.commit()
    finally:
        await engine.dispose()
