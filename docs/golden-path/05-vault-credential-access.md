# Golden Path 05: Vault Credential Access

Access secrets via SecretsManager — static keys, dynamic DB credentials, PKI certs, and rotation — all tenant-scoped.

## Prerequisites

- Archon API running, HashiCorp Vault unsealed, SecretsManager registered

## Step 1: Import SecretsManager

```python
from backend.app.auth.dependencies import get_current_user
from backend.app.auth.models import AuthenticatedUser
from backend.app.core.audit import audit_log
from backend.app.secrets.manager import SecretsManager
from backend.app.secrets.dependencies import get_secrets_manager
```

## Step 2: Get a Static Secret (API Key)

```python
async def call_external_api(
    user: AuthenticatedUser, secrets: SecretsManager,
) -> dict:
    """Fetch an API key from Vault and call an external service."""
    api_key = await secrets.get_static_secret(
        path="external-services/weather-api", key="api_key",
        tenant_id=user.tenant_id,
    )
    # Use api_key to call the external API (never log or return it)
    return {"status": "ok"}
```

## Step 3: Get a Dynamic Database Credential

```python
async def get_analytics_connection(
    user: AuthenticatedUser, secrets: SecretsManager,
) -> dict:
    """Obtain a lease-based database credential from Vault."""
    cred = await secrets.get_dynamic_credential(
        backend="database", role="analytics-readonly",
        tenant_id=user.tenant_id,
    )
    # cred exposes: username, password, lease_id, lease_duration
    conn = f"postgresql://{cred.username}:{cred.password}@analytics-db:5432/warehouse"
    await audit_log(user, "credential.leased", "database", cred.lease_id, {"role": "analytics-readonly"})
    return {"lease_id": cred.lease_id}
```

## Step 4: Issue a PKI Certificate

```python
async def issue_service_cert(
    user: AuthenticatedUser, secrets: SecretsManager,
) -> dict:
    """Issue a short-lived TLS certificate from the Vault PKI engine."""
    cert = await secrets.issue_pki_certificate(
        role="internal-services",
        common_name=f"{user.tenant_id}.svc.archon.internal",
        ttl="24h", tenant_id=user.tenant_id,
    )
    await audit_log(user, "certificate.issued", "pki", cert.serial_number, {"common_name": cert.common_name})
    return {"serial": cert.serial_number, "expiry": cert.expiry}
```

## Step 5: Rotate a Secret

```python
async def rotate_api_key(
    user: AuthenticatedUser, secrets: SecretsManager,
) -> None:
    """Rotate a static secret and notify dependent services."""
    await secrets.rotate_secret(
        path="external-services/weather-api", key="api_key",
        tenant_id=user.tenant_id,
    )
    await audit_log(user, "secret.rotated", "secret", "weather-api", {"path": "external-services/weather-api"})
```

## What NOT to Do

```python
import os
# WRONG: Hardcoded credential — exposed in source control
API_KEY = "sk-live-abc123secretkey"
# WRONG: Reading secrets from environment variables
API_KEY = os.environ["WEATHER_API_KEY"]
# WRONG: Missing tenant_id — breaks multi-tenant isolation
api_key = await secrets.get_static_secret(
    path="external-services/weather-api", key="api_key",
    # Missing: tenant_id=user.tenant_id
)
# WRONG: Logging the secret value — credential exposure in logs
logger.info(f"Retrieved API key: {api_key}")
```

## Next Steps

- [04 — Authenticated Endpoint](./04-authenticated-endpoint.md) · [01 — Create and Run Agent](./01-create-and-run-agent.md)
