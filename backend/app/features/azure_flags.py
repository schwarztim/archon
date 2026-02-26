"""Feature flags for Azure OpenAI integration."""

from typing import Dict, Any

try:
    from ..config import settings
except ImportError:
    # Fallback for standalone execution
    import sys
    from pathlib import Path

    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from app.config import settings


class AzureFeatureFlags:
    """Manages feature flags specific to Azure OpenAI integration."""

    @staticmethod
    def is_azure_provider_enabled() -> bool:
        """Check if Azure OpenAI provider is enabled."""
        return getattr(settings, "AZURE_OPENAI_ENABLED", True)

    @staticmethod
    def is_cost_tracking_enabled() -> bool:
        """Check if cost tracking is enabled (required for Azure routing)."""
        return settings.FEATURE_COST_TRACKING

    @staticmethod
    def is_fallback_enabled() -> bool:
        """Check if fallback routing is enabled."""
        return getattr(settings, "AZURE_FALLBACK_ENABLED", True)

    @staticmethod
    def get_max_retries() -> int:
        """Get maximum retry attempts for Azure API calls."""
        return getattr(settings, "AZURE_MAX_RETRIES", 3)

    @staticmethod
    def get_timeout_ms() -> int:
        """Get timeout for Azure API calls in milliseconds."""
        return getattr(settings, "AZURE_TIMEOUT_MS", 30000)

    @staticmethod
    def is_health_check_enabled() -> bool:
        """Check if Azure model health checking is enabled."""
        return getattr(settings, "AZURE_HEALTH_CHECK_ENABLED", True)

    @staticmethod
    def get_health_check_interval() -> int:
        """Get health check interval in seconds."""
        return getattr(settings, "AZURE_HEALTH_CHECK_INTERVAL", 300)

    @staticmethod
    def get_feature_config() -> Dict[str, Any]:
        """Get all Azure feature flag configuration."""
        return {
            "provider_enabled": AzureFeatureFlags.is_azure_provider_enabled(),
            "cost_tracking": AzureFeatureFlags.is_cost_tracking_enabled(),
            "fallback_enabled": AzureFeatureFlags.is_fallback_enabled(),
            "max_retries": AzureFeatureFlags.get_max_retries(),
            "timeout_ms": AzureFeatureFlags.get_timeout_ms(),
            "health_check_enabled": AzureFeatureFlags.is_health_check_enabled(),
            "health_check_interval": AzureFeatureFlags.get_health_check_interval(),
        }


# Convenience functions for common feature flag checks
def azure_enabled() -> bool:
    """Quick check if Azure OpenAI is enabled."""
    return AzureFeatureFlags.is_azure_provider_enabled()


def azure_with_fallback() -> bool:
    """Check if Azure is enabled with fallback support."""
    return azure_enabled() and AzureFeatureFlags.is_fallback_enabled()


def azure_cost_aware() -> bool:
    """Check if Azure routing should consider cost optimization."""
    return azure_enabled() and AzureFeatureFlags.is_cost_tracking_enabled()
