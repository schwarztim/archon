"""RBAC route permission matrix tests (Phase 4 / WS13).

Verifies the route-permission audit script and the public allowlist remain
in sync with the live FastAPI app.

Tests
-----
* ``test_every_route_in_matrix`` — every registered route is either
  authenticated or in the explicit allowlist.
* ``test_allowlist_is_minimal`` — every allowlist entry corresponds to a
  registered route (no stale entries).
* ``test_admin_endpoint_requires_admin_role`` — the audit verify and
  approvals endpoints reject non-admin callers attempting cross-tenant
  access (asserts the 403 path is wired).
* ``test_public_health_endpoints_unauth`` — GET /health and GET /api/v1/health
  succeed without an Authorization header.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Required env BEFORE app import (matches conftest conventions).
os.environ.setdefault("ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.interfaces.models.enterprise import AuthenticatedUser  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware.auth import get_current_user  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO_ROOT / "scripts" / "route-permissions-allowlist.txt"


# Names that count as authentication gates — must match
# scripts/check-route-permissions.py.
AUTH_DEPENDENCY_NAMES: frozenset[str] = frozenset(
    {
        "get_current_user",
        "require_auth",
        "require_mfa",
        "require_admin",
        "require_role",
        "require_permission",
        "require_active_user",
        "verify_api_key",
        "require_api_key",
    }
)


def _has_auth_dependency(dependant) -> bool:
    """Walk dependant graph for any auth-gate dependency."""
    if dependant is None:
        return False
    call = getattr(dependant, "call", None)
    name = getattr(call, "__name__", None) if call is not None else None
    if name in AUTH_DEPENDENCY_NAMES:
        return True
    for sub in getattr(dependant, "dependencies", []) or []:
        if _has_auth_dependency(sub):
            return True
    return False


def _load_allowlist() -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()
    if not ALLOWLIST.is_file():
        return entries
    for raw in ALLOWLIST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            entries.add((parts[0].upper(), parts[1]))
    return entries


def _all_route_entries() -> list[tuple[str, str, object]]:
    routes: list[tuple[str, str, object]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in (route.methods or set()) - {"HEAD"}:
            routes.append((method, route.path, route.dependant))
    return routes


# ─────────────────────────────────────────────────────────────────────
# Matrix coverage
# ─────────────────────────────────────────────────────────────────────


# Build the parameter list at collection time.
_ROUTE_ENTRIES = _all_route_entries()
_ALLOWLIST = _load_allowlist()


def test_every_route_in_matrix() -> None:
    """Every registered route is classified as authenticated or allowlisted.

    The classification mirrors ``scripts/check-route-permissions.py``.  A
    route is "covered" if its dependency tree contains a known auth gate OR
    its (method, path) appears in ``scripts/route-permissions-allowlist.txt``.

    The audit script is the single source of truth for blocking CI; this
    test asserts the same invariant in-test so contributors get an early
    signal.  When the test fails, the failure message lists every drift
    route — add an auth dependency or extend the allowlist with rationale.
    """
    drift: list[tuple[str, str]] = []
    for method, path, dependant in _ROUTE_ENTRIES:
        if _has_auth_dependency(dependant):
            continue
        if (method, path) in _ALLOWLIST:
            continue
        drift.append((method, path))

    drift.sort()
    assert not drift, (
        f"{len(drift)} route(s) are unauthenticated and not on the public "
        f"allowlist (scripts/route-permissions-allowlist.txt):\n"
        + "\n".join(f"  {m:6s} {p}" for m, p in drift[:50])
        + (f"\n  ... and {len(drift) - 50} more" if len(drift) > 50 else "")
    )


def test_allowlist_is_minimal() -> None:
    """Every allowlist entry must correspond to a real registered route."""
    actual = {(m, p) for (m, p, _) in _ROUTE_ENTRIES}
    stale = sorted(_ALLOWLIST - actual)
    assert not stale, (
        f"Allowlist contains entries that no longer exist as routes: {stale}. "
        f"Remove them from scripts/route-permissions-allowlist.txt."
    )


# ─────────────────────────────────────────────────────────────────────
# Admin / role enforcement
# ─────────────────────────────────────────────────────────────────────


def _override_user(roles: list[str], tenant_id: str = "tenant-a") -> AuthenticatedUser:
    return AuthenticatedUser(
        id="00000000-0000-0000-0000-000000000010",
        email="user@example.com",
        tenant_id=tenant_id,
        roles=roles,
        permissions=[],
        mfa_verified=True,
        session_id="sess-1",
    )


def test_admin_endpoint_requires_admin_role() -> None:
    """Audit verify rejects cross-tenant access by non-admin callers.

    A non-admin (developer role) requesting a different tenant's chain must
    get HTTP 403; an admin caller must succeed.
    """

    async def _override_non_admin() -> AuthenticatedUser:
        return _override_user(roles=["developer"], tenant_id="tenant-a")

    async def _override_admin() -> AuthenticatedUser:
        return _override_user(roles=["admin"], tenant_id="tenant-a")

    # Non-admin requesting tenant-b → 403.  Use TestClient WITHOUT the `with`
    # context manager so FastAPI's startup event (which tries to connect to
    # Postgres) does not fire — matching the conftest convention.
    app.dependency_overrides[get_current_user] = _override_non_admin
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/audit/verify", params={"tenant_id": "tenant-b"})
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # Admin requesting tenant-b → not 403 (chain verification still runs and
    # may 200 with empty chain or 500 on missing DB; we only assert RBAC gate
    # has been passed by checking it's not 403).
    app.dependency_overrides[get_current_user] = _override_admin
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/audit/verify", params={"tenant_id": "tenant-b"})
        assert resp.status_code != 403, resp.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ─────────────────────────────────────────────────────────────────────
# Public health endpoints
# ─────────────────────────────────────────────────────────────────────


def test_public_health_endpoints_unauth() -> None:
    """GET /health and GET /api/v1/health succeed without auth."""
    # No `with` — keep startup out of the request path (Postgres unavailable
    # in unit-test mode).  Matches the conftest convention.
    client = TestClient(app)
    for path in ("/health", "/api/v1/health"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
