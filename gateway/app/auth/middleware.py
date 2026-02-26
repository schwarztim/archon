"""EntraAuthMiddleware — validates Entra ID JWTs for the MCP Host Gateway.

In dev mode (AUTH_DEV_MODE=true) a simple HS256 token or the literal
string "dev-token" is accepted and a synthetic dev user is returned.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


def _decode_hs256_dev(token: str, secret: str) -> dict[str, Any] | None:
    """Try to decode a HS256 dev JWT.  Returns None on failure."""
    try:
        from jose import jwt

        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None


def _decode_entra_jwt(token: str, client_id: str, discovery_url: str) -> dict[str, Any]:
    """Validate an Entra ID RS256 JWT using OIDC discovery.

    Fetches JWKS on first call (cached by python-jose's internals).
    Raises :class:`HTTPException` 401 on failure.
    """
    try:
        import httpx
        from jose import jwt

        # Fetch JWKS URI from discovery document
        try:
            resp = httpx.get(discovery_url, timeout=10)
            resp.raise_for_status()
            jwks_uri = resp.json().get("jwks_uri", "")
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"OIDC discovery failed: {exc}") from exc

        if not jwks_uri:
            raise HTTPException(status_code=401, detail="OIDC discovery returned no jwks_uri")

        try:
            jwks_resp = httpx.get(jwks_uri, timeout=10)
            jwks_resp.raise_for_status()
            jwks = jwks_resp.json()
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"JWKS fetch failed: {exc}") from exc

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

    claims = _decode_entra_jwt(token, settings.oidc_client_id, settings.oidc_discovery_url)

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
