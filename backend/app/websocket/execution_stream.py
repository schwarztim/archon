"""ExecutionStreamManager — Redis-backed WebSocket event streaming.

This module re-exports :class:`~app.websocket.manager.ExecutionStreamManager`
(defined in ``manager.py``) and exposes the module-level singleton used by the
WebSocket route and execution runners.

See ``manager.py`` for full implementation details.
"""

from app.websocket.manager import ExecutionStreamManager

__all__ = ["ExecutionStreamManager", "execution_stream"]

#: Shared singleton used by the WebSocket route and execution runners.
execution_stream = ExecutionStreamManager()
