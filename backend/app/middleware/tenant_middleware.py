"""Tenant middleware — extracts tenant_id from the JWT and stamps request state.

Uses unverified claim extraction so it remains lightweight and does not
duplicate the full signature-validation logic owned by ``auth.py``.
Downstream middleware (e.g. DLPMiddleware) reads ``request.state.tenant_id``
set here.

Phase 4 / WS12 — DB-level tenant isolation:

* The middleware also writes the resolved tenant into
  :func:`app.services.tenant_context.set_current_tenant` so that every
  service / DB helper downstream of the request boundary can read it via
  :func:`get_current_tenant` without taking it as an explicit parameter.
* When ``ARCHON_ENTERPRISE_STRICT_TENANT=true``, the middleware refuses
  to serve tenant-scoped routes that arrive without a real tenant
  context (legacy ``"default"`` / ``"default-tenant"`` / zero-UUID
  fallbacks are rejected). Health probes and OpenAPI / docs paths bypass
  the gate.
"""

from __future__ import annotations

import logging
import os
import re

try:  # pragma: no cover -- prometheus is optional in local dev
    from prometheus_client import Counter

    _MISSING_TENANT_COUNTER: Counter | None = Counter(
        "archon_tenant_context_missing_total",
        "Tenant-scoped requests that arrived without a valid tenant context.",
        labelnames=("path", "outcome"),
    )
except Exception:  # noqa: BLE001  -- counter is purely observability
    _MISSING_TENANT_COUNTER = None

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

try:
    from jose import jwt
    from jose.exceptions import JWTError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "python-jose is required for tenant extraction. "
        "Install it with: pip install 'python-jose[cryptography]'"
    ) from exc

from app.services.tenant_context import (
    reset_tenant,
    set_current_tenant,
)

logger = logging.getLogger(__name__)

_SKIP_PATTERNS = re.compile(
    r"^/(healthz|readyz|livez|docs|redoc|openapi\.json|metrics|static)"
)

#: Sentinel emitted when the JWT does not carry a tenant claim. Strict
#: mode treats this — and the literal zero-UUID — as "no tenant".
_FALLBACK_TENANT_ID = "default"

#: Tenant strings that are NEVER acceptable in strict mode.
_REJECTED_TENANT_STRINGS: frozenset[str] = frozenset(
    {
        "",
        "default",
        "default-tenant",
        "00000000-0000-0000-0000-000000000000",
    }
)


# ─── Strict-mode flag ─────────────────────────────────────────────────


def _strict_enabled() -> bool:
    """Return ``True`` when strict tenant enforcement is on.

    Defaults to ``True`` in production / staging environments
    (``ARCHON_ENV in {production, staging}``) and ``False`` everywhere
    else, unless ``ARCHON_ENTERPRISE_STRICT_TENANT`` is set explicitly.
    """
    raw = os.getenv("ARCHON_ENTERPRISE_STRICT_TENANT", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    env = os.getenv("ARCHON_ENV", "dev").strip().lower()
    return env in {"production", "staging"}


def _is_rejected_tenant(value: str) -> bool:
    """Return ``True`` if ``value`` is a known fallback / sentinel."""
    return value.strip().lower() in _REJECTED_TENANT_STRINGS


def _record_missing(path: str, outcome: str) -> None:
    """Increment the ``archon_tenant_context_missing_total`` counter."""
    if _MISSING_TENANT_COUNTER is None:
        return
    try:
        _MISSING_TENANT_COUNTER.labels(path=path, outcome=outcome).inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("missing-tenant counter increment failed: %s", exc)


# ─── JWT extraction ───────────────────────────────────────────────────


def _extract_tenant_id_from_token(token: str) -> str:
    """Return the tenant_id embedded in the JWT without verifying the signature.

    Tries the ``tenant_id`` claim first; falls back to the last path segment
    of the issuer URL (Keycloak realm name convention).  Returns the fallback
    sentinel when neither is present or the token is malformed.
    """
    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        return _FALLBACK_TENANT_ID

    tenant_id: str = claims.get("tenant_id", "")
    if tenant_id:
        return tenant_id

    issuer: str = claims.get("iss", "")
    parts = issuer.rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else _FALLBACK_TENANT_ID


def _resolve_bearer_token(request: Request) -> str | None:
    """Extract a raw JWT string from the Authorization header or cookie."""
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return request.cookies.get("access_token")


# ─── Middleware ───────────────────────────────────────────────────────


class TenantMiddleware(BaseHTTPMiddleware):
    """Stamps ``request.state.tenant_id`` from the JWT on every request.

    Skips health-probe, documentation, and metrics paths where no token
    is expected. In **non-strict** mode it falls back to the legacy
    ``"default"`` sentinel so older services keep working. In **strict**
    mode (``ARCHON_ENTERPRISE_STRICT_TENANT=true``) it returns
    ``401 Unauthorized`` for any tenant-scoped route that lacks a real
    tenant.

    Always writes the resolved value into the
    :mod:`app.services.tenant_context` ContextVar so async code paths
    downstream of the middleware can read it without explicit threading.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Set tenant_id on request state before passing to the next layer."""
        path = request.url.path
        if _SKIP_PATTERNS.match(path):
            return await call_next(request)

        token = _resolve_bearer_token(request)
        tenant_id = (
            _extract_tenant_id_from_token(token)
            if token
            else _FALLBACK_TENANT_ID
        )

        # Strict mode: reject the request before it touches any
        # tenant-scoped infrastructure.
        if _strict_enabled() and _is_rejected_tenant(tenant_id):
            _record_missing(path, "rejected_strict")
            logger.warning(
                "tenant_middleware: rejecting request %s — no valid tenant "
                "(strict mode active)",
                path,
            )
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Authentication required: no tenant context. "
                        "Strict enterprise mode rejects the legacy "
                        "default-tenant / zero-UUID fallback."
                    ),
                    "code": "tenant_context_missing",
                },
            )

        request.state.tenant_id = tenant_id

        # Bind the ContextVar so downstream services see the same tenant
        # without taking it as a parameter on every call. The token is
        # released in ``finally`` so it never leaks into the next
        # request handled by the same worker.
        ctx_token = set_current_tenant(tenant_id)
        try:
            return await call_next(request)
        finally:
            try:
                reset_tenant(ctx_token)
            except (LookupError, ValueError) as exc:
                logger.debug(
                    "tenant_middleware: contextvar reset failed: %s", exc,
                )


__all__ = ["TenantMiddleware"]
