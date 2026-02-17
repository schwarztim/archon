"""Service for AuditLog operations (append-only)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import AuditLog


class AuditLogService:
    """Append-only audit trail operations.

    AuditLog entries are immutable — no update or delete methods are provided.
    """

    @staticmethod
    async def create(
        session: AsyncSession,
        *,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Record an audit event and return the persisted entry."""
        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry

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
        stmt = base.offset(offset).limit(limit).order_by(AuditLog.created_at.desc())  # type: ignore[union-attr]
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
            AuditLog.resource_id == resource_id,
        )

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(AuditLog.created_at.desc())  # type: ignore[union-attr]
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

        stmt = base.offset(offset).limit(limit).order_by(AuditLog.created_at.desc())  # type: ignore[union-attr]
        result = await session.exec(stmt)
        entries = list(result.all())
        return entries, total
