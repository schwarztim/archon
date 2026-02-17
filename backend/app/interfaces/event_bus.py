"""Abstract interface for event publishing (WebSocket streaming, etc.)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.interfaces.models import Event


@runtime_checkable
class EventBus(Protocol):
    """Contract for pub/sub event backends."""

    async def publish(self, channel: str, event: Event) -> None:
        """Publish an event to a channel."""
        ...

    def subscribe(self, channel: str) -> AsyncIterator[Event]:
        """Return an async iterator that yields events from a channel."""
        ...


__all__ = ["EventBus"]
