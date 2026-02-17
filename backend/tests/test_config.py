"""Tests for application configuration."""

from __future__ import annotations

from app.config import Settings, settings


def test_settings_instance_exists() -> None:
    """Module-level settings is a Settings instance."""
    assert isinstance(settings, Settings)


def test_settings_defaults() -> None:
    """Settings has sensible defaults for development."""
    assert settings.API_PREFIX == "/api/v1"
    assert settings.JWT_ALGORITHM == "RS256"
    assert settings.debug is False
    assert settings.log_level == "INFO"


def test_settings_cors_origins_is_list() -> None:
    """cors_origins is a list of strings."""
    assert isinstance(settings.cors_origins, list)


def test_settings_database_url_has_asyncpg() -> None:
    """Default DATABASE_URL uses asyncpg driver."""
    assert "asyncpg" in settings.DATABASE_URL
