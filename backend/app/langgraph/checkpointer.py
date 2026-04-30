"""LangGraph checkpointer factory — ADR-005 compliant.

Production durability policy (ADR-005):

- In production / staging environments (``ARCHON_ENV in {production, staging}``)
  the Postgres checkpointer is **mandatory**. Any failure to set it up — import
  error, connect error, setup error, invalid config — is **FATAL**: the function
  raises :class:`CheckpointerDurabilityFailed` and the caller (``startup_checks``)
  converts that to ``SystemExit(1)`` before the API listener binds.

- In dev / test environments (``ARCHON_ENV in {dev, test}`` or unset) the
  legacy fallback to ``MemorySaver`` is preserved so local workflows continue
  to function without a Postgres instance.

- ``MemorySaver`` is permitted only when ``LANGGRAPH_CHECKPOINTING=memory`` is
  explicitly set OR ``ARCHON_ENV`` classifies the environment as non-durable.

Decision matrix (resolve_checkpointer_mode):

    LANGGRAPH_CHECKPOINTING=postgres  → 'postgres'
    LANGGRAPH_CHECKPOINTING=memory    → 'memory'
    LANGGRAPH_CHECKPOINTING=disabled  → 'disabled'   (legacy aliases: false/0/off/none)
    (unset)                           → ARCHON_ENV in {production, staging} → 'postgres'
                                       ARCHON_ENV in {dev, test} or unset    → 'memory'

Usage::

    from app.langgraph.checkpointer import get_checkpointer

    saver = await get_checkpointer()          # may be None
    compiled = graph.compile(checkpointer=saver)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)

# Module-level singleton — built once, reused across calls.
_saver: BaseCheckpointSaver | None = None
_saver_initialized: bool = False

# Values of LANGGRAPH_CHECKPOINTING that mean "no checkpointing".
_DISABLED_VALUES: frozenset[str] = frozenset({"false", "0", "off", "none", "disabled"})

# Environments where the Postgres checkpointer is mandatory.
_DURABLE_ENVS: frozenset[str] = frozenset({"production", "staging"})


class CheckpointerDurabilityFailed(RuntimeError):
    """Raised in production when the Postgres checkpointer cannot be initialised.

    The caller (typically ``startup_checks.run_startup_checks``) is expected to
    log a CRITICAL ``checkpointer_durability_failed`` event and abort startup
    with ``SystemExit(1)`` before the API listener binds. This guarantees that
    a misconfigured production deployment fails fast instead of silently
    running with non-durable in-memory checkpoints.
    """


def _is_production() -> bool:
    """Return True when ARCHON_ENV classifies the environment as durable."""
    env = os.getenv("ARCHON_ENV", "dev").lower().strip()
    return env in _DURABLE_ENVS


def resolve_checkpointer_mode() -> str:
    """Determine which checkpointer backend to use.

    Decision tree (first match wins):

    1. ``LANGGRAPH_CHECKPOINTING`` is set to ``postgres`` / ``memory`` /
       a disabled alias → use that mode explicitly.
    2. ``LANGGRAPH_CHECKPOINTING`` is unset and ``ARCHON_ENV`` is
       ``production`` / ``staging`` → ``'postgres'`` (no fallback).
    3. Otherwise (dev / test / unset env) → ``'memory'``.

    Returns:
        One of ``'postgres'``, ``'memory'``, or ``'disabled'``.
    """
    raw = os.getenv("LANGGRAPH_CHECKPOINTING", "").lower().strip()

    if raw == "postgres":
        return "postgres"
    if raw == "memory":
        return "memory"
    if raw in _DISABLED_VALUES:
        return "disabled"

    # LANGGRAPH_CHECKPOINTING unset (or unrecognised) — fall back on ARCHON_ENV.
    if _is_production():
        return "postgres"
    return "memory"


def _get_db_dsn() -> str:
    """Return a psycopg-compatible DSN for the checkpoint database.

    Priority order:
    1. ``LANGGRAPH_CHECKPOINT_DSN`` env var (explicit override for the
       checkpointer, useful when the main DB uses asyncpg dialect).
    2. ``DATABASE_URL`` / ``ARCHON_DATABASE_URL`` env var — ``+asyncpg``
       dialect prefix is stripped automatically.
    3. Fallback to the application ``settings`` object.

    The returned DSN uses the ``postgresql://`` scheme (no ``+asyncpg``)
    because ``AsyncPostgresSaver`` uses *psycopg3* (not asyncpg).
    """
    explicit = os.getenv("LANGGRAPH_CHECKPOINT_DSN", "")
    if explicit:
        return explicit

    for env_key in ("ARCHON_DATABASE_URL", "DATABASE_URL"):
        url = os.getenv(env_key, "")
        if url:
            return url.replace("+asyncpg", "")

    try:
        from app.config import settings  # noqa: PLC0415

        return settings.DATABASE_URL.replace("+asyncpg", "")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "checkpointer: unable to resolve DATABASE_URL from settings (%s); "
            "falling back to localhost default",
            exc,
        )
        return "postgresql://archon:archon@localhost:5432/archon"


def _mask_dsn(dsn: str) -> str:
    """Mask the password in a DSN for safe logging."""
    try:
        import re

        return re.sub(r"(:)[^:@]+(@)", r"\1***\2", dsn)
    except Exception as exc:  # noqa: BLE001
        logger.debug("_mask_dsn fell back: %s", exc)
        return "<dsn>"


def _dsn_host(dsn: str) -> str:
    """Extract the host[:port] component of a DSN for logging (no creds)."""
    try:
        import re

        # Strip scheme + creds, then keep up to the next '/'.
        m = re.search(r"@([^/?]+)", dsn)
        if m:
            return m.group(1)
        # No creds — fall back to scheme+host parsing.
        m = re.match(r"\w+://([^/?]+)", dsn)
        if m:
            return m.group(1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("_dsn_host fell back: %s", exc)
    return "<unknown>"


async def _get_postgres_checkpointer() -> BaseCheckpointSaver:
    """Build and return an AsyncPostgresSaver. Raises on any failure.

    This is intentionally narrow — it does not catch exceptions. The caller
    (:func:`get_checkpointer`) decides whether to escalate to
    :class:`CheckpointerDurabilityFailed` (production) or fall back to
    ``MemorySaver`` (dev/test).
    """
    from langgraph.checkpoint.postgres.aio import (  # noqa: PLC0415
        AsyncConnectionPool,
        AsyncPostgresSaver,
    )

    dsn = _get_db_dsn()
    logger.info("checkpointer: connecting to PostgreSQL (%s)", _mask_dsn(dsn))

    pool = AsyncConnectionPool(
        conninfo=dsn,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()

    saver = AsyncPostgresSaver(conn=pool)
    # Create checkpoint tables (idempotent — safe to call on every startup).
    await saver.setup()
    logger.info("checkpointer: AsyncPostgresSaver ready (postgres backend)")
    return saver


def _get_memory_checkpointer() -> BaseCheckpointSaver:
    """Return an in-process MemorySaver (non-durable)."""
    from langgraph.checkpoint.memory import MemorySaver  # noqa: PLC0415

    logger.info("checkpointer: using MemorySaver (in-memory, non-persistent)")
    return MemorySaver()


def _classify_postgres_failure(exc: BaseException) -> str:
    """Classify a Postgres setup failure for the structured log event."""
    if isinstance(exc, ImportError):
        return "import_error"
    msg = repr(exc).lower()
    if "connect" in msg or "could not translate host" in msg or "refused" in msg:
        return "connect_error"
    return "setup_error"


async def get_checkpointer() -> BaseCheckpointSaver | None:
    """Return the configured LangGraph checkpointer (idempotent singleton).

    Behaviour by environment (ADR-005):

    * **production / staging**: Postgres saver MUST initialise. On failure
      this function raises :class:`CheckpointerDurabilityFailed` after
      emitting a structured CRITICAL log line. There is no silent fallback.

    * **dev / test**: Postgres failures fall back to ``MemorySaver`` with a
      WARNING log so local development continues to work.

    * **explicit memory / disabled**: Honoured in any environment, but
      ``startup_checks`` will reject ``memory``/``disabled`` when
      ``ARCHON_ENV`` classifies the environment as durable.

    Returns:
        A ready-to-use ``BaseCheckpointSaver`` instance, or ``None`` when
        checkpointing is explicitly disabled.

    Raises:
        CheckpointerDurabilityFailed: in production / staging when the
            Postgres saver cannot be initialised.
    """
    global _saver, _saver_initialized  # noqa: PLW0603

    if _saver_initialized:
        return _saver

    mode = resolve_checkpointer_mode()
    durable_env = _is_production()

    if mode == "disabled":
        logger.info(
            "checkpointer: disabled (LANGGRAPH_CHECKPOINTING=%s)",
            os.getenv("LANGGRAPH_CHECKPOINTING", ""),
        )
        _saver = None
        _saver_initialized = True
        return None

    if mode == "memory":
        _saver = _get_memory_checkpointer()
        _saver_initialized = True
        return _saver

    # mode == "postgres"
    try:
        saver = await _get_postgres_checkpointer()
    except Exception as exc:  # noqa: BLE001
        if durable_env:
            reason = _classify_postgres_failure(exc)
            dsn_host = _dsn_host(_get_db_dsn())
            logger.critical(
                "checkpointer_durability_failed",
                extra={
                    "event": "checkpointer_durability_failed",
                    "archon_env": os.getenv("ARCHON_ENV", "dev"),
                    "langgraph_checkpointing": os.getenv(
                        "LANGGRAPH_CHECKPOINTING", "postgres"
                    ),
                    "reason": reason,
                    "detail": f"{type(exc).__name__}: {exc}"[:500],
                    "pg_host": dsn_host,
                    "remediation": (
                        "Set DATABASE_URL to a reachable PostgreSQL DSN with "
                        "langgraph-checkpoint-postgres installed; or set "
                        "ARCHON_ENV=dev to permit MemorySaver"
                    ),
                },
            )
            # Phase 5: emit canonical checkpoint failure metric.
            try:
                from app.middleware import metrics_middleware as _m  # noqa: PLC0415

                _m.record_checkpoint_failure(
                    env=os.getenv("ARCHON_ENV", "dev"),
                    reason=reason,
                )
            except Exception as inner_exc:  # noqa: BLE001
                logger.debug(
                    "checkpoint failure metric emit failed: %s", inner_exc
                )
            raise CheckpointerDurabilityFailed(
                f"Postgres checkpointer unavailable in {os.getenv('ARCHON_ENV', 'dev')} "
                f"({reason}: {type(exc).__name__}: {exc})"
            ) from exc

        logger.warning(
            "checkpointer: Postgres unavailable in non-prod (%s: %s); "
            "falling back to MemorySaver",
            type(exc).__name__,
            exc,
        )
        _saver = _get_memory_checkpointer()
        _saver_initialized = True
        return _saver

    _saver = saver
    _saver_initialized = True
    return _saver


def reset_checkpointer() -> None:
    """Reset the singleton — for testing only.

    Call this between tests that need different checkpointer backends.
    """
    global _saver, _saver_initialized  # noqa: PLW0603
    _saver = None
    _saver_initialized = False
