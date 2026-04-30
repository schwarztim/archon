"""Phase 4 / WS12 — zero-UUID + legacy fallback rejection.

The enterprise stack must NEVER let the zero-UUID
``00000000-0000-0000-0000-000000000000`` or the legacy
``"default"`` / ``"default-tenant"`` strings act as a real tenant.
``require_tenant`` is the structural enforcement point.
"""

from __future__ import annotations

import os
from uuid import UUID

import pytest

from app.services.tenant_context import (
    TenantContextRequired,
    require_tenant,
    reset_tenant,
    set_current_tenant,
    tenant_scope,
)

# ── Fixed UUIDs ────────────────────────────────────────────────────────

REAL_TENANT = UUID("aa000001-0001-0001-0001-000000000001")
ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")


# ── Direct require_tenant guarantees ──────────────────────────────────


def test_require_tenant_raises_for_none() -> None:
    """No tenant set → require_tenant raises."""
    token = set_current_tenant(None)
    try:
        with pytest.raises(TenantContextRequired):
            require_tenant()
    finally:
        reset_tenant(token)


def test_require_tenant_raises_for_zero_uuid() -> None:
    """Zero-UUID coerces to None and require_tenant raises."""
    token = set_current_tenant(ZERO_UUID)
    try:
        with pytest.raises(TenantContextRequired):
            require_tenant()
    finally:
        reset_tenant(token)


def test_require_tenant_returns_real_tenant() -> None:
    """A real tenant binding is returned unchanged."""
    token = set_current_tenant(REAL_TENANT)
    try:
        assert require_tenant() == REAL_TENANT
    finally:
        reset_tenant(token)


def test_legacy_default_tenant_string_rejected_in_strict_mode() -> None:
    """Setting tenant to the legacy 'default-tenant' string coerces to None."""
    token = set_current_tenant("default-tenant")
    try:
        with pytest.raises(TenantContextRequired):
            require_tenant()
    finally:
        reset_tenant(token)


def test_empty_string_rejected() -> None:
    """Empty-string tenant must coerce to None."""
    token = set_current_tenant("")
    try:
        with pytest.raises(TenantContextRequired):
            require_tenant()
    finally:
        reset_tenant(token)


def test_zero_uuid_string_rejected() -> None:
    """Zero-UUID string form coerces to None and is rejected."""
    token = set_current_tenant("00000000-0000-0000-0000-000000000000")
    try:
        with pytest.raises(TenantContextRequired):
            require_tenant()
    finally:
        reset_tenant(token)


def test_invalid_uuid_string_raises_valueerror() -> None:
    """Garbage tenant string surfaces as ValueError, not silent None."""
    with pytest.raises(ValueError):
        set_current_tenant("not-a-uuid")


# ── tenant_scope context manager ──────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_scope_zero_uuid_yields_none_and_blocks_require() -> None:
    """tenant_scope(ZERO_UUID) yields None and require_tenant raises inside."""
    async with tenant_scope(ZERO_UUID) as resolved:
        assert resolved is None
        with pytest.raises(TenantContextRequired):
            require_tenant()


@pytest.mark.asyncio
async def test_tenant_scope_real_tenant_resolves() -> None:
    """tenant_scope(real) yields the UUID and require_tenant succeeds."""
    async with tenant_scope(REAL_TENANT) as resolved:
        assert resolved == REAL_TENANT
        assert require_tenant() == REAL_TENANT


# ── Strict-mode middleware behaviour ──────────────────────────────────


def test_strict_mode_blocks_unauthenticated_tenant_scoped_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In strict mode, an unauthenticated request to a tenant-scoped path is 401.

    We exercise the middleware directly via TestClient — a clean app
    with only the TenantMiddleware mounted is enough to assert the
    behaviour. The full app's strict-mode response should be the same.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ARCHON_ENTERPRISE_STRICT_TENANT", "true")

    # Import inside the test so the env var is observed at strict-check
    # time — _strict_enabled() reads os.getenv per request.
    from app.middleware.tenant_middleware import TenantMiddleware

    app = FastAPI()
    app.add_middleware(TenantMiddleware)

    @app.get("/api/items")
    async def _items() -> dict:
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/api/items")
    assert resp.status_code == 401, resp.text
    payload = resp.json()
    assert payload.get("code") == "tenant_context_missing"


def test_lax_mode_allows_unauthenticated_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In non-strict (dev) mode, the legacy fallback still works."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ARCHON_ENTERPRISE_STRICT_TENANT", "false")
    monkeypatch.setenv("ARCHON_ENV", "dev")

    from app.middleware.tenant_middleware import TenantMiddleware

    app = FastAPI()
    app.add_middleware(TenantMiddleware)

    @app.get("/api/items")
    async def _items() -> dict:
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/api/items")
    assert resp.status_code == 200


def test_strict_mode_skips_health_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Health / metrics paths bypass the strict gate even with no tenant."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ARCHON_ENTERPRISE_STRICT_TENANT", "true")

    from app.middleware.tenant_middleware import TenantMiddleware

    app = FastAPI()
    app.add_middleware(TenantMiddleware)

    @app.get("/healthz")
    async def _healthz() -> dict:
        return {"status": "ok"}

    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200


# ── startup_checks delta ──────────────────────────────────────────────


def test_startup_check_blocks_strict_disabled_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARCHON_ENTERPRISE_STRICT_TENANT=false in prod is a startup failure."""
    from app.startup_checks import _check_tenant_context_active

    monkeypatch.setenv("ARCHON_ENV", "production")
    monkeypatch.setenv("ARCHON_ENTERPRISE_STRICT_TENANT", "false")

    failure = _check_tenant_context_active()
    assert failure is not None
    assert "strict" in failure.lower() or "tenant" in failure.lower()


def test_startup_check_passes_when_strict_unset_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Strict default (env unset) is allowed in production."""
    from app.startup_checks import _check_tenant_context_active

    monkeypatch.setenv("ARCHON_ENV", "production")
    monkeypatch.delenv("ARCHON_ENTERPRISE_STRICT_TENANT", raising=False)

    assert _check_tenant_context_active() is None


def test_startup_check_no_op_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even strict=false passes in dev — the check is durable-only."""
    from app.startup_checks import _check_tenant_context_active

    monkeypatch.setenv("ARCHON_ENV", "dev")
    monkeypatch.setenv("ARCHON_ENTERPRISE_STRICT_TENANT", "false")

    assert _check_tenant_context_active() is None
