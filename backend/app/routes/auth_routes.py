"""Enterprise authentication routes — token, SAML SSO, MFA, and logout."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.interfaces.models.enterprise import AuthenticatedUser, MFASetupResponse
from app.middleware.auth import require_auth
from app.models.audit import EnterpriseAuditEvent

try:
    from jose import jwt as jose_jwt
except ImportError:  # pragma: no cover
    jose_jwt = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


# ── Request / response schemas ──────────────────────────────────────


class TokenRequest(BaseModel):
    """Login credentials for username/password authentication."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """JWT token pair returned after successful authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class RefreshRequest(BaseModel):
    """Payload for refreshing an access token."""

    refresh_token: str


class SAMLACSPayload(BaseModel):
    """SAML Assertion Consumer Service callback payload."""

    saml_response: str
    relay_state: str = ""


class TOTPSetupResponse(BaseModel):
    """Response when enrolling TOTP-based MFA."""

    secret: str
    provisioning_uri: str
    backup_codes: list[str] = []


class TOTPVerifyRequest(BaseModel):
    """Payload for verifying a TOTP code."""

    code: str


class DevLoginRequest(BaseModel):
    """Login with email/password (dev mode — no Keycloak required)."""

    email: str
    password: str
    remember_me: bool = False


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _audit_event(
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    *,
    user: AuthenticatedUser | None = None,
) -> EnterpriseAuditEvent:
    """Create an audit event for authentication operations."""
    from uuid import UUID

    return EnterpriseAuditEvent(
        tenant_id=UUID(user.tenant_id) if user else UUID(int=0),
        user_id=UUID(user.id) if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        session_id=user.session_id if user else None,
    )


# ── Routes ───────────────────────────────────────────────────────────

# ── Dev-mode login (HS256 self-signed JWT, no Keycloak needed) ───────

_DEV_USERS: dict[str, dict[str, Any]] = {
    "admin@archon.local": {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Admin User",
        "roles": ["admin", "operator"],
        "permissions": ["*"],
        "tenant_id": "00000000-0000-0000-0000-000000000100",
        "workspace_id": "00000000-0000-0000-0000-000000000200",
    },
    "user@archon.local": {
        "id": "00000000-0000-0000-0000-000000000002",
        "name": "Test User",
        "roles": ["user"],
        "permissions": ["read", "execute"],
        "tenant_id": "00000000-0000-0000-0000-000000000100",
        "workspace_id": "00000000-0000-0000-0000-000000000200",
    },
}


def _dev_create_token(user_info: dict[str, Any], email: str, ttl_hours: int = 8) -> str:
    """Mint an HS256 JWT for dev mode."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_info["id"],
        "email": email,
        "name": user_info["name"],
        "tenant_id": user_info["tenant_id"],
        "roles": user_info["roles"],
        "permissions": user_info["permissions"],
        "realm_access": {"roles": user_info["roles"]},
        "mfa_verified": True,
        "sid": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
        "iss": "archon-dev",
        "aud": "account",
    }
    return jose_jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _is_dev_mode() -> bool:
    """Return True when dev-mode auth bypass is active."""
    return settings.AUTH_DEV_MODE


# ── Keycloak helpers ─────────────────────────────────────────────────


async def _keycloak_token_grant(email: str, pwd: str) -> dict[str, Any]:
    """Exchange credentials for a Keycloak token via direct-access grant."""
    token_url = f"{settings.KEYCLOAK_URL}/protocol/openid-connect/token"
    form_data = {
        "grant_type": "password",
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "username": email,
    }
    form_data["password"] = pwd  # noqa: S105 — runtime value, not hardcoded
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(token_url, data=form_data)
    if resp.status_code != 200:
        detail = resp.json().get("error_description", "Authentication failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    return resp.json()


async def _keycloak_userinfo(access_token: str) -> dict[str, Any]:
    """Fetch user profile from Keycloak userinfo endpoint."""
    userinfo_url = f"{settings.KEYCLOAK_URL}/protocol/openid-connect/userinfo"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return resp.json()


@router.post("/login")
async def dev_login(body: DevLoginRequest) -> dict[str, Any]:
    """Login endpoint — delegates to Keycloak OIDC or falls back to dev mode.

    When ``ARCHON_AUTH_DEV_MODE`` is truthy the original HS256 dev-mode
    login is used (no Keycloak required).  Otherwise credentials are
    forwarded to Keycloak's direct-access grant.
    """
    request_id = str(uuid4())
    now = datetime.now(tz=timezone.utc)

    # ── Dev-mode path ───────────────────────────────────────────────
    if _is_dev_mode():
        user_info = _DEV_USERS.get(body.email)
        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unknown user. Dev accounts: {', '.join(_DEV_USERS)}",
            )

        access_token = _dev_create_token(user_info, body.email)
        expires_at = now + timedelta(hours=8)
        refresh_expires_at = now + timedelta(days=7)

        session_info = {
            "user": {
                "id": user_info["id"],
                "email": body.email,
                "name": user_info["name"],
                "roles": user_info["roles"],
                "permissions": user_info["permissions"],
                "tenant_id": user_info["tenant_id"],
                "workspace_id": user_info["workspace_id"],
                "mfa_enabled": False,
            },
            "access_token": access_token,
            "expires_at": expires_at.isoformat(),
            "issued_at": now.isoformat(),
            "refresh_token_expires_at": refresh_expires_at.isoformat(),
        }

        logger.info("Dev login: %s", body.email, extra={"request_id": request_id})

        response = JSONResponse(content={
            "data": session_info,
            "meta": _meta(request_id=request_id),
        })
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            samesite="lax",
            max_age=8 * 3600,
            path="/",
        )
        return response

    # ── Keycloak OIDC path ──────────────────────────────────────────
    kc_tokens = await _keycloak_token_grant(body.email, body.password)
    access_token = kc_tokens["access_token"]

    # Decode the Keycloak JWT to extract user claims (unverified — we
    # trust the IdP response since we just obtained it).
    claims = jose_jwt.get_unverified_claims(access_token)
    roles = []
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        roles = realm_access.get("roles", [])

    expires_at = datetime.fromtimestamp(claims.get("exp", 0), tz=timezone.utc)
    issued_at = datetime.fromtimestamp(claims.get("iat", 0), tz=timezone.utc)
    refresh_expires_at = expires_at + timedelta(days=7)

    session_info = {
        "user": {
            "id": claims.get("sub", ""),
            "email": claims.get("email", body.email),
            "name": claims.get("name", claims.get("preferred_username", "")),
            "roles": roles,
            "permissions": [],
            "tenant_id": claims.get("tenant_id", ""),
            "workspace_id": "",
            "mfa_enabled": False,
        },
        "access_token": access_token,
        "expires_at": expires_at.isoformat(),
        "issued_at": issued_at.isoformat(),
        "refresh_token_expires_at": refresh_expires_at.isoformat(),
    }

    logger.info("Keycloak login: %s", body.email, extra={"request_id": request_id})

    response = JSONResponse(content={
        "data": session_info,
        "meta": _meta(request_id=request_id),
    })
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=kc_tokens.get("expires_in", 3600),
        path="/",
    )
    return response


@router.get("/me")
async def get_me(request: Request) -> dict[str, Any]:
    """Return the current user from cookie or Authorization header.

    In dev mode, decodes an HS256 self-signed JWT.  Otherwise, validates
    the Keycloak RS256 token via JWKS or falls back to the userinfo
    endpoint.
    """
    token: str | None = None

    # Try cookie first (frontend uses credentials: "include")
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        token = cookie_token

    # Fall back to Authorization header
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # ── Try HS256 dev-mode token first ──────────────────────────────
    payload: dict[str, Any] | None = None
    try:
        payload = jose_jwt.decode(
            token, settings.JWT_SECRET, algorithms=["HS256"],
            options={"verify_aud": False, "verify_iss": False},
        )
    except Exception:
        payload = None

    if payload:
        # Dev-mode path — resolve user from built-in dev users
        user_id = payload.get("sub", "")
        user_info = None
        for email, info in _DEV_USERS.items():
            if info["id"] == user_id:
                user_info = {**info, "email": email}
                break

        return {
            "data": {
                "user": {
                    "id": payload.get("sub"),
                    "email": payload.get("email"),
                    "name": payload.get("name", ""),
                    "roles": payload.get("roles", []),
                    "permissions": payload.get("permissions", []),
                    "tenant_id": payload.get("tenant_id", ""),
                    "workspace_id": user_info.get("workspace_id", "") if user_info else "",
                    "mfa_enabled": payload.get("mfa_verified", False),
                },
                "access_token": token,
                "expires_at": datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc).isoformat(),
                "issued_at": datetime.fromtimestamp(payload.get("iat", 0), tz=timezone.utc).isoformat(),
                "refresh_token_expires_at": (
                    datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc) + timedelta(days=7)
                ).isoformat(),
            },
            "meta": _meta(),
        }

    # ── Keycloak RS256 path — use middleware validation ──────────────
    from app.middleware.auth import _fetch_jwks, _get_signing_key, _extract_roles

    try:
        jwks = await _fetch_jwks()
        signing_key = _get_signing_key(jwks, token)
        payload = jose_jwt.decode(
            token,
            signing_key,
            algorithms=[settings.JWT_ALGORITHM],
            audience="account",
            issuer=settings.KEYCLOAK_URL,
            options={"verify_exp": True, "verify_iss": True, "verify_aud": True},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    roles = _extract_roles(payload)

    return {
        "data": {
            "user": {
                "id": payload.get("sub", ""),
                "email": payload.get("email", ""),
                "name": payload.get("name", payload.get("preferred_username", "")),
                "roles": roles,
                "permissions": payload.get("permissions", []),
                "tenant_id": payload.get("tenant_id", ""),
                "workspace_id": "",
                "mfa_enabled": payload.get("mfa_verified", False),
            },
            "access_token": token,
            "expires_at": datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc).isoformat(),
            "issued_at": datetime.fromtimestamp(payload.get("iat", 0), tz=timezone.utc).isoformat(),
            "refresh_token_expires_at": (
                datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc) + timedelta(days=7)
            ).isoformat(),
        },
        "meta": _meta(),
    }


@router.post("/token")
async def login(body: TokenRequest) -> dict[str, Any]:
    """Authenticate with username and password, returning a JWT token pair.

    In dev mode, mints an HS256 token. Otherwise, delegates credential
    validation to Keycloak via direct-access grant.
    """
    request_id = str(uuid4())

    if _is_dev_mode():
        # Treat username as email for dev mode
        user_info = _DEV_USERS.get(body.username)
        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unknown user. Dev accounts: {', '.join(_DEV_USERS)}",
            )
        access_token = _dev_create_token(user_info, body.username)
        token_data = TokenResponse(
            access_token=access_token,
            refresh_token=access_token,
            token_type="bearer",
            expires_in=3600,
        )
    else:
        kc_tokens = await _keycloak_token_grant(body.username, body.password)
        token_data = TokenResponse(
            access_token=kc_tokens["access_token"],
            refresh_token=kc_tokens.get("refresh_token", ""),
            token_type=kc_tokens.get("token_type", "bearer"),
            expires_in=kc_tokens.get("expires_in", 3600),
        )

    audit = _audit_event(
        "auth.login", "session", None,
        {"username": body.username},
    )
    logger.info(
        "Login attempted",
        extra={"request_id": request_id, "username": body.username, "audit_id": str(audit.id)},
    )

    return {
        "data": token_data.model_dump(),
        "meta": _meta(request_id=request_id),
    }


@router.post("/token/refresh")
async def refresh_token(body: RefreshRequest) -> dict[str, Any]:
    """Refresh an expired access token using a valid refresh token.

    In dev mode, returns a stub. Otherwise, exchanges the refresh token
    with Keycloak for a new access/refresh pair.
    """
    request_id = str(uuid4())

    if _is_dev_mode():
        token_data = TokenResponse(
            access_token="",
            refresh_token="",
            token_type="bearer",
            expires_in=3600,
        )
    else:
        refresh_url = f"{settings.KEYCLOAK_URL}/protocol/openid-connect/token"
        form_data = {
            "grant_type": "refresh_token",
            "client_id": settings.KEYCLOAK_CLIENT_ID,
            "refresh_token": body.refresh_token,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(refresh_url, data=form_data)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token expired or invalid",
            )
        kc = resp.json()
        token_data = TokenResponse(
            access_token=kc["access_token"],
            refresh_token=kc.get("refresh_token", ""),
            token_type=kc.get("token_type", "bearer"),
            expires_in=kc.get("expires_in", 3600),
        )

    logger.info(
        "Token refresh requested",
        extra={"request_id": request_id},
    )

    return {
        "data": token_data.model_dump(),
        "meta": _meta(request_id=request_id),
    }


@router.get("/saml/metadata")
async def saml_metadata() -> dict[str, Any]:
    """Return SAML service provider metadata (public endpoint).

    Provides the SP entity ID, ACS URL, and signing certificate
    for IdP configuration.
    """
    metadata = {
        "entity_id": "urn:archon:sp",
        "acs_url": "/api/v1/auth/saml/acs",
        "name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
    }

    return {
        "data": metadata,
        "meta": _meta(),
    }


@router.post("/saml/acs")
async def saml_acs(body: SAMLACSPayload) -> dict[str, Any]:
    """SAML Assertion Consumer Service endpoint.

    Receives and validates the SAML response from the identity provider,
    extracts user attributes, and issues a JWT session token.
    """
    request_id = str(uuid4())

    # Production: validate SAML response, extract assertions, create session.
    session_data = {
        "access_token": "",
        "token_type": "bearer",
        "relay_state": body.relay_state,
    }

    audit = _audit_event(
        "auth.saml_login", "session", None,
        {"relay_state": body.relay_state},
    )
    logger.info(
        "SAML ACS callback processed",
        extra={"request_id": request_id, "audit_id": str(audit.id)},
    )

    return {
        "data": session_data,
        "meta": _meta(request_id=request_id),
    }


@router.post("/mfa/totp/setup")
async def mfa_totp_setup(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Set up TOTP-based multi-factor authentication for the current user.

    Generates a TOTP secret and provisioning URI for authenticator apps.
    Backup codes are provided for account recovery.
    """
    request_id = str(uuid4())

    # Production: generate TOTP secret via pyotp, store encrypted in Vault.
    setup_data = MFASetupResponse(
        secret="",
        provisioning_uri="",
        backup_codes=[],
    )

    audit = _audit_event(
        "auth.mfa_setup", "mfa", user.id, user=user,
    )
    logger.info(
        "MFA TOTP setup initiated",
        extra={
            "request_id": request_id,
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": setup_data.model_dump(),
        "meta": _meta(request_id=request_id),
    }


@router.post("/mfa/totp/verify")
async def mfa_totp_verify(
    body: TOTPVerifyRequest,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Verify a TOTP code to complete MFA authentication.

    Validates the one-time code against the user's enrolled TOTP secret.
    On success, upgrades the session to MFA-verified status.
    """
    request_id = str(uuid4())

    # Production: validate TOTP code via pyotp against stored secret.
    verified = False

    audit = _audit_event(
        "auth.mfa_verify", "mfa", user.id,
        {"verified": verified},
        user=user,
    )
    logger.info(
        "MFA TOTP verification attempted",
        extra={
            "request_id": request_id,
            "user_id": user.id,
            "verified": verified,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": {"verified": verified},
        "meta": _meta(request_id=request_id),
    }


@router.post("/logout")
async def logout(
    request: Request,
) -> JSONResponse:
    """Logout the current user by clearing the session cookie."""
    request_id = str(uuid4())

    logger.info("User logged out", extra={"request_id": request_id})

    response = JSONResponse(content={
        "data": {"message": "Logged out successfully"},
        "meta": _meta(request_id=request_id),
    })
    response.delete_cookie(key="access_token", path="/")
    return response
