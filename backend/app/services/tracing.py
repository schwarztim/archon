"""Tracing wrapper. Falls back to no-op if OpenTelemetry is not installed.

Phase 5 / W5.2 — distributed tracing for the Archon control plane. The
goal is a single, dependency-light entry point (``span``) that:

* uses OpenTelemetry when the SDK is importable, and
* degrades to a true no-op (zero-allocation, zero-overhead) when the
  SDK is missing or tracing is disabled via ``ARCHON_TRACING_ENABLED=false``.

Design notes
------------

* Public surface: :func:`is_tracing_enabled`, :func:`span`,
  :func:`add_event`, :func:`set_attr`, :func:`get_tracer`,
  :func:`configure_tracing`. Anything else is private.
* All call sites use ``async with span(...)`` regardless of whether
  tracing is on. The contextmanager yields ``None`` in no-op mode so
  callers must treat the yielded span as optional.
* Attribute coercion (:func:`_safe_attrs`) drops ``None``, casts UUID
  to ``str``, and truncates strings >256 chars. OTel rejects values
  that aren't ``str``/``bool``/``int``/``float`` (or sequences of
  those), so coercion happens before they reach the SDK.
* On exception the span is marked ``Status(StatusCode.ERROR)`` and the
  exception is recorded; the exception still propagates.
* Production deployments configure exporters via the standard OTel
  env vars (``OTEL_EXPORTER_OTLP_ENDPOINT`` etc.). When
  ``ARCHON_OTEL_EXPORTER=otlp`` is set we install the OTLP HTTP
  exporter; otherwise we install an in-memory exporter (useful for
  tests).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OTel availability detection
# ---------------------------------------------------------------------------

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status, StatusCode

    _TRACING_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised when SDK is absent
    _otel_trace = None  # type: ignore[assignment]
    Status = None  # type: ignore[assignment]
    StatusCode = None  # type: ignore[assignment]
    _TRACING_AVAILABLE = False

_TRACER_NAME = "archon"

# Cached in-memory exporter handle (test introspection).
_IN_MEMORY_EXPORTER: Any = None
_PROVIDER_CONFIGURED: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_tracing_enabled() -> bool:
    """Return ``True`` when OTel is importable and not explicitly disabled."""
    if not _TRACING_AVAILABLE:
        return False
    raw = os.getenv("ARCHON_TRACING_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def get_tracer() -> Any:
    """Return the project tracer, or ``None`` when tracing is disabled."""
    if not is_tracing_enabled():
        return None
    return _otel_trace.get_tracer(_TRACER_NAME)


@asynccontextmanager
async def span(name: str, **attrs: Any) -> AsyncIterator[Any]:
    """Async span context manager.

    Sets ``attrs`` on the span at start. Records exceptions and marks
    the span as ``ERROR`` on exception (then re-raises). When tracing
    is disabled the manager yields ``None`` immediately.
    """
    if not is_tracing_enabled():
        yield None
        return

    tracer = _otel_trace.get_tracer(_TRACER_NAME)
    safe = _safe_attrs(attrs)
    with tracer.start_as_current_span(name, attributes=safe) as current:
        try:
            yield current
        except Exception as exc:  # noqa: BLE001 — record & re-raise
            try:
                current.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
                current.record_exception(exc)
            except Exception as set_exc:  # noqa: BLE001
                logger.debug("span.set_status failed: %s", set_exc)
            raise


@contextmanager
def sync_span(name: str, **attrs: Any) -> Iterator[Any]:
    """Synchronous twin of :func:`span` for non-async call sites."""
    if not is_tracing_enabled():
        yield None
        return

    tracer = _otel_trace.get_tracer(_TRACER_NAME)
    safe = _safe_attrs(attrs)
    with tracer.start_as_current_span(name, attributes=safe) as current:
        try:
            yield current
        except Exception as exc:  # noqa: BLE001
            try:
                current.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
                current.record_exception(exc)
            except Exception as set_exc:  # noqa: BLE001
                logger.debug("sync_span.set_status failed: %s", set_exc)
            raise


def add_event(name: str, **attrs: Any) -> None:
    """Add an event to the current span. No-op when tracing is disabled."""
    if not is_tracing_enabled():
        return
    current = _otel_trace.get_current_span()
    if current is None:
        return
    try:
        current.add_event(name, attributes=_safe_attrs(attrs))
    except Exception as exc:  # noqa: BLE001
        logger.debug("add_event failed: %s", exc)


def set_attr(key: str, value: Any) -> None:
    """Set a single attribute on the current span."""
    if not is_tracing_enabled():
        return
    current = _otel_trace.get_current_span()
    if current is None:
        return
    safe = _safe_attrs({key: value})
    if key not in safe:
        return
    try:
        current.set_attribute(key, safe[key])
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_attr failed: %s", exc)


# ---------------------------------------------------------------------------
# Attribute coercion
# ---------------------------------------------------------------------------


def _safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Coerce values to OTel-safe types; truncate long strings; drop None.

    OTel only accepts ``str``/``bool``/``int``/``float`` (or homogeneous
    sequences thereof). Anything else is rendered with ``str()`` and
    truncated to 256 chars.
    """
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, UUID):
            out[key] = str(value)
        elif isinstance(value, str):
            out[key] = value[:256]
        elif isinstance(value, (list, tuple)):
            # OTel sequences must be homogeneous — fall back to str repr
            try:
                seq = [str(item)[:256] for item in value]
                out[key] = seq
            except Exception:  # noqa: BLE001
                out[key] = str(value)[:256]
        else:
            try:
                out[key] = str(value)[:256]
            except Exception:  # noqa: BLE001
                continue
    return out


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------


def configure_tracing(*, force_in_memory: bool = False) -> Any:
    """Install a TracerProvider. Idempotent.

    Returns the in-memory exporter when one is installed (so tests can
    introspect spans), or ``None`` when the OTLP exporter is in use.

    Production deployments are expected to configure an OTLP exporter
    via the standard OTel environment variables (``OTEL_EXPORTER_OTLP_ENDPOINT``
    etc.) and set ``ARCHON_OTEL_EXPORTER=otlp``. Otherwise an in-memory
    exporter is installed.
    """
    global _IN_MEMORY_EXPORTER, _PROVIDER_CONFIGURED

    if not _TRACING_AVAILABLE:
        return None
    if _PROVIDER_CONFIGURED and not force_in_memory:
        return _IN_MEMORY_EXPORTER

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    resource = Resource.create({"service.name": "archon"})
    provider = TracerProvider(resource=resource)

    exporter_kind = os.getenv("ARCHON_OTEL_EXPORTER", "memory").strip().lower()
    in_memory: Any = None

    if exporter_kind == "otlp" and not force_in_memory:
        try:  # pragma: no cover — only exercised when OTLP is wired
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
        except ImportError as exc:
            logger.warning("OTLP exporter requested but unavailable: %s", exc)
            in_memory = _make_in_memory_exporter()
            if in_memory is not None:
                provider.add_span_processor(SimpleSpanProcessor(in_memory))
    else:
        in_memory = _make_in_memory_exporter()
        if in_memory is not None:
            provider.add_span_processor(SimpleSpanProcessor(in_memory))

    _otel_trace.set_tracer_provider(provider)
    _IN_MEMORY_EXPORTER = in_memory
    _PROVIDER_CONFIGURED = True
    return in_memory


def _make_in_memory_exporter() -> Any:
    """Return an in-memory exporter, or ``None`` if it cannot be imported."""
    try:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
    except ImportError:  # pragma: no cover
        return None
    return InMemorySpanExporter()


def get_in_memory_exporter() -> Any:
    """Return the in-memory exporter installed by :func:`configure_tracing`."""
    return _IN_MEMORY_EXPORTER


def reset_tracing_for_tests() -> None:
    """Reset module-level state. Intended for test teardown only."""
    global _IN_MEMORY_EXPORTER, _PROVIDER_CONFIGURED
    _IN_MEMORY_EXPORTER = None
    _PROVIDER_CONFIGURED = False


__all__ = [
    "add_event",
    "configure_tracing",
    "get_in_memory_exporter",
    "get_tracer",
    "is_tracing_enabled",
    "reset_tracing_for_tests",
    "set_attr",
    "span",
    "sync_span",
]
