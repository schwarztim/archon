"""Shared fixtures for integration tests.

Uses FastAPI TestClient (in-process) with an in-memory SQLite backend.
No live server, PostgreSQL, or Redis required.

The ARCHON_ env-prefix is used by pydantic-settings, so we must set env vars
BEFORE importing any app module that reads the config at import time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the backend package is on the path (mirrors tests/conftest.py)
_backend = str(Path(__file__).resolve().parent.parent.parent / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

# ---------------------------------------------------------------------------
# Set env vars BEFORE any app import — pydantic-settings reads them at class
# instantiation time, which happens the first time config.py is imported.
# ---------------------------------------------------------------------------
os.environ.setdefault("ARCHON_DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("ARCHON_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
# Disable rate limiting so tests are never blocked by the counter
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Build a reusable mock Redis client used in both the rate-limit middleware
# and the health-check helper.  The singleton cache on _get_redis must also
# be cleared so it picks up our mock rather than trying a real connection.
# ---------------------------------------------------------------------------
_mock_redis = MagicMock()
_mock_redis.incr = AsyncMock(return_value=1)
_mock_redis.expire = AsyncMock(return_value=True)
_mock_redis.ttl = AsyncMock(return_value=60)
_mock_redis.get = AsyncMock(return_value=None)
_mock_redis.set = AsyncMock(return_value=True)
_mock_redis.ping = AsyncMock(return_value=True)
_mock_redis.aclose = AsyncMock()
_mock_redis.close = AsyncMock()

# ---------------------------------------------------------------------------
# SQLite doesn't accept pool_size / max_overflow.  Wrap create_async_engine
# so those arguments are stripped when the URL is sqlite-based.
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import create_async_engine as _real_create_async_engine


def _sqlite_friendly_create_engine(url, **kwargs):
    if "sqlite" in str(url):
        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
        kwargs.pop("pool_pre_ping", None)
    return _real_create_async_engine(url, **kwargs)


# ---------------------------------------------------------------------------
# Import the app under the patches so every lazy import inside app modules
# also sees our mocked redis.asyncio.from_url.
# ---------------------------------------------------------------------------
with (
    patch(
        "sqlalchemy.ext.asyncio.create_async_engine",
        side_effect=_sqlite_friendly_create_engine,
    ),
    patch("redis.asyncio.from_url", return_value=_mock_redis),
    patch("app.logging_config.setup_logging"),
):
    from starlette.testclient import TestClient
    from app.main import create_app  # noqa: E402

    _app = create_app()

    # Clear the cached Redis client inside _get_redis (it may have been set
    # before our patch took effect during the lazy singleton call).
    from app.middleware.rate_limit import _get_redis as _rl_get_redis

    if hasattr(_rl_get_redis, "_client"):
        del _rl_get_redis._client  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def client():
    """TestClient running the FastAPI app in-process (no live server needed)."""
    with TestClient(_app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def api_prefix():
    """Standard API version prefix."""
    return "/api/v1"
