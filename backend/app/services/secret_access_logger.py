"""Secret access logger — records every access to secrets for audit trail."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field as PField

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


class SecretAccessLogger:
    """In-memory secret access logger for recording and querying access events.

    Stores access log entries in memory (will be backed by DB in production).
    Thread-safe for concurrent access via append-only design.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

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
        """Record a secret access event."""
        from uuid import uuid4

        entry = {
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
        self._entries.append(entry)

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
        """Return access log entries for a specific secret, scoped to tenant."""
        filtered = [
            e for e in self._entries
            if e["tenant_id"] == tenant_id and e["secret_path"] == secret_path
        ]
        filtered.sort(key=lambda x: x["created_at"], reverse=True)
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return [SecretAccessEntry(**{k: v for k, v in e.items() if k != "tenant_id"}) for e in page], total

    def get_all_access_logs(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SecretAccessEntry], int]:
        """Return all access log entries for a tenant."""
        filtered = [e for e in self._entries if e["tenant_id"] == tenant_id]
        filtered.sort(key=lambda x: x["created_at"], reverse=True)
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return [SecretAccessEntry(**{k: v for k, v in e.items() if k != "tenant_id"}) for e in page], total


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
