"""Secret access logger — records every access to secrets for audit trail.

Storage: primary writes go to ``SecretAccessLog`` DB table via an async
fire-and-forget task.  The in-memory ``_entries`` list is kept as a fallback
buffer so that synchronous callers (e.g. during startup before an event loop
is available) never lose data and query methods remain usable without an
explicit DB session.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SecretAccessEntry(BaseModel):
    """A single secret access log entry returned by the API."""

    id: str
    secret_path: str
    user_id: str | None = None
    user_email: str = ""
    action: str
    component: str = ""
    ip_address: str | None = None
    details: str | None = None
    created_at: str


async def _persist_entry(entry: dict[str, Any]) -> None:
    """Write a single access log entry to the DB (fire-and-forget)."""
    try:
        from app.database import async_session_factory
        from app.models.secrets import SecretAccessLog

        record = SecretAccessLog(
            id=UUID(entry["id"]),
            tenant_id=UUID(entry["tenant_id"]),
            secret_path=entry["secret_path"],
            user_id=UUID(entry["user_id"]) if entry.get("user_id") else None,
            user_email=entry.get("user_email", ""),
            action=entry["action"],
            component=entry.get("component", ""),
            ip_address=entry.get("ip_address"),
            details=entry.get("details"),
        )
        async with async_session_factory() as session:
            session.add(record)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.debug(
            "secret_access_logger.db_persist_failed",
            exc_info=True,
        )


class SecretAccessLogger:
    """Secret access logger backed by DB with in-memory fallback buffer.

    ``log_access`` is intentionally synchronous to preserve the existing call
    signature.  DB persistence is scheduled as an asyncio background task when
    an event loop is running; the entry is always appended to ``_entries`` so
    that reads work immediately and survive failures.
    """

    def __init__(self) -> None:
        # _entries acts as a write-through cache / fallback buffer.
        # DB is the primary store; this list ensures in-process reads are fast.
        self._entries: list[dict[str, Any]] = []  # kept as fallback — do not remove

    def log_access(
        self,
        *,
        tenant_id: str,
        secret_path: str,
        user_id: str | None = None,
        user_email: str = "",
        action: str,
        component: str = "",
        ip_address: str | None = None,
        details: str | None = None,
    ) -> None:
        """Record a secret access event.

        Appends to the in-memory buffer and schedules a DB INSERT via
        ``asyncio.create_task`` when an event loop is available.
        """
        entry: dict[str, Any] = {
            "id": str(uuid4()),
            "tenant_id": tenant_id,
            "secret_path": secret_path,
            "user_id": user_id,
            "user_email": user_email,
            "action": action,
            "component": component,
            "ip_address": ip_address,
            "details": details,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # In-memory buffer (fallback + fast reads)
        self._entries.append(entry)

        # Async DB INSERT — fire and forget; safe to skip if loop unavailable
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist_entry(entry))
        except RuntimeError:
            # No running event loop (e.g. called from sync startup code);
            # entry is preserved in _entries fallback buffer.
            logger.debug(
                "secret_access_logger.no_event_loop_fallback",
                extra={"action": action, "secret_path": secret_path},
            )

        logger.info(
            "Secret access logged",
            extra={
                "tenant_id": tenant_id,
                "secret_path": secret_path,
                "action": action,
                "user_email": user_email,
            },
        )

    def get_access_log(
        self,
        secret_path: str,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SecretAccessEntry], int]:
        """Return access log entries for a specific secret, scoped to tenant.

        Reads from the in-memory buffer.  For production queries against the
        full DB history, use ``async_get_access_log`` instead.
        """
        filtered = [
            e
            for e in self._entries
            if e["tenant_id"] == tenant_id and e["secret_path"] == secret_path
        ]
        filtered.sort(key=lambda x: x["created_at"], reverse=True)
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return [
            SecretAccessEntry(**{k: v for k, v in e.items() if k != "tenant_id"})
            for e in page
        ], total

    def get_all_access_logs(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SecretAccessEntry], int]:
        """Return all access log entries for a tenant.

        Reads from the in-memory buffer.  For production queries against the
        full DB history, use ``async_get_all_access_logs`` instead.
        """
        filtered = [e for e in self._entries if e["tenant_id"] == tenant_id]
        filtered.sort(key=lambda x: x["created_at"], reverse=True)
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return [
            SecretAccessEntry(**{k: v for k, v in e.items() if k != "tenant_id"})
            for e in page
        ], total

    async def async_get_access_log(
        self,
        secret_path: str,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SecretAccessEntry], int]:
        """Query access log for a specific secret directly from the DB."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.models.secrets import SecretAccessLog

        try:
            async with async_session_factory() as session:
                stmt = (
                    select(SecretAccessLog)
                    .where(SecretAccessLog.tenant_id == UUID(tenant_id))
                    .where(SecretAccessLog.secret_path == secret_path)
                    .order_by(SecretAccessLog.created_at.desc())
                )
                result = await session.exec(stmt)
                rows = result.all()
        except Exception:  # noqa: BLE001
            logger.debug("secret_access_logger.db_query_failed", exc_info=True)
            return self.get_access_log(
                secret_path, tenant_id, limit=limit, offset=offset
            )

        total = len(rows)
        page = rows[offset : offset + limit]
        entries = [
            SecretAccessEntry(
                id=str(row.id),
                secret_path=row.secret_path,
                user_id=str(row.user_id) if row.user_id else None,
                user_email=row.user_email,
                action=row.action,
                component=row.component,
                ip_address=row.ip_address,
                details=row.details,
                created_at=row.created_at.isoformat() if row.created_at else "",
            )
            for row in page
        ]
        return entries, total

    async def async_get_all_access_logs(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SecretAccessEntry], int]:
        """Query all access logs for a tenant directly from the DB."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.models.secrets import SecretAccessLog

        try:
            async with async_session_factory() as session:
                stmt = (
                    select(SecretAccessLog)
                    .where(SecretAccessLog.tenant_id == UUID(tenant_id))
                    .order_by(SecretAccessLog.created_at.desc())
                )
                result = await session.exec(stmt)
                rows = result.all()
        except Exception:  # noqa: BLE001
            logger.debug("secret_access_logger.db_query_all_failed", exc_info=True)
            return self.get_all_access_logs(tenant_id, limit=limit, offset=offset)

        total = len(rows)
        page = rows[offset : offset + limit]
        entries = [
            SecretAccessEntry(
                id=str(row.id),
                secret_path=row.secret_path,
                user_id=str(row.user_id) if row.user_id else None,
                user_email=row.user_email,
                action=row.action,
                component=row.component,
                ip_address=row.ip_address,
                details=row.details,
                created_at=row.created_at.isoformat() if row.created_at else "",
            )
            for row in page
        ]
        return entries, total


# Module-level singleton
_access_logger: SecretAccessLogger | None = None


def get_access_logger() -> SecretAccessLogger:
    """Return the singleton SecretAccessLogger instance."""
    global _access_logger  # noqa: PLW0603
    if _access_logger is None:
        _access_logger = SecretAccessLogger()
    return _access_logger


__all__ = [
    "SecretAccessEntry",
    "SecretAccessLogger",
    "get_access_logger",
]
