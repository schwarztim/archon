# ADR-010: Secrets Management

> **Status**: ACCEPTED
> **Date**: 2026-02-14
> **Decision**: All credential storage and cryptographic operations use HashiCorp Vault, accessed exclusively through a `SecretsManager` abstraction layer.

## Context

Archon orchestrates AI agents that require access to database credentials, API keys, cloud provider tokens, encryption keys, and TLS certificates. Storing these in environment variables, config files, or application databases creates security risks: credentials in plaintext, no rotation, no audit trail, and no centralized revocation. A multi-tenant platform demands per-tenant secret isolation with a unified operational model.

## Decision

### Vault as the Single Source of Truth

All secrets are stored in and retrieved from HashiCorp Vault. No credential may be stored in environment variables, `.env` files, application config, or the PostgreSQL database. The only Vault credential permitted outside Vault is the AppRole `role_id`/`secret_id` used for initial authentication.

### Secret Engines

| Engine | Purpose | Example |
|---|---|---|
| **KV-v2** | Static secrets (API keys, webhook tokens, tenant config) | `secret/data/tenants/{tenant_id}/openai_api_key` |
| **Transit** | Encrypt/decrypt without exposing keys (PII, audit payloads) | `transit/encrypt/archon-tenant-{tenant_id}` |
| **PKI** | Short-lived TLS certificates for internal mTLS | `pki/issue/archon-internal` (TTL 24h) |
| **Database** | Dynamic PostgreSQL credentials per service | `database/creds/archon-api-role` (TTL 1h) |
| **AWS/Azure/GCP** | Cloud provider credentials via assumed roles / service principals | `aws/creds/archon-s3-role` (TTL 15m) |

### SecretsManager Abstraction Layer

All application code accesses secrets through `backend.app.secrets.manager.SecretsManager`, injected via FastAPI `Depends(get_secrets_manager)`. This abstraction:

1. **Decouples application code from Vault's HTTP API** — swappable for testing or migration.
2. **Enforces tenant scoping** — every read/write operation requires `tenant_id`, prepended to the Vault path automatically.
3. **Handles lease renewal** — background task renews dynamic credentials before TTL expiry.
4. **Strips secrets from logs** — integrates with structlog processors to redact any value retrieved from Vault.

```python
# CORRECT: Access via SecretsManager dependency
secrets: SecretsManager = Depends(get_secrets_manager)
api_key = await secrets.get_secret(tenant_id=user.tenant_id, path="openai_api_key")

# WRONG: Direct env var or hardcoded value
api_key = os.environ["OPENAI_API_KEY"]
```

### Rotation Strategy

- **Static secrets (KV-v2)**: Application subscribes to Vault's event notifications. On rotation, `SecretsManager` invalidates its local cache and re-fetches. Maximum cache TTL: 5 minutes.
- **Dynamic credentials (Database, Cloud)**: Vault generates short-lived credentials. `SecretsManager` renews leases at 75% of TTL. On renewal failure, a new credential is requested.
- **Transit keys**: Vault handles key versioning. The `min_decryption_version` policy ensures old ciphertext remains readable during key rotation.
- **PKI certificates**: Certificates issued with 24h TTL, renewed at 50% lifetime by a sidecar process.

### Access Policies

Vault policies follow least-privilege per service:

```hcl
# API service policy — read tenant secrets, encrypt/decrypt via Transit
path "secret/data/tenants/{{identity.entity.metadata.tenant_id}}/*" {
  capabilities = ["read"]
}
path "transit/encrypt/archon-tenant-*" {
  capabilities = ["update"]
}
path "transit/decrypt/archon-tenant-*" {
  capabilities = ["update"]
}
```

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **AWS Secrets Manager / Azure Key Vault** | Cloud-specific; locks platform to a single provider. Vault runs anywhere. |
| **Environment variables** | No rotation, no audit trail, visible in process listings and crash dumps. |
| **Encrypted config files (SOPS)** | No dynamic credentials, no centralized revocation, poor multi-tenant isolation. |
| **Application-level encryption with DB storage** | Key management becomes the application's problem; no hardware security module integration. |
| **CyberArk / Thales** | Enterprise licensing cost prohibitive for open-source project; limited OSS community tooling. |

## Consequences

- All secrets have audit trails via Vault's built-in audit log.
- Dynamic credentials eliminate long-lived passwords — blast radius of a leak is limited to the credential's TTL.
- Tenant isolation is enforced at the Vault policy level, not just application logic.
- Operational complexity increases: Vault must be deployed, unsealed, and operated as critical infrastructure.
- Local development requires a Vault dev server (`vault server -dev`) or mock `SecretsManager` in tests.
- Every new service must define a Vault policy before deployment — no implicit access.
