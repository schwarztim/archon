"""WebSocket package — exports the singleton connection manager instances.

``manager`` is exposed for backward compatibility.  It is now the
:class:`~app.websocket.execution_stream.ExecutionStreamManager` singleton
(``execution_stream``) which implements the same ``._connections``,
``._tenant_rooms``, ``._connection_tenants``, ``send_event()``, and
``disconnect()`` interface as the original ``ConnectionManager``.

Code that previously did::

    from app.websocket import manager
    await manager.send_event(...)

continues to work unchanged.
"""

from app.websocket.manager import ConnectionManager
from app.websocket.execution_stream import ExecutionStreamManager, execution_stream

# Backward-compatible alias
manager: ExecutionStreamManager = execution_stream

__all__ = ["manager", "ConnectionManager", "ExecutionStreamManager", "execution_stream"]
