"""JWT middleware tests — verifies token validation, expiry, MFA, and tenant extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.middleware.auth import get_current_user, require_mfa


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_jwks(jwks: dict):
    """Patch ``_fetch_jwks`` to return *jwks* without hitting Keycloak."""
    return patch("app.middleware.auth._fetch_jwks", new_callable=AsyncMock, return_value=jwks)


def _mock_request():
    """Create a minimal mock Request with empty cookies."""
    from unittest.mock import MagicMock
    req = MagicMock()
    req.cookies = {}
    return req


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_jwt_extracts_user(mock_jwt_token, mock_keycloak_jwks) -> None:
    """A correctly signed JWT should return an ``AuthenticatedUser``."""
    token = mock_jwt_token(
        user_id="u-42",
        email="alice@example.com",
        tenant_id="acme",
        roles=["admin"],
        mfa_verified=True,
    )

    with _patch_jwks(mock_keycloak_jwks):
        user = await get_current_user(request=_mock_request(), token=token)

    assert user.id == "u-42"
    assert user.email == "alice@example.com"
    assert user.tenant_id == "acme"
    assert "admin" in user.roles
    assert user.mfa_verified is True


@pytest.mark.asyncio
async def test_expired_jwt_returns_401(mock_jwt_token, mock_keycloak_jwks) -> None:
    """An expired JWT must result in HTTP 401."""
    token = mock_jwt_token(expired=True)

    with _patch_jwks(mock_keycloak_jwks):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=_mock_request(), token=token)

    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_invalid_signature_returns_401(mock_jwt_token, mock_keycloak_jwks) -> None:
    """A JWT signed with a different key must be rejected with 401."""
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod
    from cryptography.hazmat.primitives import serialization

    wrong_key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_pem = wrong_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = mock_jwt_token(signing_key=wrong_pem)

    with _patch_jwks(mock_keycloak_jwks):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=_mock_request(), token=token)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_token_returns_401(mock_keycloak_jwks) -> None:
    """Calling ``get_current_user`` with an empty/unparseable token → 401."""
    with _patch_jwks(mock_keycloak_jwks):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=_mock_request(), token="")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tenant_id_extracted_from_claims(mock_jwt_token, mock_keycloak_jwks) -> None:
    """The tenant_id claim in the JWT should be forwarded to AuthenticatedUser."""
    token = mock_jwt_token(tenant_id="org-99")

    with _patch_jwks(mock_keycloak_jwks):
        user = await get_current_user(request=_mock_request(), token=token)

    assert user.tenant_id == "org-99"


@pytest.mark.asyncio
async def test_mfa_verified_claim(mock_jwt_token, mock_keycloak_jwks) -> None:
    """``require_mfa`` should pass when ``mfa_verified`` is ``True``."""
    token = mock_jwt_token(mfa_verified=True)

    with _patch_jwks(mock_keycloak_jwks):
        user = await get_current_user(request=_mock_request(), token=token)

    # Simulate the require_mfa dependency with the resolved user
    result = await require_mfa(user=user)
    assert result.mfa_verified is True


@pytest.mark.asyncio
async def test_mfa_not_verified_returns_403(mock_jwt_token, mock_keycloak_jwks) -> None:
    """``require_mfa`` should raise 403 when ``mfa_verified`` is ``False``."""
    token = mock_jwt_token(mfa_verified=False)

    with _patch_jwks(mock_keycloak_jwks):
        user = await get_current_user(request=_mock_request(), token=token)

    with pytest.raises(HTTPException) as exc_info:
        await require_mfa(user=user)

    assert exc_info.value.status_code == 403
    assert "multi-factor" in exc_info.value.detail.lower()
