"""Tracing middleware — wraps every HTTP request in an ``http.request`` span.

Phase 5 / W5.2 — owned by Observability Squad. The middleware is the
outermost layer (registered last in :mod:`app.main`) so its span
covers every other middleware and the route handler.

Attributes set on the span:

* ``http.method``
* ``http.route``      — the request path
* ``http.status_code`` — populated from the response after the route runs
* ``tenant_id``       — when ``request.state.tenant_id`` is populated by
                        :class:`TenantMiddleware`
* ``correlation_id``  — when ``request.state.request_id`` is populated by
                        the request-id middleware in :mod:`app.main`

When tracing is disabled (no OTel SDK or
``ARCHON_TRACING_ENABLED=false``) the middleware is a no-op pass-through.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.services.tracing import is_tracing_enabled, set_attr, span

logger = logging.getLogger(__name__)


class TracingMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that opens an ``http.request`` span per request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Wrap the route handler in an ``http.request`` span."""
        if not is_tracing_enabled():
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        correlation_id = getattr(request.state, "request_id", None)

        async with span(
            "http.request",
            **{
                "http.method": request.method,
                "http.route": request.url.path,
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
            },
        ):
            response = await call_next(request)
            # Backfill status code now that the response is known.
            set_attr("http.status_code", response.status_code)
            return response


__all__ = ["TracingMiddleware"]
