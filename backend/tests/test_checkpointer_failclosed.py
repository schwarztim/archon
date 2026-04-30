"""Tests for the ADR-005 fail-closed checkpointer policy.

Coverage:
    - resolve_checkpointer_mode picks 'postgres' for production by default.
    - resolve_checkpointer_mode picks 'memory' for dev/test by default.
    - Explicit LANGGRAPH_CHECKPOINTING values override the env-derived default.
    - get_checkpointer raises CheckpointerDurabilityFailed in production when
      Postgres setup fails (no silent fallback).
    - get_checkpointer falls back to MemorySaver in dev when Postgres fails.
    - get_checkpointer is a per-process singleton (idempotent).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset() -> None:
    """Reset the module-level singleton between tests."""
    from app.langgraph import checkpointer as _ckpt

    _ckpt.reset_checkpointer()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a clean singleton and pristine env."""
    monkeypatch.delenv("LANGGRAPH_CHECKPOINTING", raising=False)
    monkeypatch.delenv("ARCHON_ENV", raising=False)
    _reset()
    yield
    _reset()


# ---------------------------------------------------------------------------
# resolve_checkpointer_mode
# ---------------------------------------------------------------------------


def test_resolve_mode_with_explicit_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "memory")
    monkeypatch.setenv("ARCHON_ENV", "production")  # explicit memory wins
    from app.langgraph.checkpointer import resolve_checkpointer_mode

    assert resolve_checkpointer_mode() == "memory"


def test_resolve_mode_with_explicit_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "postgres")
    monkeypatch.setenv("ARCHON_ENV", "dev")
    from app.langgraph.checkpointer import resolve_checkpointer_mode

    assert resolve_checkpointer_mode() == "postgres"


def test_resolve_mode_production_default_is_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGGRAPH_CHECKPOINTING", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")
    from app.langgraph.checkpointer import resolve_checkpointer_mode

    assert resolve_checkpointer_mode() == "postgres"


def test_resolve_mode_staging_default_is_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGGRAPH_CHECKPOINTING", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "staging")
    from app.langgraph.checkpointer import resolve_checkpointer_mode

    assert resolve_checkpointer_mode() == "postgres"


def test_resolve_mode_dev_default_is_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGGRAPH_CHECKPOINTING", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")
    from app.langgraph.checkpointer import resolve_checkpointer_mode

    assert resolve_checkpointer_mode() == "memory"


def test_resolve_mode_unset_defaults_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGGRAPH_CHECKPOINTING", raising=False)
    monkeypatch.delenv("ARCHON_ENV", raising=False)
    from app.langgraph.checkpointer import resolve_checkpointer_mode

    assert resolve_checkpointer_mode() == "memory"


def test_resolve_mode_disabled_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("false", "0", "off", "none", "disabled"):
        monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", value)
        from app.langgraph.checkpointer import resolve_checkpointer_mode

        assert resolve_checkpointer_mode() == "disabled", value


# ---------------------------------------------------------------------------
# get_checkpointer fail-closed behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_checkpointer_raises_in_production_when_postgres_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production + Postgres failure → CheckpointerDurabilityFailed (no fallback)."""
    monkeypatch.setenv("ARCHON_ENV", "production")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "postgres")

    from app.langgraph import checkpointer as _ckpt

    async def _boom() -> None:
        raise ConnectionError("could not connect to postgres at db.invalid:5432")

    monkeypatch.setattr(_ckpt, "_get_postgres_checkpointer", _boom)

    with pytest.raises(_ckpt.CheckpointerDurabilityFailed) as exc_info:
        await _ckpt.get_checkpointer()
    assert "production" in str(exc_info.value).lower()
    assert "connect" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_checkpointer_raises_in_staging_when_postgres_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Staging is also durable — failure must be fatal."""
    monkeypatch.setenv("ARCHON_ENV", "staging")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "postgres")

    from app.langgraph import checkpointer as _ckpt

    async def _boom() -> None:
        raise ImportError("No module named 'langgraph.checkpoint.postgres'")

    monkeypatch.setattr(_ckpt, "_get_postgres_checkpointer", _boom)

    with pytest.raises(_ckpt.CheckpointerDurabilityFailed):
        await _ckpt.get_checkpointer()


@pytest.mark.asyncio
async def test_get_checkpointer_falls_back_in_dev_when_postgres_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev environment falls back to MemorySaver (legacy behaviour)."""
    monkeypatch.setenv("ARCHON_ENV", "dev")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "postgres")

    from app.langgraph import checkpointer as _ckpt

    async def _boom() -> None:
        raise ConnectionError("could not connect")

    monkeypatch.setattr(_ckpt, "_get_postgres_checkpointer", _boom)

    saver = await _ckpt.get_checkpointer()
    assert saver is not None
    # MemorySaver fallback in dev.
    assert "Memory" in type(saver).__name__


@pytest.mark.asyncio
async def test_get_checkpointer_falls_back_in_test_when_postgres_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test env behaves like dev — failures fall back."""
    monkeypatch.setenv("ARCHON_ENV", "test")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "postgres")

    from app.langgraph import checkpointer as _ckpt

    async def _boom() -> None:
        raise RuntimeError("setup_error")

    monkeypatch.setattr(_ckpt, "_get_postgres_checkpointer", _boom)

    saver = await _ckpt.get_checkpointer()
    assert saver is not None
    assert "Memory" in type(saver).__name__


@pytest.mark.asyncio
async def test_singleton_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling get_checkpointer twice returns the same instance."""
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "memory")
    monkeypatch.setenv("ARCHON_ENV", "test")

    from app.langgraph.checkpointer import get_checkpointer

    a = await get_checkpointer()
    b = await get_checkpointer()
    assert a is b
    assert a is not None


@pytest.mark.asyncio
async def test_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """LANGGRAPH_CHECKPOINTING=disabled returns None in non-prod."""
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "disabled")
    monkeypatch.setenv("ARCHON_ENV", "dev")

    from app.langgraph.checkpointer import get_checkpointer

    saver = await get_checkpointer()
    assert saver is None


@pytest.mark.asyncio
async def test_critical_log_emitted_on_production_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A CRITICAL 'checkpointer_durability_failed' log line is emitted before raising."""
    import logging

    monkeypatch.setenv("ARCHON_ENV", "production")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTING", "postgres")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://archon:archon@db.example.invalid:5432/archon"
    )

    from app.langgraph import checkpointer as _ckpt

    async def _boom() -> None:
        raise ConnectionError("connection refused")

    monkeypatch.setattr(_ckpt, "_get_postgres_checkpointer", _boom)

    caplog.set_level(logging.CRITICAL)
    with pytest.raises(_ckpt.CheckpointerDurabilityFailed):
        await _ckpt.get_checkpointer()

    # Verify the structured log fired.
    msgs = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert msgs, "expected a CRITICAL log line"
    rec = msgs[0]
    # The structured 'event' field should match the contract.
    assert getattr(rec, "event", None) == "checkpointer_durability_failed"
    # Host should be present (no creds).
    assert "db.example.invalid" in getattr(rec, "pg_host", "")
    assert "archon:archon" not in getattr(rec, "pg_host", "")
