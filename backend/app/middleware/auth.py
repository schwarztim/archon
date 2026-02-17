"""JWT authentication middleware using Keycloak OIDC."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.config import settings
from app.interfaces.models.enterprise import AuthenticatedUser

try:
    from jose import JWTError, jwt
    from jose.exceptions import ExpiredSignatureError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "python-jose is required for JWT validation. "
        "Install it with: pip install 'python-jose[cryptography]'"
    ) from exc

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "httpx is required for JWKS fetching. "
        "Install it with: pip install httpx"
    ) from exc

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------

_jwks_cache: dict[str, Any] | None = None
_jwks_cache_ts: float = 0.0
_jwks_lock = asyncio.Lock()
_JWKS_TTL_SECONDS: int = 300  # 5 minutes


async def _fetch_jwks() -> dict[str, Any]:
    """Fetch JWKS keys from Keycloak, with TTL-based caching."""
    global _jwks_cache, _jwks_cache_ts  # noqa: PLW0603

    async with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache is not None and (now - _jwks_cache_ts) < _JWKS_TTL_SECONDS:
            return _jwks_cache

        jwks_url = f"{settings.KEYCLOAK_URL}/protocol/openid-connect/certs"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_cache_ts = now
            logger.debug("Refreshed JWKS key cache from %s", jwks_url)
            return _jwks_cache


def _get_signing_key(jwks: dict[str, Any], token: str) -> dict[str, Any]:
    """Select the correct signing key from a JWKS keyset by kid header."""
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
        ) from exc

    kid = unverified_header.get("kid")
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token signing key not found in JWKS",
    )


def _extract_roles(payload: dict[str, Any]) -> list[str]:
    """Extract roles from JWT realm_access and resource_access claims."""
    roles: list[str] = []

    realm_access = payload.get("realm_access")
    if isinstance(realm_access, dict):
        roles.extend(realm_access.get("roles", []))

    resource_access = payload.get("resource_access")
    if isinstance(resource_access, dict):
        for _client, access in resource_access.items():
            if isinstance(access, dict):
                roles.extend(access.get("roles", []))

    return list(dict.fromkeys(roles))  # deduplicate, preserve order


# ---------------------------------------------------------------------------
# Core dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
) -> AuthenticatedUser:
    """Validate a JWT and return an ``AuthenticatedUser``.

    Accepts token from Authorization header or access_token cookie.
    Tries HS256 dev-mode validation first (using JWT_SECRET), then
    falls back to RS256 via Keycloak JWKS.
    """
    # Fall back to cookie if no Bearer token
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # ── Try HS256 dev-mode token first ──────────────────────────────
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            options={
                "verify_exp": True,
                "verify_iss": False,
                "verify_aud": False,
            },
        )
    except (JWTError, ExpiredSignatureError):
        payload = {}  # fall through to Keycloak JWKS path

    # ── Fall back to RS256 via Keycloak JWKS ────────────────────────
    if not payload:
        jwks = await _fetch_jwks()
        signing_key = _get_signing_key(jwks, token)

        try:
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[settings.JWT_ALGORITHM],
                audience="account",
                issuer=settings.KEYCLOAK_URL,
                options={
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except JWTError as exc:
            raise credentials_exception from exc

    user_id: str | None = payload.get("sub")
    email: str | None = payload.get("email")
    if not user_id or not email:
        raise credentials_exception

    # Tenant resolution: explicit claim → realm name fallback
    tenant_id: str = payload.get("tenant_id", "")
    if not tenant_id:
        # Fall back to Keycloak realm from issuer URL path segment
        issuer: str = payload.get("iss", "")
        parts = issuer.rstrip("/").split("/")
        tenant_id = parts[-1] if parts else ""

    roles = _extract_roles(payload)
    permissions: list[str] = payload.get("permissions", [])
    mfa_verified: bool = payload.get("mfa_verified", False)
    session_id: str = payload.get("sid", payload.get("session_id", ""))

    return AuthenticatedUser(
        id=user_id,
        email=email,
        tenant_id=tenant_id,
        roles=roles,
        permissions=permissions,
        mfa_verified=mfa_verified,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Convenience dependencies
# ---------------------------------------------------------------------------


async def require_auth(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """FastAPI dependency that returns ``AuthenticatedUser`` or raises 401."""
    return user


async def require_mfa(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """FastAPI dependency that enforces MFA verification on the token.

    Returns the authenticated user if ``mfa_verified`` is ``True``,
    otherwise raises HTTP 403.
    """
    if not user.mfa_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-factor authentication required",
        )
    return user
