"""WebSocket package — exports the singleton ConnectionManager instance."""

from app.websocket.manager import ConnectionManager

manager = ConnectionManager()

__all__ = ["manager"]
