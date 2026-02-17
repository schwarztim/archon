"""Application configuration via pydantic-settings with ARCHON_ env prefix."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Archon backend configuration.

    All values are read from environment variables prefixed with ``ARCHON_``.
    """

    model_config = SettingsConfigDict(
        env_prefix="ARCHON_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://archon:archon@localhost:5432/archon"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT / Auth
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "RS256"

    # Keycloak
    KEYCLOAK_URL: str = "http://localhost:8180/auth/realms/archon"
    KEYCLOAK_CLIENT_ID: str = "archon-app"

    # Auth mode — set to "true" to bypass Keycloak and use dev HS256 JWTs
    AUTH_DEV_MODE: bool = True

    # API
    API_PREFIX: str = "/api/v1"

    # App
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
