"""Abstract interface for agent CRUD operations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.interfaces.models import AgentDefinition


@runtime_checkable
class AgentRepository(Protocol):
    """Contract for agent persistence backends."""

    async def create(self, agent: AgentDefinition) -> AgentDefinition:
        """Persist a new agent and return the created record."""
        ...

    async def get(self, agent_id: str) -> AgentDefinition | None:
        """Return an agent by ID, or None if not found."""
        ...

    async def list(
        self, *, limit: int = 20, offset: int = 0
    ) -> list[AgentDefinition]:
        """Return a paginated list of agents."""
        ...

    async def update(
        self, agent_id: str, agent: AgentDefinition
    ) -> AgentDefinition | None:
        """Update an existing agent; return updated record or None."""
        ...

    async def delete(self, agent_id: str) -> bool:
        """Delete an agent by ID. Return True if deleted."""
        ...


__all__ = ["AgentRepository"]
