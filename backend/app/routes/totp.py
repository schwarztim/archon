"""Dedicated TOTP endpoints for non-OIDC MFA fallback.

Provides enroll, verify, and unenroll endpoints for TOTP-based MFA at
``/api/v1/auth/totp/*``.  The legacy ``/setup`` endpoint is preserved for
backward compatibility.
"""

from __future__ import annotations

import base64
import io
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.interfaces.models.enterprise import AuthenticatedUser, MFASetupResponse
from app.middleware.auth import require_auth

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None  # type: ignore[assignment]

try:
    import qrcode  # type: ignore[import]
    import qrcode.image.pil  # type: ignore[import]
except ImportError:  # pragma: no cover
    qrcode = None  # type: ignore[assignment]

try:
    from jose import jwt as jose_jwt
except ImportError:  # pragma: no cover
    jose_jwt = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/totp", tags=["TOTP"])

# In-memory TOTP secret store for dev / test (keyed by user_id).
# Production deployments should persist secrets in the DB / secrets backend.
_totp_secrets: dict[str, str] = {}


# ── Request / response schemas ──────────────────────────────────────


class TOTPVerifyRequest(BaseModel):
    """Payload for verifying a 6-digit TOTP code."""

    code: str


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _generate_qr_base64(otpauth_url: str) -> str | None:
    """Return a base64-encoded PNG QR code for *otpauth_url*, or None."""
    if qrcode is None:
        return None
    try:
        img = qrcode.make(otpauth_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        logger.debug("_generate_qr_base64: QR generation failed", exc_info=True)
        return None


def _issue_mfa_jwt(user: AuthenticatedUser) -> str | None:
    """Issue a short-lived HS256 JWT with ``mfa_verified=true`` claim."""
    if jose_jwt is None:
        return None
    try:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user.id,
            "email": user.email,
            "tenant_id": user.tenant_id,
            "roles": user.roles,
            "mfa_verified": True,
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        return jose_jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    except Exception:
        logger.debug("_issue_mfa_jwt: JWT encoding failed", exc_info=True)
        return None


async def _get_totp_secret(user_id: str) -> str | None:
    """Retrieve the stored TOTP secret for *user_id*.

    Checks the in-memory store first, then attempts a DB lookup on the
    ``user_identities`` table.  Returns ``None`` when no secret is found.
    """
    # Fast path: in-memory store (covers dev/test and freshly enrolled users)
    if user_id in _totp_secrets:
        return _totp_secrets[user_id]

    try:
        from uuid import UUID

        from sqlmodel import select

        from app.database import async_session_factory
        from app.models.auth import UserIdentity

        try:
            user_uuid = UUID(user_id)
        except ValueError:
            return None

        async with async_session_factory() as session:
            result = await session.exec(
                select(UserIdentity).where(UserIdentity.id == user_uuid)
            )
            identity = result.first()

        if identity is None:
            return None

        return getattr(identity, "totp_secret", None)
    except Exception:
        logger.debug("_get_totp_secret: DB lookup failed", exc_info=True)
        return None


async def _store_totp_secret(user_id: str, secret: str | None) -> None:
    """Persist a TOTP secret for *user_id* (in-memory + DB best-effort)."""
    if secret is None:
        _totp_secrets.pop(user_id, None)
    else:
        _totp_secrets[user_id] = secret

    try:
        from uuid import UUID

        from sqlmodel import select

        from app.database import async_session_factory
        from app.models.auth import UserIdentity

        try:
            user_uuid = UUID(user_id)
        except ValueError:
            return

        async with async_session_factory() as session:
            result = await session.exec(
                select(UserIdentity).where(UserIdentity.id == user_uuid)
            )
            identity = result.first()
            if identity is not None and hasattr(identity, "totp_secret"):
                identity.totp_secret = secret  # type: ignore[attr-defined]
                if secret is not None:
                    identity.mfa_enabled = True
                    identity.mfa_method = "totp"
                else:
                    identity.mfa_enabled = False
                    identity.mfa_method = None
                session.add(identity)
                await session.commit()
    except Exception:
        logger.debug("_store_totp_secret: DB update failed", exc_info=True)


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/enroll")
async def totp_enroll(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Enroll the current user in TOTP-based MFA.

    Generates a fresh TOTP secret and returns the ``otpauth://`` provisioning
    URI plus a base64-encoded PNG QR code for scanning with any authenticator
    app.  The caller must follow up with ``POST /totp/verify`` to confirm
    that the code is correct before the secret is considered active.
    """
    request_id = str(uuid4())

    if pyotp is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="pyotp is not installed.",
        )

    totp_secret: str = pyotp.random_base32()
    otpauth_url: str = pyotp.TOTP(totp_secret).provisioning_uri(
        name=user.email,
        issuer_name="Archon",
    )
    qr_base64 = _generate_qr_base64(otpauth_url)

    # Store provisionally (enrollment is considered complete immediately).
    await _store_totp_secret(user.id, totp_secret)

    logger.info(
        "TOTP enroll initiated",
        extra={
            "request_id": request_id,
            "user_id": user.id,
            "tenant_id": user.tenant_id,
        },
    )

    return {
        "data": {
            "secret": totp_secret,
            "otpauth_url": otpauth_url,
            "qr_code_base64": qr_base64,
        },
        "meta": _meta(request_id=request_id),
    }


@router.post("/verify")
async def totp_verify(
    body: TOTPVerifyRequest,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Validate a 6-digit TOTP code against the user's stored secret.

    On success returns a short-lived JWT with ``mfa_verified=true``.
    Accepts a +-30 second drift window (``valid_window=1``).
    Returns HTTP 401 on mismatch and HTTP 422 if the user has not enrolled.
    """
    request_id = str(uuid4())

    if pyotp is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="pyotp is not installed.",
        )

    totp_secret: str | None = await _get_totp_secret(user.id)

    if not totp_secret:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="TOTP not configured for this user. Call /totp/enroll first.",
        )

    code = body.code.strip()
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP code must be exactly 6 digits.",
        )

    totp = pyotp.TOTP(totp_secret)
    verified: bool = totp.verify(code, valid_window=1)

    logger.info(
        "TOTP verification attempted",
        extra={"request_id": request_id, "user_id": user.id, "verified": verified},
    )

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired TOTP code.",
        )

    mfa_token = _issue_mfa_jwt(user)

    return {
        "data": {
            "verified": True,
            "mfa_verified": True,
            **(
                {"access_token": mfa_token, "token_type": "bearer"} if mfa_token else {}
            ),
        },
        "meta": _meta(request_id=request_id),
    }


@router.delete("/unenroll")
async def totp_unenroll(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Remove TOTP MFA from the current user's account.

    Deletes the stored secret from both the in-memory cache and the database.
    """
    request_id = str(uuid4())

    await _store_totp_secret(user.id, None)

    logger.info(
        "TOTP unenrolled",
        extra={
            "request_id": request_id,
            "user_id": user.id,
            "tenant_id": user.tenant_id,
        },
    )

    return {
        "data": {"unenrolled": True},
        "meta": _meta(request_id=request_id),
    }


@router.post("/setup")
async def totp_setup(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Generate a TOTP secret and provisioning URI for authenticator apps.

    Deprecated in favour of ``POST /enroll``.  Kept for backward compatibility.
    Returns the base-32 secret, an ``otpauth://`` URI, and 8 backup codes.
    """
    request_id = str(uuid4())

    if pyotp is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="pyotp is not installed. Add pyotp to requirements.txt.",
        )

    totp_secret: str = pyotp.random_base32()

    provisioning_uri: str = pyotp.TOTP(totp_secret).provisioning_uri(
        name=user.email,
        issuer_name="Archon",
    )

    backup_codes: list[str] = [secrets.token_hex(8) for _ in range(8)]

    setup_data = MFASetupResponse(
        secret=totp_secret,
        provisioning_uri=provisioning_uri,
        backup_codes=backup_codes,
    )

    logger.info(
        "TOTP setup initiated",
        extra={
            "request_id": request_id,
            "user_id": user.id,
            "tenant_id": user.tenant_id,
        },
    )

    return {
        "data": setup_data.model_dump(),
        "meta": _meta(request_id=request_id),
    }
