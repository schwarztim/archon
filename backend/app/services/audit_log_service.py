"""Service for AuditLog operations (append-only).

Thin wrapper around AuditService for backwards-compatible list/filter
operations used by the audit-logs API endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import AuditLog


class AuditLogService:
    """Append-only audit trail read operations.

    AuditLog entries are immutable — no update or delete methods are provided.
    For writing new entries use AuditService.log_action().
    """

    @staticmethod
    async def list_all(
        session: AsyncSession,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Return all paginated audit entries (no filter)."""
        base = select(AuditLog)
        count_result = await session.exec(base)
        total = len(count_result.all())
        stmt = (
            select(AuditLog)
            .offset(offset)
            .limit(limit)
            .order_by(AuditLog.created_at.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def list_by_resource(
        session: AsyncSession,
        *,
        resource_type: str,
        resource_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Return paginated audit entries for a specific resource."""
        base = select(AuditLog).where(
            AuditLog.resource_type == resource_type,
            AuditLog.resource_id == str(resource_id),
        )

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            select(AuditLog)
            .where(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == str(resource_id),
            )
            .offset(offset)
            .limit(limit)
            .order_by(AuditLog.created_at.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        entries = list(result.all())
        return entries, total

    @staticmethod
    async def list_by_actor(
        session: AsyncSession,
        *,
        actor_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Return paginated audit entries for a specific actor."""
        base = select(AuditLog).where(AuditLog.actor_id == actor_id)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor_id)
            .offset(offset)
            .limit(limit)
            .order_by(AuditLog.created_at.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        entries = list(result.all())
        return entries, total

    @staticmethod
    async def list_filtered(
        session: AsyncSession,
        *,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        actor_id: UUID | None = None,
        action: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Return paginated audit entries with combined filters."""
        conditions = []

        if resource_type:
            conditions.append(AuditLog.resource_type == resource_type)
        if resource_id:
            conditions.append(AuditLog.resource_id == str(resource_id))
        if actor_id:
            conditions.append(AuditLog.actor_id == actor_id)
        if action:
            conditions.append(AuditLog.action == action)
        if date_from:
            conditions.append(AuditLog.created_at >= date_from)
        if date_to:
            conditions.append(AuditLog.created_at <= date_to)
        if search:
            conditions.append(AuditLog.action.contains(search))  # type: ignore[union-attr]

        base = select(AuditLog)
        if conditions:
            base = base.where(*conditions)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(AuditLog.created_at.desc())  # type: ignore[union-attr]
        result = await session.exec(stmt)
        return list(result.all()), total
