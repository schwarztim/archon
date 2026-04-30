"""Tests for backend.app.startup_checks.

These verify ADR-005 enforcement: production refuses to start with unsafe
defaults. Test environments are unaffected — production-only checks become
no-ops outside ARCHON_ENV in {production, staging}.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clean slate per test — wipe any inherited env vars and singletons."""
    for key in (
        "ARCHON_ENV",
        "LANGGRAPH_CHECKPOINTING",
        "ARCHON_JWT_SECRET",
        "JWT_SECRET",
        "ARCHON_AUTH_DEV_MODE",
        "AUTH_DEV_MODE",
        "ARCHON_DATABASE_URL",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    from app.langgraph import checkpointer as _ckpt

    _ckpt.reset_checkpointer()
    yield
    _ckpt.reset_checkpointer()


def _good_postgres_secret() -> dict[str, str]:
    """Env block representing a well-configured production deploy."""
    return {
        "ARCHON_ENV": "production",
        "LANGGRAPH_CHECKPOINTING": "postgres",
        "ARCHON_JWT_SECRET": "x" * 64,  # strong random length
        "ARCHON_AUTH_DEV_MODE": "false",
        "ARCHON_DATABASE_URL": "postgresql+asyncpg://archon:archon@db:5432/archon",
        "DATABASE_URL": "postgresql+asyncpg://archon:archon@db:5432/archon",
    }


def _stub_postgres_checkpointer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make _get_postgres_checkpointer return an object whose class has 'Postgres' in the name."""

    class _FakePostgresSaver:  # noqa: D401 - simple stub
        """Stand-in for AsyncPostgresSaver used by startup-check tests."""

    async def _ok() -> _FakePostgresSaver:
        return _FakePostgresSaver()

    from app.langgraph import checkpointer as _ckpt

    monkeypatch.setattr(_ckpt, "_get_postgres_checkpointer", _ok)


# ---------------------------------------------------------------------------
# Pass-through cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passes_in_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ARCHON_ENV=test (and unset) → all production checks no-op."""
    monkeypatch.setenv("ARCHON_ENV", "test")
    # Even with intentionally bad values, none of the prod-only checks fire.
    monkeypatch.setenv("ARCHON_JWT_SECRET", "dev-secret")
    monkeypatch.setenv("ARCHON_AUTH_DEV_MODE", "true")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "memory")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

    from app.startup_checks import run_startup_checks

    # Should not raise.
    await run_startup_checks()


@pytest.mark.asyncio
async def test_does_not_run_in_dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same as test env — dev is non-durable."""
    monkeypatch.setenv("ARCHON_ENV", "dev")
    monkeypatch.setenv("ARCHON_JWT_SECRET", "dev-secret")
    monkeypatch.setenv("ARCHON_AUTH_DEV_MODE", "true")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "memory")

    from app.startup_checks import run_startup_checks

    await run_startup_checks()


@pytest.mark.asyncio
async def test_passes_in_production_with_good_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy production config (good secrets + Postgres) → no failure."""
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import run_startup_checks

    await run_startup_checks()


# ---------------------------------------------------------------------------
# Production failure cases (each must abort startup)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aborts_in_production_with_dev_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ARCHON_JWT_SECRET", "dev-secret")
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    assert any("JWT_SECRET" in f for f in exc_info.value.failures)


@pytest.mark.asyncio
async def test_aborts_in_production_with_short_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ARCHON_JWT_SECRET", "shortsecret")
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    assert any("too short" in f.lower() for f in exc_info.value.failures)


@pytest.mark.asyncio
async def test_aborts_in_production_with_sqlite_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ARCHON_DATABASE_URL", "sqlite:///./prod.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./prod.db")
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    assert any("sqlite" in f.lower() for f in exc_info.value.failures)


@pytest.mark.asyncio
async def test_aborts_in_production_with_memory_checkpointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "memory")
    # The memory env-check fires before the checkpointer-init check, but stub
    # anyway so an unrelated import error doesn't mask the assertion.
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    assert any(
        "LANGGRAPH_CHECKPOINTING=memory" in f for f in exc_info.value.failures
    )


@pytest.mark.asyncio
async def test_aborts_in_production_with_disabled_checkpointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "disabled")
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    assert any("disabled" in f.lower() for f in exc_info.value.failures)


@pytest.mark.asyncio
async def test_aborts_in_production_with_AUTH_DEV_MODE_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ARCHON_AUTH_DEV_MODE", "true")
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    assert any("AUTH_DEV_MODE" in f for f in exc_info.value.failures)


@pytest.mark.asyncio
async def test_aborts_in_production_when_checkpointer_returns_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if env vars look ok, an actual MemorySaver instance must be rejected."""
    for k, v in _good_postgres_secret().items():
        monkeypatch.setenv(k, v)

    # Stub the postgres builder to *return* a MemorySaver-like object, simulating
    # a regression where the factory silently substitutes a non-durable saver.
    class _FakeMemorySaver:  # noqa: D401
        """Stub whose class name does not contain 'Postgres'."""

    async def _wrong() -> _FakeMemorySaver:
        return _FakeMemorySaver()

    from app.langgraph import checkpointer as _ckpt

    monkeypatch.setattr(_ckpt, "_get_postgres_checkpointer", _wrong)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    joined = " | ".join(exc_info.value.failures)
    assert "FakeMemorySaver" in joined or "expected AsyncPostgresSaver" in joined


@pytest.mark.asyncio
async def test_aggregates_multiple_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All applicable failures appear in the same StartupCheckFailed."""
    monkeypatch.setenv("ARCHON_ENV", "production")
    monkeypatch.setenv("ARCHON_JWT_SECRET", "dev-secret")
    monkeypatch.setenv("ARCHON_AUTH_DEV_MODE", "true")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "memory")
    monkeypatch.setenv("ARCHON_DATABASE_URL", "sqlite:///./prod.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./prod.db")
    _stub_postgres_checkpointer(monkeypatch)

    from app.startup_checks import StartupCheckFailed, run_startup_checks

    with pytest.raises(StartupCheckFailed) as exc_info:
        await run_startup_checks()
    failures = exc_info.value.failures
    # At least 4 distinct issues should be reported.
    assert len(failures) >= 4
    joined = " | ".join(failures)
    assert "JWT_SECRET" in joined
    assert "AUTH_DEV_MODE" in joined
    assert "LANGGRAPH_CHECKPOINTING=memory" in joined
    assert "sqlite" in joined.lower()
