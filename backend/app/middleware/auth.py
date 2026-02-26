"""JWT authentication middleware using Keycloak OIDC and Azure Entra ID."""

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
        "httpx is required for JWKS fetching. Install it with: pip install httpx"
    ) from exc

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

# ---------------------------------------------------------------------------
# Keycloak JWKS cache
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


# ---------------------------------------------------------------------------
# Azure Entra ID OIDC JWKS cache (separate from Keycloak — 1-hour TTL)
# ---------------------------------------------------------------------------

_entra_jwks_cache: dict[str, Any] | None = None
_entra_jwks_cache_ts: float = 0.0
_entra_jwks_lock = asyncio.Lock()
_ENTRA_JWKS_TTL_SECONDS: int = 3600  # 1 hour


async def _fetch_entra_jwks() -> dict[str, Any]:
    """Fetch JWKS keys from Entra ID via the OIDC discovery document.

    Resolves the ``jwks_uri`` from the discovery URL then caches the keyset
    for ``_ENTRA_JWKS_TTL_SECONDS`` (1 hour).  Returns an empty keyset if
    ``OIDC_DISCOVERY_URL`` is not configured.
    """
    global _entra_jwks_cache, _entra_jwks_cache_ts  # noqa: PLW0603

    if not settings.OIDC_DISCOVERY_URL:
        return {"keys": []}

    async with _entra_jwks_lock:
        now = time.monotonic()
        if (
            _entra_jwks_cache is not None
            and (now - _entra_jwks_cache_ts) < _ENTRA_JWKS_TTL_SECONDS
        ):
            return _entra_jwks_cache

        async with httpx.AsyncClient(timeout=10.0) as client:
            discovery_resp = await client.get(settings.OIDC_DISCOVERY_URL)
            discovery_resp.raise_for_status()
            discovery = discovery_resp.json()

            jwks_uri: str = discovery.get("jwks_uri", "")
            if not jwks_uri:
                logger.warning("Entra OIDC discovery document missing jwks_uri")
                return {"keys": []}

            jwks_resp = await client.get(jwks_uri)
            jwks_resp.raise_for_status()
            _entra_jwks_cache = jwks_resp.json()
            _entra_jwks_cache_ts = now
            logger.debug("Refreshed Entra ID JWKS key cache from %s", jwks_uri)
            return _entra_jwks_cache


async def _map_entra_groups_to_roles(
    group_oids: list[str],
    tenant_id: str,
) -> list[str]:
    """Resolve Entra group OIDs → Archon role names via GroupRoleMapping table.

    Returns a deduplicated list of role names.  Silently returns an empty list
    if the database is unavailable (e.g. during tests without DB).
    """
    if not group_oids or not tenant_id:
        return []

    try:
        from uuid import UUID as _UUID

        from sqlmodel import select

        from app.database import async_session_factory
        from app.models.custom_role import GroupRoleMapping

        # Validate tenant_id is a valid UUID before querying
        try:
            tenant_uuid = _UUID(tenant_id)
        except ValueError:
            return []

        async with async_session_factory() as session:
            stmt = select(GroupRoleMapping).where(
                GroupRoleMapping.tenant_id == tenant_uuid,
                GroupRoleMapping.group_oid.in_(group_oids),  # type: ignore[arg-type]
            )
            result = await session.exec(stmt)
            mappings = result.all()

        roles = list(dict.fromkeys(m.role_name for m in mappings))
        return roles
    except Exception:
        logger.debug("entra_group_mapping: could not resolve groups", exc_info=True)
        return []


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
    Tries validation tiers in order:

    1. HS256 dev-mode (using JWT_SECRET) — fastest, no network calls
    2. RS256 via Keycloak JWKS — for Keycloak-issued tokens
    3. RS256 via Azure Entra ID OIDC — when OIDC_DISCOVERY_URL is configured
    """
    # Fall back to cookie if no Bearer token
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        # Dev-mode bypass: return a synthetic admin user so every
        # authenticated route works without a real token / Keycloak.
        if settings.AUTH_DEV_MODE:
            logger.debug("Dev-mode auth bypass — returning synthetic admin user")
            return AuthenticatedUser(
                id="00000000-0000-0000-0000-000000000001",
                email="admin@archon.local",
                tenant_id="00000000-0000-0000-0000-000000000100",
                roles=["admin", "operator"],
                permissions=["*"],
                mfa_verified=True,
                session_id="dev-session",
            )
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

    # ── Tier 1: HS256 dev-mode token ────────────────────────────────
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

    # ── Tier 2: RS256 via Keycloak JWKS ─────────────────────────────
    if not payload:
        try:
            jwks = await _fetch_jwks()
            signing_key = _get_signing_key(jwks, token)
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
        except (JWTError, HTTPException):
            payload = {}  # fall through to Entra ID tier

    # ── Tier 3: RS256 via Azure Entra ID OIDC ───────────────────────
    if not payload and settings.OIDC_DISCOVERY_URL:
        try:
            entra_jwks = await _fetch_entra_jwks()
            signing_key = _get_signing_key(entra_jwks, token)
            # Entra ID tokens use the client_id (or api://<client_id>) as audience
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                options={
                    "verify_exp": True,
                    "verify_iss": False,  # issuer varies by tenant/cloud
                    "verify_aud": bool(settings.OIDC_CLIENT_ID),
                    **(
                        {"audience": settings.OIDC_CLIENT_ID}
                        if settings.OIDC_CLIENT_ID
                        else {}
                    ),
                },
            )
            logger.debug("Authenticated via Entra ID OIDC (sub=%s)", payload.get("sub"))
        except ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except (JWTError, HTTPException):
            payload = {}

    if not payload:
        raise credentials_exception

    user_id: str | None = payload.get("sub")

    # Entra ID tokens may use "preferred_username" or "upn" as the primary email
    email: str | None = (
        payload.get("email") or payload.get("preferred_username") or payload.get("upn")
    )

    if not user_id or not email:
        raise credentials_exception

    # Tenant resolution: explicit claim → oid fallback → realm name fallback
    tenant_id: str = payload.get("tenant_id", "")
    if not tenant_id:
        # Entra ID: tid claim is the directory tenant ID
        tenant_id = payload.get("tid", "")
    if not tenant_id:
        # Keycloak fallback: extract realm from issuer URL
        issuer: str = payload.get("iss", "")
        parts = issuer.rstrip("/").split("/")
        tenant_id = parts[-1] if parts else ""

    roles = _extract_roles(payload)

    # Entra ID: map groups claim (list of group OIDs) to Archon RBAC roles
    entra_groups: list[str] = payload.get("groups", [])
    if entra_groups and isinstance(entra_groups, list):
        group_roles = await _map_entra_groups_to_roles(entra_groups, tenant_id)
        # Merge without duplicates, preserving order
        roles = list(dict.fromkeys(roles + group_roles))

    permissions: list[str] = payload.get("permissions", [])

    # MFA: check mfa_verified claim (Keycloak) or amr claim (Entra ID)
    mfa_verified: bool = payload.get("mfa_verified", False)
    if not mfa_verified:
        # Entra ID Authentication Methods Reference
        amr: list[str] = payload.get("amr", [])
        if isinstance(amr, list) and any(
            method in amr for method in ("mfa", "ngcmfa", "rsa", "hwk", "face", "fido")
        ):
            mfa_verified = True

    # Entra ID: use oid as the stable user identifier when available
    stable_id: str = payload.get("oid", user_id)

    session_id: str = payload.get("sid", payload.get("session_id", ""))

    return AuthenticatedUser(
        id=stable_id,
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
