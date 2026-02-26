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

    # Vault
    VAULT_ADDR: str = "http://localhost:8200"
    VAULT_TOKEN: str = "dev-token"

    # Auth mode — set to "true" to bypass Keycloak and use dev HS256 JWTs
    # Default is False for production safety; override with ARCHON_AUTH_DEV_MODE=true locally
    AUTH_DEV_MODE: bool = False

    # Azure Entra ID / OIDC
    OIDC_DISCOVERY_URL: str = ""  # https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration
    OIDC_CLIENT_ID: str = ""  # Entra application (client) ID
    OIDC_CLIENT_SECRET: str = ""  # Optional for public clients
    OIDC_TENANT_ID: str = ""  # Entra directory (tenant) ID

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = (
        "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com"
    )
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_MODEL: str = "gpt-5.2-codex"
    AZURE_OPENAI_EMBEDDINGS_MODEL: str = "qrg-embedding-experimental"

    # Rate limiting
    RATE_LIMIT_RPM: int = 1000  # Requests per minute (global per-tenant)
    RATE_LIMIT_ENABLED: bool = True

    # API
    API_PREFIX: str = "/api/v1"

    # SMTP
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_FROM: str = ""
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""

    # Microsoft Teams
    TEAMS_WEBHOOK_URL: str = ""

    # App
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
