"""Tenant isolation tests — W15a.

All tests use --noconftest pattern: inline SQLite, no conftest.py fixtures.
Tests verify:
  - cross-tenant read is blocked
  - cross-tenant write path raises TenantViolationError
  - missing resource is treated as a violation (fail-closed)
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from uuid import uuid4, UUID

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, Field, select


# ---------------------------------------------------------------------------
# Inline SQLite DB setup
# ---------------------------------------------------------------------------

_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_AsyncSession = sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)


# Minimal in-test model that has a tenant_id column.
class FakeRun(SQLModel, table=True):
    __tablename__ = "fake_runs_ti"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)
    name: str = Field(default="test-run")


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


class TestTenantGuardDirectly:
    """Test TenantViolationError and the model-resolution logic."""

    def test_tenant_violation_error_carries_fields(self):
        from app.services.tenant_guard import TenantViolationError

        tid = uuid4()
        rid = uuid4()
        owner = uuid4()
        exc = TenantViolationError(
            tenant_id=tid,
            resource_type="run",
            resource_id=rid,
            owner_tenant_id=owner,
        )
        assert str(tid) in str(exc)
        assert exc.resource_type == "run"
        assert exc.resource_id == rid
        assert exc.owner_tenant_id == owner

    def test_tenant_violation_error_without_owner(self):
        from app.services.tenant_guard import TenantViolationError

        exc = TenantViolationError(
            tenant_id=uuid4(),
            resource_type="task",
            resource_id=uuid4(),
        )
        assert exc.owner_tenant_id is None


@pytest.mark.asyncio
async def test_cross_tenant_read_blocked(session: AsyncSession):
    """A row belonging to tenant_A cannot be read by tenant_B."""
    from app.services.tenant_guard import (
        TenantViolationError,
        enforce_tenant_isolation,
    )

    tenant_a = uuid4()
    tenant_b = uuid4()
    run_id = uuid4()

    # Create a row owned by tenant_a.
    run = FakeRun(id=run_id, tenant_id=tenant_a)
    session.add(run)
    await session.commit()

    # Monkeypatch _resolve_model_class to return our FakeRun model.
    import app.services.tenant_guard as tg

    original = tg._resolve_model_class

    def patched(resource_type: str):
        if resource_type == "run":
            return FakeRun
        return original(resource_type)

    tg._resolve_model_class = patched
    try:
        with pytest.raises(TenantViolationError) as exc_info:
            await enforce_tenant_isolation(
                session,
                tenant_id=tenant_b,
                resource_type="run",
                resource_id=run_id,
            )
        assert exc_info.value.owner_tenant_id == tenant_a
    finally:
        tg._resolve_model_class = original


@pytest.mark.asyncio
async def test_cross_tenant_write_blocked(session: AsyncSession):
    """A row owned by a different tenant raises TenantViolationError."""
    from app.services.tenant_guard import (
        TenantViolationError,
        enforce_tenant_isolation,
    )

    owner = uuid4()
    requester = uuid4()
    run_id = uuid4()

    run = FakeRun(id=run_id, tenant_id=owner)
    session.add(run)
    await session.commit()

    import app.services.tenant_guard as tg

    original = tg._resolve_model_class

    def patched(rt):
        if rt == "run":
            return FakeRun
        return original(rt)

    tg._resolve_model_class = patched
    try:
        with pytest.raises(TenantViolationError):
            await enforce_tenant_isolation(
                session,
                tenant_id=requester,
                resource_type="run",
                resource_id=run_id,
            )
    finally:
        tg._resolve_model_class = original


@pytest.mark.asyncio
async def test_missing_resource_blocked_fail_closed(session: AsyncSession):
    """A resource that does not exist raises TenantViolationError (fail-closed)."""
    from app.services.tenant_guard import (
        TenantViolationError,
        enforce_tenant_isolation,
    )

    import app.services.tenant_guard as tg

    original = tg._resolve_model_class

    def patched(rt):
        if rt == "run":
            return FakeRun
        return original(rt)

    tg._resolve_model_class = patched
    try:
        with pytest.raises(TenantViolationError):
            await enforce_tenant_isolation(
                session,
                tenant_id=uuid4(),
                resource_type="run",
                resource_id=uuid4(),  # does not exist
            )
    finally:
        tg._resolve_model_class = original


@pytest.mark.asyncio
async def test_same_tenant_access_allowed(session: AsyncSession):
    """A row owned by the requesting tenant passes the guard with no exception."""
    from app.services.tenant_guard import enforce_tenant_isolation

    tenant = uuid4()
    run_id = uuid4()

    run = FakeRun(id=run_id, tenant_id=tenant)
    session.add(run)
    await session.commit()

    import app.services.tenant_guard as tg

    original = tg._resolve_model_class

    def patched(rt):
        if rt == "run":
            return FakeRun
        return original(rt)

    tg._resolve_model_class = patched
    try:
        # Must not raise.
        await enforce_tenant_isolation(
            session,
            tenant_id=tenant,
            resource_type="run",
            resource_id=run_id,
        )
    finally:
        tg._resolve_model_class = original


@pytest.mark.asyncio
async def test_resource_type_without_model_skips_check(session: AsyncSession):
    """Resource types with no direct model (signal, artifact) skip the DB check."""
    from app.services.tenant_guard import enforce_tenant_isolation

    # "signal" has no model — must not raise.
    await enforce_tenant_isolation(
        session,
        tenant_id=uuid4(),
        resource_type="signal",
        resource_id=uuid4(),
    )
