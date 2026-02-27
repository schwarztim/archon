"""EntraAuthMiddleware — validates Entra ID JWTs for the MCP Host Gateway.

In dev mode (AUTH_DEV_MODE=true) a simple HS256 token or the literal
string "dev-token" is accepted and a synthetic dev user is returned.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# ── JWKS cache (1-hour TTL) ─────────────────────────────────────────────────

_jwks_cache: dict[str, Any] | None = None
_jwks_cache_ts: float = 0.0
_jwks_lock = asyncio.Lock()
_JWKS_TTL_SECONDS: int = 3600  # 1 hour


async def _fetch_entra_jwks(discovery_url: str) -> dict[str, Any]:
    """Fetch JWKS from the Entra ID OIDC discovery endpoint.

    Resolves ``jwks_uri`` from the discovery document then caches the keyset
    for ``_JWKS_TTL_SECONDS`` (1 hour) to avoid blocking the event loop on
    every request.
    """
    global _jwks_cache, _jwks_cache_ts  # noqa: PLW0603

    async with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache is not None and (now - _jwks_cache_ts) < _JWKS_TTL_SECONDS:
            return _jwks_cache

        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                discovery_resp = await client.get(discovery_url)
                discovery_resp.raise_for_status()
                discovery = discovery_resp.json()

                jwks_uri: str = discovery.get("jwks_uri", "")
                if not jwks_uri:
                    raise HTTPException(
                        status_code=401,
                        detail="OIDC discovery returned no jwks_uri",
                    )

                jwks_resp = await client.get(jwks_uri)
                jwks_resp.raise_for_status()
                _jwks_cache = jwks_resp.json()
                _jwks_cache_ts = now
                logger.debug("Refreshed gateway JWKS cache from %s", jwks_uri)
                return _jwks_cache
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"JWKS fetch failed: {exc}") from exc


def _decode_hs256_dev(token: str, secret: str) -> dict[str, Any] | None:
    """Try to decode a HS256 dev JWT.  Returns None on failure."""
    try:
        from jose import jwt

        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None


async def _decode_entra_jwt(token: str, client_id: str, discovery_url: str) -> dict[str, Any]:
    """Validate an Entra ID RS256 JWT using OIDC discovery.

    Fetches JWKS asynchronously with a 1-hour module-level TTL cache to avoid
    blocking the event loop.  Raises :class:`HTTPException` 401 on failure.
    """
    try:
        from jose import jwt

        jwks = await _fetch_entra_jwks(discovery_url)

        return jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=client_id,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"JWT validation failed: {exc}") from exc


async def get_current_user(
    request: Request,
) -> GatewayUser:  # type: ignore[name-defined]  # noqa: F821
    """FastAPI dependency that extracts and validates the caller identity.

    Resolution order:
    1. If AUTH_DEV_MODE=true — accept "dev-token" or any valid HS256 dev JWT.
    2. Otherwise — validate Entra ID RS256 JWT via OIDC discovery.
    """
    from app.auth.models import GatewayUser
    from app.config import get_settings

    settings = get_settings()

    # Extract bearer token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    token: str | None = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()

    # ── Dev bypass ────────────────────────────────────────────────────
    if settings.auth_dev_mode:
        if token == "dev-token" or token is None:
            return GatewayUser(
                oid="dev-oid",
                email="dev@localhost",
                name="Dev User",
                groups=["MCP-Users-All", "MCP-Users-Finance"],
                roles=["admin"],
                tenant_id="dev-tenant",
                is_dev=True,
            )

        # Try HS256 dev JWT
        claims = _decode_hs256_dev(token, settings.jwt_secret)
        if claims:
            return GatewayUser(
                oid=claims.get("sub", "dev-oid"),
                email=claims.get("email", "dev@localhost"),
                name=claims.get("name", "Dev User"),
                groups=claims.get("groups", []),
                roles=claims.get("roles", []),
                tenant_id=claims.get("tid", "dev-tenant"),
                is_dev=True,
            )

        # Fall through to Entra validation if dev JWT fails but token is present
        if not settings.oidc_discovery_url:
            raise HTTPException(status_code=401, detail="Invalid dev token and OIDC not configured")

    # ── Entra ID JWT validation ────────────────────────────────────────
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer token")

    if not settings.oidc_discovery_url:
        raise HTTPException(status_code=503, detail="OIDC not configured. Set OIDC_DISCOVERY_URL.")

    claims = await _decode_entra_jwt(token, settings.oidc_client_id, settings.oidc_discovery_url)

    # Extract groups — may be IDs or names depending on token config
    groups: list[str] = claims.get("groups", [])
    roles: list[str] = claims.get("roles", []) or claims.get("appRoles", [])

    return GatewayUser(
        oid=claims.get("oid", claims.get("sub", "")),
        email=claims.get("upn", claims.get("email", claims.get("preferred_username", ""))),
        name=claims.get("name", ""),
        groups=groups,
        roles=roles,
        tenant_id=claims.get("tid", ""),
        is_dev=False,
    )
