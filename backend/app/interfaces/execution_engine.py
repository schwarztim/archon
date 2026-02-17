"""Abstract interface for the agent execution engine."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.interfaces.models import ExecutionResult, ExecutionStatus


@runtime_checkable
class ExecutionEngine(Protocol):
    """Contract for backends that execute agent graphs."""

    async def execute(
        self, agent_id: str, input: dict[str, Any] | None = None
    ) -> ExecutionResult:
        """Start executing an agent and return the initial result."""
        ...

    async def get_status(self, execution_id: str) -> ExecutionStatus:
        """Return the current status of an execution."""
        ...

    async def cancel(self, execution_id: str) -> bool:
        """Cancel a running execution. Return True if successfully cancelled."""
        ...


__all__ = ["ExecutionEngine"]
