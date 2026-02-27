"""MCP Host Gateway — configuration settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Gateway runtime configuration.

    All values can be set via environment variables (case-insensitive).
    """

    # Service identity
    app_name: str = Field(default="archon-mcp-gateway", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")

    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8080, alias="PORT")

    # CORS — comma-separated list of allowed origins
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        alias="CORS_ORIGINS",
    )

    # Auth
    auth_dev_mode: bool = Field(default=False, alias="AUTH_DEV_MODE")
    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")

    # Entra ID OIDC
    oidc_discovery_url: str = Field(default="", alias="OIDC_DISCOVERY_URL")
    oidc_client_id: str = Field(default="", alias="OIDC_CLIENT_ID")
    oidc_tenant_id: str = Field(default="", alias="OIDC_TENANT_ID")

    # Plugin directory
    plugins_dir: str = Field(default="plugins", alias="PLUGINS_DIR")

    # Upstream Archon backend
    archon_backend_url: str = Field(default="http://localhost:8000", alias="ARCHON_BACKEND_URL")

    # Azure OpenAI (for built-in tool execution)
    azure_openai_endpoint: str = Field(
        default="",
        alias="AZURE_OPENAI_ENDPOINT",
    )
    azure_openai_api_key: str = Field(default="", alias="AZURE_OPENAI_API_KEY")
    azure_openai_model: str = Field(default="gpt-5.2-codex", alias="AZURE_OPENAI_MODEL")

    # Rate limiting
    rate_limit_rpm: int = Field(default=60, alias="RATE_LIMIT_RPM")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")

    model_config = {"env_file": ".env", "populate_by_name": True}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()
