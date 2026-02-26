"""Tests for the auth middleware."""

from __future__ import annotations

import os

import pytest


def test_dev_token_returns_dev_user() -> None:
    """dev-token must return a GatewayUser with is_dev=True."""
    os.environ["AUTH_DEV_MODE"] = "true"
    from app.config import get_settings

    # Re-instantiate settings to pick up env
    get_settings.cache_clear()  # type: ignore[attr-defined]
    os.environ["AUTH_DEV_MODE"] = "true"

    import asyncio

    from fastapi import Request

    from app.auth.middleware import get_current_user
    from app.auth.models import GatewayUser

    async def _run() -> GatewayUser:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", b"Bearer dev-token")],
            "query_string": b"",
        }
        request = Request(scope)
        return await get_current_user(request)

    user = asyncio.get_event_loop().run_until_complete(_run())
    assert user.is_dev is True
    assert user.oid == "dev-oid"


def test_no_token_in_dev_mode_returns_dev_user() -> None:
    """No token in dev mode should still return a dev user."""
    os.environ["AUTH_DEV_MODE"] = "true"
    from app.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    import asyncio

    from fastapi import Request

    from app.auth.middleware import get_current_user

    async def _run() -> object:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        return await get_current_user(request)

    user = asyncio.get_event_loop().run_until_complete(_run())
    assert user.is_dev is True  # type: ignore[union-attr]


def test_missing_oidc_config_raises_503_when_not_dev() -> None:
    """Without OIDC config and not in dev mode, the middleware must raise 503."""
    import asyncio

    from fastapi import HTTPException, Request

    from app.auth.middleware import get_current_user
    from app.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    os.environ["AUTH_DEV_MODE"] = "false"
    os.environ["OIDC_DISCOVERY_URL"] = ""

    async def _run() -> object:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", b"Bearer sometoken")],
            "query_string": b"",
        }
        request = Request(scope)
        return await get_current_user(request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(_run())

    assert exc_info.value.status_code == 503
    # Restore
    os.environ["AUTH_DEV_MODE"] = "true"
    get_settings.cache_clear()  # type: ignore[attr-defined]
