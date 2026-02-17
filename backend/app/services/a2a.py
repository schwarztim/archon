"""A2A (Agent-to-Agent) protocol client and publisher services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.a2a import A2AAgentCard, A2AMessage, A2ATask


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ── A2A Client (discovery + outbound communication) ─────────────────


class A2AClient:
    """Discovers external A2A agents and sends tasks/messages to them.

    Handles the *consumption* side of the A2A protocol: fetching agent
    cards, sending messages, and managing outbound task lifecycle.
    """

    @staticmethod
    async def discover_agents(
        session: AsyncSession,
        *,
        capability: str | None = None,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[A2AAgentCard], int]:
        """Return paginated discovered (inbound) agent cards with optional filters."""
        base = select(A2AAgentCard).where(A2AAgentCard.direction == "inbound")
        if is_active is not None:
            base = base.where(A2AAgentCard.is_active == is_active)

        # Fetch all for total count (capability is in JSON column)
        count_result = await session.exec(base)
        all_rows = list(count_result.all())

        if capability is not None:
            all_rows = [r for r in all_rows if capability in (r.capabilities or [])]

        total = len(all_rows)

        stmt = base.offset(offset).limit(limit).order_by(
            A2AAgentCard.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        entries = list(result.all())

        if capability is not None:
            entries = [e for e in entries if capability in (e.capabilities or [])]

        return entries, total

    @staticmethod
    async def get_agent_card(
        session: AsyncSession,
        card_id: UUID,
    ) -> A2AAgentCard | None:
        """Return a single agent card by ID."""
        return await session.get(A2AAgentCard, card_id)

    @staticmethod
    async def register_agent_card(
        session: AsyncSession,
        card: A2AAgentCard,
    ) -> A2AAgentCard:
        """Register a discovered external agent card."""
        card.direction = "inbound"
        card.last_discovered_at = _utcnow()
        session.add(card)
        await session.commit()
        await session.refresh(card)
        return card

    @staticmethod
    async def send_message(
        session: AsyncSession,
        *,
        task_id: UUID,
        role: str,
        content: str,
        parts: list[dict[str, Any]] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> A2AMessage:
        """Record and send a message within an A2A task conversation."""
        message = A2AMessage(
            task_id=task_id,
            role=role,
            content=content,
            parts=parts or [],
            extra_metadata=extra_metadata or {},
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)
        return message

    @staticmethod
    async def create_task(
        session: AsyncSession,
        *,
        agent_card_id: UUID,
        input_data: dict[str, Any],
        extra_metadata: dict[str, Any] | None = None,
    ) -> A2ATask:
        """Create an outbound A2A task to an external agent."""
        task = A2ATask(
            agent_card_id=agent_card_id,
            direction="outbound",
            status="submitted",
            input_data=input_data,
            extra_metadata=extra_metadata or {},
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

    @staticmethod
    async def get_task(
        session: AsyncSession,
        task_id: UUID,
    ) -> A2ATask | None:
        """Return an A2A task by ID."""
        return await session.get(A2ATask, task_id)

    @staticmethod
    async def update_task_status(
        session: AsyncSession,
        task_id: UUID,
        *,
        status: str,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> A2ATask | None:
        """Update the status of an A2A task."""
        task = await session.get(A2ATask, task_id)
        if task is None:
            return None
        task.status = status
        task.updated_at = _utcnow()
        if output_data is not None:
            task.output_data = output_data
        if error is not None:
            task.error = error
        if status == "working" and task.started_at is None:
            task.started_at = _utcnow()
        if status in ("completed", "failed", "canceled"):
            task.completed_at = _utcnow()
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

    @staticmethod
    async def list_tasks(
        session: AsyncSession,
        *,
        agent_card_id: UUID | None = None,
        status: str | None = None,
        direction: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[A2ATask], int]:
        """Return paginated A2A tasks with optional filters."""
        base = select(A2ATask)
        if agent_card_id is not None:
            base = base.where(A2ATask.agent_card_id == agent_card_id)
        if status is not None:
            base = base.where(A2ATask.status == status)
        if direction is not None:
            base = base.where(A2ATask.direction == direction)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            A2ATask.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        tasks = list(result.all())
        return tasks, total

    @staticmethod
    async def list_messages(
        session: AsyncSession,
        *,
        task_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[A2AMessage], int]:
        """Return paginated messages for an A2A task."""
        base = select(A2AMessage).where(A2AMessage.task_id == task_id)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            A2AMessage.created_at.asc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        messages = list(result.all())
        return messages, total


# ── A2A Publisher (outbound agent card management) ──────────────────


class A2APublisher:
    """Publishes Archon agents as A2A-compatible services.

    Manages the *publishing* side: creating, updating, and removing
    A2A Agent Cards that describe Archon agents to external platforms.
    """

    @staticmethod
    async def publish_card(
        session: AsyncSession,
        card: A2AAgentCard,
    ) -> A2AAgentCard:
        """Publish an Archon agent as an A2A service by creating its agent card."""
        card.direction = "outbound"
        card.is_active = True
        session.add(card)
        await session.commit()
        await session.refresh(card)
        return card

    @staticmethod
    async def update_card(
        session: AsyncSession,
        card_id: UUID,
        data: dict[str, Any],
    ) -> A2AAgentCard | None:
        """Update a published agent card. Returns None if not found."""
        card = await session.get(A2AAgentCard, card_id)
        if card is None:
            return None
        for key, value in data.items():
            if hasattr(card, key):
                setattr(card, key, value)
        card.updated_at = _utcnow()
        session.add(card)
        await session.commit()
        await session.refresh(card)
        return card

    @staticmethod
    async def unpublish_card(
        session: AsyncSession,
        card_id: UUID,
    ) -> bool:
        """Unpublish (delete) an A2A agent card. Returns True if deleted."""
        card = await session.get(A2AAgentCard, card_id)
        if card is None:
            return False
        await session.delete(card)
        await session.commit()
        return True

    @staticmethod
    async def get_card(
        session: AsyncSession,
        card_id: UUID,
    ) -> A2AAgentCard | None:
        """Return a published agent card by ID."""
        return await session.get(A2AAgentCard, card_id)

    @staticmethod
    async def list_published(
        session: AsyncSession,
        *,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[A2AAgentCard], int]:
        """Return paginated published (outbound) agent cards."""
        base = select(A2AAgentCard).where(A2AAgentCard.direction == "outbound")
        if is_active is not None:
            base = base.where(A2AAgentCard.is_active == is_active)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            A2AAgentCard.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        cards = list(result.all())
        return cards, total

    @staticmethod
    async def get_well_known_card(
        session: AsyncSession,
        agent_id: UUID,
    ) -> A2AAgentCard | None:
        """Return the active outbound card for an Archon agent (for /.well-known/agent.json)."""
        stmt = (
            select(A2AAgentCard)
            .where(A2AAgentCard.agent_id == agent_id)
            .where(A2AAgentCard.direction == "outbound")
            .where(A2AAgentCard.is_active == True)  # noqa: E712
        )
        result = await session.exec(stmt)
        return result.first()


__all__ = [
    "A2AClient",
    "A2APublisher",
]
