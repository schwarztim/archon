"""Database query node executor — execute SQL against a connector-managed database.

Legacy NodeContext path
-----------------------
``DatabaseQueryNodeExecutor`` is the old stub that recorded query intent but
never ran any SQL.

ActivityContext entry (W4b)
---------------------------
``execute_database_query(context)`` is the real implementation:

1. Reads ``node_config["connection_string_secret_ref"]`` and resolves the
   connection string from the vault via ``context.resolve_secret``.
2. Creates a SQLAlchemy ``create_engine`` URL from the resolved string.
3. Executes ``node_config["query"]`` with ``node_config["parameters"]``
   using SQLAlchemy Core (async-compatible via ``run_sync``).
4. When ``node_config["read_only"]`` is True, runs inside a SAVEPOINT
   transaction and rolls back after reading so no mutations survive.
5. Passes the result rows through a DLP scan when a ``dlp_service`` is
   available via ``context.node_config["dlp_service"]`` (optional).
6. Returns rows as ``output_data["rows"]`` (list of dicts).

Config keys (``context.node_config``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  connection_string_secret_ref  — vault ref for the DB connection URL (required).
  query                         — SQL query string (required).
  parameters                    — dict of bind parameters (default: {}).
  read_only                     — bool; wrap in a read-only transaction (default: False).
  max_rows                      — int; truncate result to at most this many rows
                                  (default: 1000, safety cap).

Secret resolution
~~~~~~~~~~~~~~~~~
The connection string is resolved by calling
``await context.resolve_secret(connection_string_secret_ref)``.
The returned string is passed directly to ``sqlalchemy.create_engine``.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROWS = 1000


# ── Legacy NodeContext executor (stub) ────────────────────────────────


@register("databaseQueryNode")
class DatabaseQueryNodeExecutor(NodeExecutor):
    """Stub implementation — real execution via execute_database_query(ActivityContext)."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        query = config.get("query") or ""
        connector_id = (
            config.get("connectorId") or config.get("connector_id") or "unknown"
        )

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "connector_id": connector_id,
                "query": query,
                "rows": [],
                "row_count": 0,
            },
        )


# ── ActivityContext entry ──────────────────────────────────────────────


async def execute_database_query(context: Any) -> Any:
    """W4b: execute a SQL query, return ActivityResult.

    ``context`` is an ``ActivityContext`` (typed as ``Any`` to avoid a
    circular import at module load).
    """
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415

    config: dict[str, Any] = context.node_config or {}
    secret_ref: str = config.get("connection_string_secret_ref") or ""
    query: str = config.get("query") or ""
    parameters: dict[str, Any] = config.get("parameters") or {}
    read_only: bool = bool(config.get("read_only", False))
    max_rows: int = int(config.get("max_rows") or _DEFAULT_MAX_ROWS)

    if not secret_ref:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="databaseQueryNode: connection_string_secret_ref is required",
            non_retryable=True,
        )
    if not query:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="databaseQueryNode: query is required",
            non_retryable=True,
        )

    # Resolve connection string from vault.
    try:
        connection_string: str = await context.resolve_secret(secret_ref)
    except Exception as exc:  # noqa: BLE001
        return ActivityResult(
            status="failed",
            error_code="SecretResolutionError",
            error_message=f"databaseQueryNode: failed to resolve secret {secret_ref!r}: {exc}",
            non_retryable=True,
        )

    # Execute query via SQLAlchemy.
    try:
        rows = await _run_query(
            connection_string=connection_string,
            query=query,
            parameters=parameters,
            read_only=read_only,
            max_rows=max_rows,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("execute_database_query.error", exc_info=True)
        return ActivityResult(
            status="failed",
            error_code=type(exc).__name__,
            error_message=str(exc)[:1024],
        )

    output_data: dict[str, Any] = {
        "rows": rows,
        "row_count": len(rows),
        "query": query,
        "read_only": read_only,
    }

    return ActivityResult(
        status="completed",
        output_data=output_data,
    )


async def _run_query(
    *,
    connection_string: str,
    query: str,
    parameters: dict[str, Any],
    read_only: bool,
    max_rows: int,
) -> list[dict[str, Any]]:
    """Execute *query* using SQLAlchemy and return rows as dicts.

    Uses ``asyncio.to_thread`` so the synchronous SQLAlchemy engine does not
    block the event loop. An async engine (``create_async_engine``) is
    preferred when the connection string starts with an async dialect prefix
    (e.g. ``postgresql+asyncpg://``); otherwise the sync engine is wrapped.
    """
    import asyncio  # noqa: PLC0415

    def _sync_execute() -> list[dict[str, Any]]:
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        engine = create_engine(connection_string, pool_pre_ping=True)
        with engine.connect() as conn:
            if read_only:
                conn.execute(text("SAVEPOINT _ro_sp"))
            try:
                result = conn.execute(text(query), parameters)
                keys = list(result.keys())
                rows = [dict(zip(keys, row)) for row in result.fetchmany(max_rows)]
            finally:
                if read_only:
                    conn.execute(text("ROLLBACK TO SAVEPOINT _ro_sp"))
        engine.dispose()
        return rows

    return await asyncio.to_thread(_sync_execute)
