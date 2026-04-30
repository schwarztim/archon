"""MCP Interactive Components service for managing sessions, components, and interactions."""

from __future__ import annotations

from datetime import datetime, timezone

from app.utils.time import utcnow as _utcnow
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.mcp import (
    COMPONENT_TYPES,
    MCPComponent,
    MCPInteraction,
    MCPSession,
)


class MCPService:
    """Manages MCP interactive components, sessions, and user interactions.

    Provides CRUD and rendering for interactive UI elements that agents
    can embed in responses via WebSocket.
    """

    # ── Component Management ────────────────────────────────────────

    @staticmethod
    async def create_component(
        session: AsyncSession,
        *,
        session_id: UUID,
        component_type: str,
        props: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> MCPComponent:
        """Create a new interactive component within a session.

        Args:
            session: Database session.
            session_id: The MCP session this component belongs to.
            component_type: One of form, chart, table, text, code, image.
            props: Component-specific properties (schema, data, config).
            extra_metadata: Arbitrary metadata for the component.

        Returns:
            The persisted MCPComponent.

        Raises:
            ValueError: If component_type is invalid or session not found/active.
        """
        if component_type not in COMPONENT_TYPES:
            raise ValueError(
                f"Invalid component_type '{component_type}'. "
                f"Must be one of: {', '.join(sorted(COMPONENT_TYPES))}"
            )

        mcp_session = await session.get(MCPSession, session_id)
        if mcp_session is None:
            raise ValueError(f"MCP session '{session_id}' not found")
        if mcp_session.status != "active":
            raise ValueError(f"MCP session '{session_id}' is not active")

        component = MCPComponent(
            session_id=session_id,
            component_type=component_type,
            props=props or {},
            extra_metadata=extra_metadata or {},
        )
        session.add(component)
        await session.commit()
        await session.refresh(component)
        return component

    @staticmethod
    async def get_component(
        session: AsyncSession,
        component_id: UUID,
    ) -> MCPComponent | None:
        """Return a single component by ID."""
        return await session.get(MCPComponent, component_id)

    @staticmethod
    async def update_component(
        session: AsyncSession,
        component_id: UUID,
        data: dict[str, Any],
    ) -> MCPComponent | None:
        """Partial-update a component. Returns None if not found."""
        component = await session.get(MCPComponent, component_id)
        if component is None:
            return None
        for key, value in data.items():
            if hasattr(component, key):
                setattr(component, key, value)
        component.updated_at = datetime.now(timezone.utc)
        session.add(component)
        await session.commit()
        await session.refresh(component)
        return component

    @staticmethod
    async def delete_component(session: AsyncSession, component_id: UUID) -> bool:
        """Delete a component. Returns True if deleted."""
        component = await session.get(MCPComponent, component_id)
        if component is None:
            return False
        await session.delete(component)
        await session.commit()
        return True

    @staticmethod
    async def list_components(
        session: AsyncSession,
        *,
        session_id: UUID | None = None,
        component_type: str | None = None,
        state: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPComponent], int]:
        """Return paginated components with optional filters and total count."""
        base = select(MCPComponent)
        if session_id is not None:
            base = base.where(MCPComponent.session_id == session_id)
        if component_type is not None:
            base = base.where(MCPComponent.component_type == component_type)
        if state is not None:
            base = base.where(MCPComponent.state == state)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                MCPComponent.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        components = list(result.all())
        return components, total

    # ── Rendering ───────────────────────────────────────────────────

    @staticmethod
    async def render_component(
        session: AsyncSession,
        component_id: UUID,
    ) -> dict[str, Any]:
        """Render a component into a WebSocket-ready message payload.

        Returns a dict suitable for sending over WebSocket:
        ``{ type: "component", component: "<type>", props: {...}, id: "..." }``

        Raises:
            ValueError: If component not found or already unmounted.
        """
        component = await session.get(MCPComponent, component_id)
        if component is None:
            raise ValueError(f"Component '{component_id}' not found")
        if component.state == "unmounted":
            raise ValueError(f"Component '{component_id}' is unmounted")

        return {
            "type": "component",
            "component": component.component_type,
            "props": component.props,
            "id": str(component.id),
            "state": component.state,
            "extra_metadata": component.extra_metadata,
        }

    # ── Session Management ──────────────────────────────────────────

    @staticmethod
    async def create_session(
        session: AsyncSession,
        *,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> MCPSession:
        """Create a new MCP interactive session.

        Args:
            session: Database session.
            agent_id: Optional agent that owns this session.
            user_id: Optional user participating in this session.
            extra_metadata: Arbitrary metadata.

        Returns:
            The persisted MCPSession.
        """
        mcp_session = MCPSession(
            agent_id=agent_id,
            user_id=user_id,
            extra_metadata=extra_metadata or {},
        )
        session.add(mcp_session)
        await session.commit()
        await session.refresh(mcp_session)
        return mcp_session

    @staticmethod
    async def get_session(
        session: AsyncSession,
        session_id: UUID,
    ) -> MCPSession | None:
        """Return a single MCP session by ID."""
        return await session.get(MCPSession, session_id)

    @staticmethod
    async def close_session(
        session: AsyncSession,
        session_id: UUID,
    ) -> MCPSession | None:
        """Close an active MCP session. Returns None if not found."""
        mcp_session = await session.get(MCPSession, session_id)
        if mcp_session is None:
            return None
        mcp_session.status = "closed"
        mcp_session.closed_at = _utcnow()
        mcp_session.updated_at = _utcnow()
        session.add(mcp_session)
        await session.commit()
        await session.refresh(mcp_session)
        return mcp_session

    @staticmethod
    async def list_sessions(
        session: AsyncSession,
        *,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPSession], int]:
        """Return paginated MCP sessions with optional filters and total count."""
        base = select(MCPSession)
        if agent_id is not None:
            base = base.where(MCPSession.agent_id == agent_id)
        if user_id is not None:
            base = base.where(MCPSession.user_id == user_id)
        if status is not None:
            base = base.where(MCPSession.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                MCPSession.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        sessions = list(result.all())
        return sessions, total

    # ── Interaction Handling ────────────────────────────────────────

    @staticmethod
    async def handle_interaction(
        session: AsyncSession,
        *,
        session_id: UUID,
        component_id: UUID,
        event_type: str,
        payload: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> MCPInteraction:
        """Record a user interaction on a component.

        Args:
            session: Database session.
            session_id: The MCP session the interaction occurred in.
            component_id: The component that was interacted with.
            event_type: Type of event (onClick, onChange, onSubmit, etc.).
            payload: Event-specific data (form values, selection, etc.).
            extra_metadata: Arbitrary metadata.

        Returns:
            The persisted MCPInteraction.

        Raises:
            ValueError: If session or component not found, or session inactive.
        """
        mcp_session = await session.get(MCPSession, session_id)
        if mcp_session is None:
            raise ValueError(f"MCP session '{session_id}' not found")
        if mcp_session.status != "active":
            raise ValueError(f"MCP session '{session_id}' is not active")

        component = await session.get(MCPComponent, component_id)
        if component is None:
            raise ValueError(f"Component '{component_id}' not found")
        if component.state == "unmounted":
            raise ValueError(f"Component '{component_id}' is unmounted")

        interaction = MCPInteraction(
            session_id=session_id,
            component_id=component_id,
            event_type=event_type,
            payload=payload or {},
            extra_metadata=extra_metadata or {},
        )
        session.add(interaction)
        await session.commit()
        await session.refresh(interaction)
        return interaction

    @staticmethod
    async def list_interactions(
        session: AsyncSession,
        *,
        session_id: UUID | None = None,
        component_id: UUID | None = None,
        event_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPInteraction], int]:
        """Return paginated interactions with optional filters and total count."""
        base = select(MCPInteraction)
        if session_id is not None:
            base = base.where(MCPInteraction.session_id == session_id)
        if component_id is not None:
            base = base.where(MCPInteraction.component_id == component_id)
        if event_type is not None:
            base = base.where(MCPInteraction.event_type == event_type)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                MCPInteraction.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        interactions = list(result.all())
        return interactions, total


__all__ = ["MCPService"]
