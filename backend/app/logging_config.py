"""Structured logging configuration for Archon.

Provides a structlog processor chain with JSON output, correlation IDs
(request_id, tenant_id, user_id), and a ``get_logger`` helper.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

# ---------------------------------------------------------------------------
# Context variables — set by middleware, read by log processors
# ---------------------------------------------------------------------------
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="")


def _add_correlation_ids(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict,
) -> dict:
    """Inject correlation IDs from contextvars into every log event."""
    event_dict.setdefault("request_id", request_id_ctx.get(""))
    event_dict.setdefault("tenant_id", tenant_id_ctx.get(""))
    event_dict.setdefault("user_id", user_id_ctx.get(""))
    return event_dict


def setup_logging(*, log_level: str = "INFO") -> None:
    """Configure structlog and stdlib logging for JSON output."""
    from app.middleware.sentinel_processor import sentinel_processor

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_correlation_ids,
        sentinel_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
        if sys.stderr.isatty()
        else structlog.processors.JSONRenderer(),
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level.upper())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for the given module name."""
    return structlog.get_logger(name)


__all__ = [
    "get_logger",
    "request_id_ctx",
    "setup_logging",
    "tenant_id_ctx",
    "user_id_ctx",
]
