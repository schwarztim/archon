"""Comprehensive tests for health and readiness endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.health import health_check, readiness_check


# ---------------------------------------------------------------------------
# health_check (liveness)
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Tests for the liveness probe function."""

    @pytest.mark.asyncio
    async def test_returns_healthy(self) -> None:
        result = await health_check()
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_includes_version(self) -> None:
        result = await health_check()
        assert "version" in result
        assert isinstance(result["version"], str)


# ---------------------------------------------------------------------------
# readiness_check — all services healthy
# ---------------------------------------------------------------------------


class TestReadinessAllUp:
    """Readiness probe when all backend services are available."""

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_ready_when_all_ok(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "ok"}
        mock_redis.return_value = {"status": "ok"}
        mock_vault.return_value = {"status": "ok", "sealed": False}
        result = await readiness_check()
        assert result["status"] == "ready"

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_includes_checks_detail(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "ok"}
        mock_redis.return_value = {"status": "ok"}
        mock_vault.return_value = {"status": "ok", "sealed": False}
        result = await readiness_check()
        assert "checks" in result
        assert "database" in result["checks"]
        assert "redis" in result["checks"]
        assert "vault" in result["checks"]

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_includes_timestamp(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "ok"}
        mock_redis.return_value = {"status": "ok"}
        mock_vault.return_value = {"status": "ok", "sealed": False}
        result = await readiness_check()
        assert "timestamp" in result


# ---------------------------------------------------------------------------
# readiness_check — service down
# ---------------------------------------------------------------------------


class TestReadinessServiceDown:
    """Readiness probe when one or more services are unavailable."""

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_not_ready_when_db_down(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "error", "error": "connection refused"}
        mock_redis.return_value = {"status": "ok"}
        mock_vault.return_value = {"status": "ok", "sealed": False}
        result = await readiness_check()
        assert result["status"] == "not_ready"

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_not_ready_when_redis_down(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "ok"}
        mock_redis.return_value = {"status": "error", "error": "timeout"}
        mock_vault.return_value = {"status": "ok", "sealed": False}
        result = await readiness_check()
        assert result["status"] == "not_ready"

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_not_ready_when_vault_down(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "ok"}
        mock_redis.return_value = {"status": "ok"}
        mock_vault.return_value = {"status": "error", "error": "sealed"}
        result = await readiness_check()
        assert result["status"] == "not_ready"

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_not_ready_when_all_down(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "error", "error": "down"}
        mock_redis.return_value = {"status": "error", "error": "down"}
        mock_vault.return_value = {"status": "error", "error": "down"}
        result = await readiness_check()
        assert result["status"] == "not_ready"

    @pytest.mark.asyncio
    @patch("app.health._check_vault", new_callable=AsyncMock)
    @patch("app.health._check_redis", new_callable=AsyncMock)
    @patch("app.health._check_db", new_callable=AsyncMock)
    async def test_version_present_when_not_ready(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_vault: AsyncMock,
    ) -> None:
        mock_db.return_value = {"status": "error", "error": "down"}
        mock_redis.return_value = {"status": "ok"}
        mock_vault.return_value = {"status": "ok", "sealed": False}
        result = await readiness_check()
        assert "version" in result
