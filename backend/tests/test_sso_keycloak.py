"""Keycloak SSO integration tests.

These tests exercise the OIDC authorization-code flow against a live
Keycloak realm. They are skipped when:

  * the ``requests`` library is not installed, or
  * the ``KEYCLOAK_TEST_URL`` environment variable is not set.

The expected realm shape is documented in
``docs/runbooks/sso-integration.md`` § 5 (test users + roles).

Environment variables:

  KEYCLOAK_TEST_URL          Base URL of Keycloak (e.g. http://localhost:8180/auth)
  KEYCLOAK_TEST_REALM        Realm name (default: archon)
  KEYCLOAK_TEST_CLIENT_ID    Confidential client ID (default: archon-backend)
  KEYCLOAK_TEST_CLIENT_SECRET  Client secret (required when set)
  KEYCLOAK_TEST_USERNAME     Test user (default: alice@tenant1.local)
  KEYCLOAK_TEST_PASSWORD     Test user password (default: alice-test)
"""

from __future__ import annotations

import os

import pytest

requests = pytest.importorskip("requests")  # noqa: E402

KEYCLOAK_URL = os.getenv("KEYCLOAK_TEST_URL")
if not KEYCLOAK_URL:
    pytest.skip(
        "KEYCLOAK_TEST_URL not set; skipping live Keycloak SSO tests",
        allow_module_level=True,
    )

REALM = os.getenv("KEYCLOAK_TEST_REALM", "archon")
CLIENT_ID = os.getenv("KEYCLOAK_TEST_CLIENT_ID", "archon-backend")
CLIENT_SECRET = os.getenv("KEYCLOAK_TEST_CLIENT_SECRET")
USERNAME = os.getenv("KEYCLOAK_TEST_USERNAME", "alice@tenant1.local")
PASSWORD = os.getenv("KEYCLOAK_TEST_PASSWORD", "alice-test")

OIDC_BASE = f"{KEYCLOAK_URL.rstrip('/')}/realms/{REALM}/protocol/openid-connect"
DISCOVERY = f"{KEYCLOAK_URL.rstrip('/')}/realms/{REALM}/.well-known/openid-configuration"
JWKS_URL = f"{KEYCLOAK_URL.rstrip('/')}/realms/{REALM}/protocol/openid-connect/certs"


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def discovery_doc() -> dict:
    """Fetch the OIDC discovery document once per module."""
    resp = requests.get(DISCOVERY, timeout=5)
    resp.raise_for_status()
    return resp.json()


@pytest.fixture(scope="module")
def access_token() -> str:
    """Acquire an access token via the resource-owner password grant.

    Direct-access grants are normally disabled in production. This test
    asks the realm for them; if the realm refuses, the test is skipped.
    """
    if not CLIENT_SECRET:
        pytest.skip("KEYCLOAK_TEST_CLIENT_SECRET not set")
    payload = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": USERNAME,
        "password": PASSWORD,
        "scope": "openid profile email",
    }
    resp = requests.post(f"{OIDC_BASE}/token", data=payload, timeout=5)
    if resp.status_code == 400 and "unauthorized_client" in resp.text:
        pytest.skip("realm does not enable direct-access grants for this client")
    resp.raise_for_status()
    return resp.json()["access_token"]


# ── Tests ───────────────────────────────────────────────────────────


def test_realm_discovery_advertises_required_endpoints(discovery_doc: dict) -> None:
    """OIDC discovery must advertise every endpoint the backend uses."""
    required = {
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "userinfo_endpoint",
        "jwks_uri",
        "end_session_endpoint",
    }
    missing = required - discovery_doc.keys()
    assert not missing, f"discovery doc missing endpoints: {missing}"
    assert discovery_doc["issuer"].endswith(REALM), (
        "issuer must reference the configured realm"
    )


def test_jwks_endpoint_returns_signing_keys() -> None:
    """JWKS must expose at least one signing key the backend can verify with."""
    resp = requests.get(JWKS_URL, timeout=5)
    resp.raise_for_status()
    jwks = resp.json()
    assert "keys" in jwks and jwks["keys"], "JWKS returned no signing keys"
    sig_keys = [k for k in jwks["keys"] if k.get("use", "sig") == "sig"]
    assert sig_keys, "no signing keys in JWKS (only enc keys present)"
    for key in sig_keys:
        assert "kid" in key, "signing key missing kid"
        assert key.get("kty") in {"RSA", "EC"}, "unsupported key type"


def test_password_login_returns_jwt_with_required_claims(access_token: str) -> None:
    """The returned access token must be a JWT with Archon-required claims."""
    parts = access_token.split(".")
    assert len(parts) == 3, "access token is not a JWT (expected 3 dot-separated parts)"

    # Decode the payload without signature verification — the JWKS test
    # above proves the keys are present; here we only check claim shape.
    import base64
    import json

    payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))

    for claim in ("iss", "aud", "sub", "exp", "iat", "preferred_username"):
        assert claim in payload, f"missing required claim: {claim}"
    assert payload["preferred_username"] == USERNAME


def test_token_carries_role_claims(access_token: str) -> None:
    """Realm roles must propagate through the access token (`realm_access.roles`)."""
    import base64
    import json

    payload_b64 = access_token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))

    realm_roles = payload.get("realm_access", {}).get("roles", [])
    archon_roles = {
        r for r in realm_roles
        if r in {"archon-admin", "archon-tenant-admin", "archon-user"}
    }
    assert archon_roles, (
        f"token carries no Archon-recognized roles; realm_access.roles={realm_roles}"
    )


def test_userinfo_endpoint_validates_token(
    discovery_doc: dict, access_token: str
) -> None:
    """The userinfo endpoint must accept the token and echo the username."""
    userinfo_url = discovery_doc["userinfo_endpoint"]
    resp = requests.get(
        userinfo_url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=5,
    )
    resp.raise_for_status()
    info = resp.json()
    assert info.get("preferred_username") == USERNAME


def test_logout_revokes_refresh_token() -> None:
    """End-session must accept a refresh token without error.

    We exchange creds for a refresh token, hit the revoke endpoint,
    and re-using the refresh token must then fail.
    """
    if not CLIENT_SECRET:
        pytest.skip("KEYCLOAK_TEST_CLIENT_SECRET not set")
    token_resp = requests.post(
        f"{OIDC_BASE}/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": USERNAME,
            "password": PASSWORD,
            "scope": "openid profile email offline_access",
        },
        timeout=5,
    )
    if token_resp.status_code != 200:
        pytest.skip("could not acquire refresh token (check scope grants)")
    refresh_token = token_resp.json().get("refresh_token")
    assert refresh_token, "no refresh_token returned despite offline_access"

    logout_resp = requests.post(
        f"{OIDC_BASE}/logout",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=5,
    )
    assert logout_resp.status_code in (204, 200), (
        f"logout returned {logout_resp.status_code}: {logout_resp.text}"
    )

    # Re-using the refresh token must now fail.
    replay = requests.post(
        f"{OIDC_BASE}/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=5,
    )
    assert replay.status_code >= 400, (
        "refresh token still valid after logout — backchannel logout broken"
    )
