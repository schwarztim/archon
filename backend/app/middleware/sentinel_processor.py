"""Structlog processor that formats log records into Azure Sentinel-compatible JSON.

Transforms structlog event dicts into the schema expected by Azure Log Analytics
(Sentinel). The processor maps standard log fields to Sentinel's required columns
and can be inserted into any structlog processor chain.

Configuration via environment variables:
    SENTINEL_WORKSPACE_ID  — Log Analytics workspace ID (informational, included in output)
    SENTINEL_LOG_TYPE      — Custom log type name (default: "ArchonAudit")

Usage — register in ``setup_logging()`` inside ``logging_config.py``::

    from app.middleware.sentinel_processor import sentinel_processor

    # Insert before the final renderer in the processor chain:
    processors=[
        ...
        sentinel_processor,
        structlog.processors.JSONRenderer(),
    ]
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
SENTINEL_WORKSPACE_ID: str = os.getenv("SENTINEL_WORKSPACE_ID", "")
SENTINEL_LOG_TYPE: str = os.getenv("SENTINEL_LOG_TYPE", "ArchonAudit")

_HOSTNAME: str = socket.gethostname()

# Map structlog/Python log levels → Sentinel severity strings
_LEVEL_MAP: dict[str, str] = {
    "debug": "Informational",
    "info": "Informational",
    "warning": "Warning",
    "warn": "Warning",
    "error": "Error",
    "critical": "Critical",
    "fatal": "Critical",
}


def sentinel_processor(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Re-key a structlog event dict into Azure Sentinel / Log Analytics format.

    Sentinel fields produced:
        TimeGenerated   — ISO-8601 UTC timestamp
        SourceSystem    — always ``"Archon"``
        Computer        — hostname of the emitting machine
        Category        — the ``SENTINEL_LOG_TYPE`` value
        Activity        — the original ``event`` (log message)
        Level           — mapped severity string
        CorrelationId   — ``request_id`` from the event (if present)

    All original keys are preserved so downstream processors / renderers
    still have access to the full context.
    """
    # TimeGenerated — prefer existing timestamp, else generate one
    timestamp = event_dict.get("timestamp")
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    event_dict["TimeGenerated"] = timestamp

    event_dict["SourceSystem"] = "Archon"
    event_dict["Computer"] = _HOSTNAME
    event_dict["Category"] = SENTINEL_LOG_TYPE
    event_dict["Activity"] = event_dict.get("event", "")

    # Map log level
    raw_level = event_dict.get("level", method_name or "info")
    event_dict["Level"] = _LEVEL_MAP.get(str(raw_level).lower(), "Informational")

    # CorrelationId — use request_id if available
    correlation_id = event_dict.get("request_id", event_dict.get("correlation_id", ""))
    event_dict["CorrelationId"] = correlation_id

    # Attach workspace ID when configured (useful for multi-workspace routing)
    if SENTINEL_WORKSPACE_ID:
        event_dict["WorkspaceId"] = SENTINEL_WORKSPACE_ID

    return event_dict


__all__ = [
    "SENTINEL_LOG_TYPE",
    "SENTINEL_WORKSPACE_ID",
    "sentinel_processor",
]
