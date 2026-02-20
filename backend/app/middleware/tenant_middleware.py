"""Tenant middleware — extracts tenant_id from the JWT and stamps request state.

Uses unverified claim extraction so it remains lightweight and does not
duplicate the full signature-validation logic owned by ``auth.py``.
Downstream middleware (e.g. DLPMiddleware) reads ``request.state.tenant_id``
set here.
"""

from __future__ import annotations

import logging
import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

try:
    from jose import jwt
    from jose.exceptions import JWTError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "python-jose is required for tenant extraction. "
        "Install it with: pip install 'python-jose[cryptography]'"
    ) from exc

logger = logging.getLogger(__name__)

_SKIP_PATTERNS = re.compile(
    r"^/(healthz|readyz|livez|docs|redoc|openapi\.json|metrics|static)"
)

_FALLBACK_TENANT_ID = "default"


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


class TenantMiddleware(BaseHTTPMiddleware):
    """Stamps ``request.state.tenant_id`` from the JWT on every request.

    Skips health-probe, documentation, and metrics paths where no token
    is expected.  Never raises — if the token is absent or unreadable the
    state is set to the fallback sentinel so downstream code always has a
    value to work with.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Set tenant_id on request state before passing to the next layer."""
        if _SKIP_PATTERNS.match(request.url.path):
            return await call_next(request)

        token = _resolve_bearer_token(request)
        tenant_id = (
            _extract_tenant_id_from_token(token)
            if token
            else _FALLBACK_TENANT_ID
        )

        request.state.tenant_id = tenant_id
        return await call_next(request)
