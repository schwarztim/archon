"""PostgreSQL connector — asyncpg-backed implementation of BaseConnector."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class PostgreSQLConnector(BaseConnector):
    """Connector for PostgreSQL databases using asyncpg.

    Configuration keys (``config`` dict):
        host: Database hostname.
        port: Port number (default 5432).
        database: Database name.
        ssl: SSL mode — "disable" | "require" | "verify-ca" | "verify-full".

    Credential keys (``credentials`` dict, loaded from Vault):
        username: Database user.
        password: Database password.
    """

    connector_type = "postgresql"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(config, credentials)
        self._pool: Any = None  # asyncpg.Pool set after connect

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _get_pool(self) -> Any:
        """Return the asyncpg connection pool, creating it on first call."""
        if self._pool is not None:
            return self._pool

        try:
            import asyncpg  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PostgreSQLConnector. "
                "Install it with: pip install asyncpg"
            ) from exc

        host = self.config.get("host", "localhost")
        port = int(self.config.get("port", 5432))
        database = self.config.get("database", "postgres")
        ssl_mode = self.config.get("ssl", "disable")
        username = self.credentials.get("username") or self.config.get("username", "")
        password = self.credentials.get("password") or self.credentials.get(
            "secret_credential", ""
        )

        ssl: Any = None
        if ssl_mode in ("require", "verify-ca", "verify-full"):
            ssl = True

        self._pool = await asyncpg.create_pool(
            host=host,
            port=port,
            database=database,
            user=username,
            password=password,
            ssl=ssl,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        return self._pool

    async def close(self) -> None:
        """Close the asyncpg connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Verify connectivity by running ``SELECT 1``."""
        start = time.monotonic()
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            latency = (time.monotonic() - start) * 1000
            return {
                "success": True,
                "latency_ms": round(latency, 2),
                "message": "Connection successful",
                "details": {
                    "host": self.config.get("host"),
                    "database": self.config.get("database"),
                },
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.warning("PostgreSQL test_connection failed: %s", exc)
            return {
                "success": False,
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def health_check(self) -> dict[str, Any]:
        """Run ``SELECT 1`` and return health status."""
        start = time.monotonic()
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                pg_version = await conn.fetchval("SELECT version()")
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "message": "Database reachable",
                "details": {"version": pg_version},
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "error",
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def list_resources(self) -> list[dict[str, Any]]:
        """Return all user tables in the connected database via information_schema."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT table_schema, table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                    ORDER BY table_schema, table_name
                    """
                )
            return [
                {
                    "id": f"{row['table_schema']}.{row['table_name']}",
                    "name": row["table_name"],
                    "schema": row["table_schema"],
                    "type": row["table_type"],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("PostgreSQL list_resources failed: %s", exc)
            raise

    async def read(
        self,
        resource_id: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a parameterised SELECT query against a table.

        Args:
            resource_id: Fully-qualified table name, e.g. ``"public.users"``.
            params: Optional dict with:
                - ``limit`` (int, default 100)
                - ``offset`` (int, default 0)
                - ``where`` (str, raw WHERE clause — must be pre-validated)
                - ``columns`` (list[str])

        Returns:
            List of row dicts.
        """
        params = params or {}
        limit = int(params.get("limit", 100))
        offset = int(params.get("offset", 0))
        # Clamp to sane bounds
        limit = min(max(limit, 1), 10_000)
        offset = max(offset, 0)

        # Use quoted identifier to prevent injection via resource_id
        schema_table = resource_id.strip()
        parts = schema_table.split(".", 1)
        if len(parts) == 2:
            quoted = f'"{parts[0]}"."{parts[1]}"'
        else:
            quoted = f'"{parts[0]}"'

        query = f"SELECT * FROM {quoted} LIMIT $1 OFFSET $2"  # noqa: S608

        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, limit, offset)
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error("PostgreSQL read failed for %s: %s", resource_id, exc)
            raise

    async def write(
        self,
        resource_id: str,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert one or more rows into a table inside a transaction.

        Args:
            resource_id: Fully-qualified table name.
            data: Either a single dict of column→value pairs, or a list of
                such dicts for bulk insert.  All records in a list must have
                the same set of columns.
            params: Optional dict with ``on_conflict`` strategy.

        Returns:
            Dict with ``{"success": bool, "rows_affected": int}``.
        """
        # Normalise to list for uniform handling
        if isinstance(data, dict):
            records: list[dict[str, Any]] = [data]
        elif isinstance(data, list):
            records = data
        else:
            raise ValueError("data must be a dict or list of dicts")

        if not records:
            raise ValueError("data must contain at least one record")
        if not all(isinstance(r, dict) and r for r in records):
            raise ValueError("each record must be a non-empty dict")

        # Use columns from the first record; all rows must share the same keys
        columns = list(records[0].keys())
        if len(records) > 1:
            for i, rec in enumerate(records[1:], start=1):
                if set(rec.keys()) != set(columns):
                    raise ValueError(
                        f"record {i} has different keys than record 0 "
                        f"(expected {set(columns)}, got {set(rec.keys())})"
                    )

        parts = resource_id.strip().split(".", 1)
        if len(parts) == 2:
            quoted_table = f'"{parts[0]}"."{parts[1]}"'
        else:
            quoted_table = f'"{parts[0]}"'

        quoted_cols = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
        query = f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({placeholders})"  # noqa: S608

        try:
            pool = await self._get_pool()
            rows_affected = 0
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for record in records:
                        values = [record[c] for c in columns]
                        result = await conn.execute(query, *values)
                        # asyncpg returns "INSERT 0 <count>"
                        rows_affected += int(result.split()[-1]) if result else 0
            return {"success": True, "rows_affected": rows_affected}
        except Exception as exc:
            logger.error("PostgreSQL write failed for %s: %s", resource_id, exc)
            raise

    async def get_schema(self, resource_id: str) -> dict[str, Any]:
        """Return column definitions for a table from information_schema.

        Args:
            resource_id: Fully-qualified table name, e.g. ``"public.users"``.

        Returns:
            Dict with ``{"table": str, "columns": [{"name": str, "type": str, ...}]}``.
        """
        parts = resource_id.strip().split(".", 1)
        if len(parts) == 2:
            schema_name, table_name = parts
        else:
            schema_name, table_name = "public", parts[0]

        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        column_name,
                        data_type,
                        is_nullable,
                        column_default,
                        character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = $1
                      AND table_name   = $2
                    ORDER BY ordinal_position
                    """,
                    schema_name,
                    table_name,
                )
            columns = [
                {
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES",
                    "default": row["column_default"],
                    "max_length": row["character_maximum_length"],
                }
                for row in rows
            ]
            return {"table": resource_id, "columns": columns}
        except Exception as exc:
            logger.error("PostgreSQL get_schema failed for %s: %s", resource_id, exc)
            raise


__all__ = ["PostgreSQLConnector"]
