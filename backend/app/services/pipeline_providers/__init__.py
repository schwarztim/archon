"""Pipeline provider adapters (W9a).

Each adapter implements the ``PipelineProvider`` protocol:
  - start_pipeline   — trigger an external pipeline run
  - get_pipeline_status — poll the run's current status
  - cancel_pipeline  — request cancellation
  - normalize_status — map provider-specific status strings to canonical values
  - normalize_error  — extract a canonical error dict from a provider error blob

Canonical status values: "running", "completed", "failed", "cancelled", "unknown"

Provider adapters are stateless; all external credentials are resolved
per-call from the ``credentials`` dict passed by the activity executor.
External HTTP calls are performed via httpx in the real implementations but
are fully mockable via dependency injection in tests.
"""

from app.services.pipeline_providers.base import PipelineProvider
from app.services.pipeline_providers.github_actions import GitHubActionsProvider
from app.services.pipeline_providers.azure_devops import AzureDevOpsProvider
from app.services.pipeline_providers.generic_webhook import GenericWebhookProvider

_PROVIDERS: dict[str, PipelineProvider] = {
    "github_actions": GitHubActionsProvider(),
    "azure_devops": AzureDevOpsProvider(),
    "generic_webhook": GenericWebhookProvider(),
}


def get_provider(name: str) -> PipelineProvider:
    """Return the registered provider adapter for *name*.

    Raises ``ValueError`` for unknown provider names.
    """
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ValueError(
            f"Unknown pipeline provider {name!r}. "
            f"Valid providers: {list(_PROVIDERS)}"
        )
    return provider


__all__ = [
    "AzureDevOpsProvider",
    "GenericWebhookProvider",
    "GitHubActionsProvider",
    "PipelineProvider",
    "get_provider",
]
