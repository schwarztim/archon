"""Dedicated TOTP endpoints for non-OIDC MFA fallback.

Provides ``/api/v1/auth/totp/setup`` and ``/api/v1/auth/totp/verify``
as a standalone router that can be registered independently of the
main auth routes.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.interfaces.models.enterprise import AuthenticatedUser, MFASetupResponse
from app.middleware.auth import require_auth

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/totp", tags=["TOTP"])


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


async def _get_totp_secret(user_id: str) -> str | None:
    """Retrieve the stored TOTP secret for *user_id*.

    Attempts a DB lookup on the ``user_identities`` table.  Returns
    ``None`` when no secret is found or the DB is unavailable.
    """
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


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/setup")
async def totp_setup(
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Generate a TOTP secret and provisioning URI for authenticator apps.

    Returns the base-32 secret, an ``otpauth://`` URI suitable for QR
    display, and 8 single-use backup codes.  The secret is returned
    **once** — callers must persist it securely.
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


@router.post("/verify")
async def totp_verify(
    body: TOTPVerifyRequest,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Validate a 6-digit TOTP code against the user's stored secret.

    Accepts a +-30 second drift window (``valid_window=1``).  Returns
    HTTP 401 on mismatch and HTTP 422 if the user has not completed
    TOTP setup.
    """
    request_id = str(uuid4())

    if pyotp is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="pyotp is not installed. Add pyotp to requirements.txt.",
        )

    totp_secret: str | None = await _get_totp_secret(user.id)

    if not totp_secret:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="TOTP not configured for this user. Call /totp/setup first.",
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
        extra={
            "request_id": request_id,
            "user_id": user.id,
            "verified": verified,
        },
    )

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired TOTP code.",
        )

    return {
        "data": {"verified": True},
        "meta": _meta(request_id=request_id),
    }
