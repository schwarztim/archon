"""Shared fixtures for enterprise auth flow tests."""

from __future__ import annotations

import time
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt

from app.interfaces.models.enterprise import AuthenticatedUser


# ---------------------------------------------------------------------------
# RSA key pair (generated once per session)
# ---------------------------------------------------------------------------

_TEST_KID = "test-key-1"


def _generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    """Generate an RSA private key and its JWKS-format public key."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = private_key.public_key()
    pub_numbers = pub.public_numbers()

    import base64

    def _b64url(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(
            n.to_bytes(length, byteorder="big")
        ).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": _TEST_KID,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url(pub_numbers.n, 256),
        "e": _b64url(pub_numbers.e, 3),
    }
    return private_key, jwk


_PRIVATE_KEY, _PUBLIC_JWK = _generate_rsa_keypair()

# PEM bytes for python-jose signing
_PRIVATE_PEM: bytes = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_keycloak_jwks() -> dict[str, Any]:
    """Return a JWKS response matching the test signing key."""
    return {"keys": [_PUBLIC_JWK]}


@pytest.fixture()
def mock_jwt_token():
    """Factory fixture: create a signed JWT with configurable claims.

    Usage::

        token = mock_jwt_token(user_id="u1", tenant_id="t1", roles=["admin"])
    """

    def _create(
        *,
        user_id: str = "user-1",
        email: str = "user@example.com",
        tenant_id: str = "tenant-1",
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        mfa_verified: bool = False,
        expired: bool = False,
        kid: str = _TEST_KID,
        signing_key: bytes = _PRIVATE_PEM,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "sub": user_id,
            "email": email,
            "tenant_id": tenant_id,
            "iss": "http://localhost:8180/auth/realms/archon",
            "aud": "account",
            "iat": now - 60,
            "exp": now - 10 if expired else now + 3600,
            "mfa_verified": mfa_verified,
            "sid": "session-1",
            "realm_access": {"roles": roles or []},
            "permissions": permissions or [],
        }
        return jwt.encode(
            payload,
            signing_key,
            algorithm="RS256",
            headers={"kid": kid},
        )

    return _create


@pytest.fixture()
def mock_authenticated_user():
    """Factory fixture: create an ``AuthenticatedUser`` instance."""

    def _create(
        *,
        user_id: str = "user-1",
        email: str = "user@example.com",
        tenant_id: str = "tenant-1",
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        mfa_verified: bool = False,
    ) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=user_id,
            email=email,
            tenant_id=tenant_id,
            roles=roles or [],
            permissions=permissions or [],
            mfa_verified=mfa_verified,
            session_id="session-1",
        )

    return _create
