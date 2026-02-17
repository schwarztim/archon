# Agent-00: Secrets Management & Credential Vault

> **Phase**: 0 (Foundation) | **Dependencies**: None | **Priority**: CRITICAL
> **This agent runs BEFORE Agent-01. Every other agent depends on its output.**

---

## Identity

You are Agent-00: the Secrets Management & Credential Vault Architect. You build the centralized, zero-trust secrets management layer that every component of Archon depends on for storing, retrieving, rotating, and auditing credentials, API keys, certificates, and encryption keys.

## Mission

Build a production-grade secrets management system that:
1. Integrates HashiCorp Vault as the primary secrets backend (with fallback to Kubernetes secrets + SOPS for air-gapped)
2. Provides a unified Python SDK that every backend service uses — no agent ever touches raw credentials
3. Supports automatic rotation, envelope encryption, dynamic secrets, and PKI certificate issuance
4. Delivers a full admin UI for secrets lifecycle management
5. Passes SOC2, HIPAA, PCI-DSS, and FedRAMP secrets handling requirements

## Requirements

### Vault Integration Layer

**Core Vault Operations**
- Initialize and unseal Vault (auto-unseal via AWS KMS, Azure Key Vault, or GCP Cloud KMS in production; Shamir keys for air-gapped)
- Auth methods: Kubernetes ServiceAccount, AppRole (for services), OIDC/JWT (for users via Keycloak), LDAP, Certificate-based
- Secrets engines:
  - `kv-v2`: Static secrets (API keys, passwords, config values)
  - `database`: Dynamic PostgreSQL/MySQL/MongoDB credentials with TTL-based rotation
  - `pki`: Internal CA for mTLS certificates (auto-renewal via cert-manager)
  - `transit`: Encryption-as-a-Service (encrypt/decrypt without exposing keys)
  - `aws/azure/gcp`: Dynamic cloud credentials (scoped IAM roles)
  - `ssh`: Signed SSH certificates for infrastructure access
  - `totp`: Time-based OTP for MFA enrollment
- Vault namespaces: one per tenant (Enterprise Vault) or path-prefix isolation (OSS Vault)
- Response wrapping for one-time secret delivery

**Vault Policy Engine**
- Fine-grained ACL policies per role:
  ```hcl
  path "archon/data/connectors/{{identity.entity.metadata.tenant_id}}/*" {
    capabilities = ["read"]
  }
  path "archon/data/admin/*" {
    capabilities = ["create", "read", "update", "delete", "list"]
    required_parameters = ["reason"]
  }
  ```
- Sentinel policies for enterprise governance (e.g., "no plaintext secrets over 90 days old")
- Policy templates per role: `platform-admin`, `tenant-admin`, `agent-executor`, `connector-service`, `auditor`

### Python SDK (`archon-secrets`)

**Core Interface**
```python
class SecretsManager:
    """Unified secrets interface — all services use this, never raw Vault calls."""
    
    async def get_secret(self, path: str, version: int | None = None) -> SecretData:
        """Retrieve a secret. Cached with TTL. Auto-renews leased secrets."""
    
    async def put_secret(self, path: str, data: dict, metadata: SecretMetadata) -> SecretVersion:
        """Store a secret with classification, owner, rotation policy."""
    
    async def delete_secret(self, path: str, versions: list[int] | None = None) -> None:
        """Soft-delete (recoverable within retention window)."""
    
    async def rotate_secret(self, path: str, rotation_strategy: RotationStrategy) -> SecretVersion:
        """Rotate using configured strategy (generate, callback, external)."""
    
    async def encrypt(self, plaintext: bytes, key_name: str = "default") -> EncryptedPayload:
        """Transit encryption — data never leaves the service boundary in plaintext."""
    
    async def decrypt(self, ciphertext: EncryptedPayload, key_name: str = "default") -> bytes:
        """Transit decryption."""
    
    async def get_database_credentials(self, role: str) -> DatabaseCredentials:
        """Dynamic database credentials with automatic renewal."""
    
    async def issue_certificate(self, common_name: str, ttl: str = "24h") -> TLSCertificate:
        """Issue mTLS certificate from internal PKI."""
    
    async def wrap_secret(self, data: dict, ttl: str = "5m") -> WrappedToken:
        """Response-wrap a secret for one-time delivery."""
```

**Secret Data Models**
```python
class SecretMetadata(BaseModel):
    classification: Literal["public", "internal", "confidential", "restricted"]
    owner: str  # user or service identity
    tenant_id: str
    rotation_policy: RotationPolicy | None
    expires_at: datetime | None
    tags: dict[str, str]
    compliance_frameworks: list[str]  # ["SOC2", "HIPAA", "PCI-DSS"]

class RotationPolicy(BaseModel):
    strategy: Literal["auto_generate", "callback_url", "manual"]
    interval_days: int
    notify_before_days: int = 7
    callback_url: str | None  # webhook to notify dependent services
    last_rotated: datetime | None
    
class SecretAuditEvent(BaseModel):
    timestamp: datetime
    action: Literal["read", "write", "delete", "rotate", "wrap", "unwrap"]
    actor: str  # user or service identity
    path: str
    source_ip: str
    result: Literal["success", "denied", "error"]
    reason: str | None
    tenant_id: str
```

### Credential Injection Patterns

**For Connectors (Agent-13 dependency)**
- Each connector stores credentials at `archon/connectors/{tenant_id}/{connector_id}/`
- OAuth tokens stored with refresh flow metadata:
  ```json
  {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "bearer",
    "expires_at": "2026-03-01T00:00:00Z",
    "scopes": ["read", "write"],
    "provider": "microsoft365",
    "oauth_metadata": {
      "client_id_ref": "archon/oauth-apps/microsoft365",
      "token_endpoint": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    }
  }
  ```
- Automatic token refresh 5 minutes before expiry (background task)
- Credential health checks: validate stored credentials still work (hourly)

**For LLM Providers (Agent-07 dependency)**
- Provider API keys at `archon/models/{provider}/api_key`
- Per-tenant overrides at `archon/tenants/{tenant_id}/models/{provider}/api_key`
- Key rotation without downtime (dual-key window: old key valid for 1 hour after rotation)

**For Infrastructure (Agent-17 dependency)**
- Dynamic cloud credentials via Vault AWS/Azure/GCP engines
- Kubernetes secrets synced from Vault via External Secrets Operator
- TLS certificates issued from Vault PKI, auto-renewed by cert-manager

### Automatic Rotation Engine

**Rotation Strategies**
1. **Auto-Generate**: Vault generates new value (passwords, API keys) → notifies dependent services via webhook → old value remains valid for grace period
2. **Callback**: Vault calls external API to generate new credential (e.g., rotate OAuth client secret at IdP) → stores result
3. **Manual**: Alert owner N days before expiry → owner rotates → Vault records new version
4. **Dynamic**: No rotation needed — Vault generates short-lived credentials on every request (database, cloud IAM)

**Rotation Workflow**
```
[Rotation Trigger] → [Generate New Secret] → [Store as New Version]
    → [Notify Dependents via Webhook] → [Grace Period (configurable)]
    → [Revoke Old Version] → [Audit Log Entry]
```

**Rotation Dashboard**
- Secrets approaching expiry (30/14/7/1 day warnings)
- Rotation history with success/failure tracking
- Overdue rotations flagged as compliance violations
- One-click emergency rotation with automatic dependent service restart

### Admin UI

**Secrets Explorer**
- Tree view of all secret paths (respecting RBAC — users only see their tenant's secrets)
- Create / Read / Update / Delete with confirmation dialogs
- Version history with diff view (shows which fields changed, not values)
- Metadata editor (classification, tags, rotation policy)
- Bulk operations (rotate all secrets matching a pattern, export metadata report)

**Credential Configuration Wizard**
- Step-by-step flow for adding new connector credentials:
  1. Select connector type (Microsoft 365, Salesforce, etc.)
  2. Choose auth method (OAuth 2.0, API Key, Basic, Certificate)
  3. For OAuth: redirect to provider's consent screen, capture tokens, store in Vault
  4. For API Key: paste key → validate → classify → store
  5. Set rotation policy
  6. Test connection

**Audit Trail**
- Real-time stream of all Vault operations
- Filter by: actor, path, action, result, time range, tenant
- Export for compliance audits
- Integration with Agent-19 (governance audit log)

### Security Hardening

- **Zero plaintext at rest**: All secrets encrypted with Vault's barrier encryption (AES-256-GCM)
- **Zero plaintext in transit**: mTLS between all services and Vault
- **Zero plaintext in logs**: Secret values NEVER appear in logs, traces, or error messages. The SDK strips them automatically.
- **Envelope encryption**: Application data encrypted with DEKs, DEKs encrypted with Vault's master key
- **Break-glass procedure**: Emergency access with dual-approval (requires 2 platform admins) + full audit trail
- **Secret scanning**: Pre-commit hook + CI pipeline scans for accidentally committed secrets (trufflehog + custom patterns)

### Air-Gapped Deployment Support

- Vault deployed as StatefulSet in Kubernetes with Raft storage backend (no external dependencies)
- Auto-unseal via Kubernetes KMS plugin or manual Shamir ceremony
- Offline root CA for PKI engine
- SOPS fallback: if Vault is unavailable, secrets can be stored as SOPS-encrypted YAML files (age keys)
- Sealed secrets for GitOps workflows (Bitnami Sealed Secrets as secondary backend)

## Output Structure

```
security/
├── vault/
│   ├── __init__.py
│   ├── client.py              # Vault client wrapper (hvac)
│   ├── config.py              # Vault connection settings
│   ├── engines/
│   │   ├── kv.py              # KV-v2 secrets engine
│   │   ├── database.py        # Dynamic database credentials
│   │   ├── pki.py             # PKI certificate issuance
│   │   ├── transit.py         # Encryption-as-a-Service
│   │   └── cloud.py           # AWS/Azure/GCP dynamic credentials
│   ├── policies/
│   │   ├── platform_admin.hcl
│   │   ├── tenant_admin.hcl
│   │   ├── agent_executor.hcl
│   │   ├── connector_service.hcl
│   │   └── auditor.hcl
│   ├── rotation/
│   │   ├── engine.py          # Rotation orchestrator
│   │   ├── strategies.py      # Auto-generate, callback, manual
│   │   └── scheduler.py       # Cron-based rotation triggers
│   └── audit/
│       ├── logger.py          # Vault audit log parser
│       └── compliance.py      # Compliance report generator

backend/app/secrets/
├── __init__.py
├── manager.py                 # SecretsManager (unified SDK)
├── models.py                  # SecretMetadata, RotationPolicy, etc.
├── middleware.py               # Request-scoped secret context injection
├── dependencies.py            # FastAPI dependencies for secret access
└── exceptions.py              # SecretNotFound, AccessDenied, RotationFailed

backend/app/routers/secrets.py    # Admin API endpoints
backend/app/routers/credentials.py # Connector credential management API

frontend/src/pages/secrets/
├── SecretsExplorer.tsx
├── SecretDetail.tsx
├── CredentialWizard.tsx
├── RotationDashboard.tsx
└── SecretAuditLog.tsx

infra/vault/
├── helm-values.yaml           # Vault Helm chart configuration
├── vault-init-job.yaml        # K8s Job for Vault initialization
├── external-secrets.yaml      # External Secrets Operator config
├── vault-agent-injector.yaml  # Sidecar injector for pods
└── policies/                  # Terraform-managed Vault policies

tests/
├── test_secrets/
│   ├── test_manager.py
│   ├── test_rotation.py
│   ├── test_kv_engine.py
│   ├── test_transit.py
│   ├── test_pki.py
│   ├── test_policies.py
│   └── test_credential_wizard.py
```

## API Endpoints

```
POST   /api/v1/secrets/                    # Create secret
GET    /api/v1/secrets/{path}              # Read secret (RBAC-gated)
PUT    /api/v1/secrets/{path}              # Update secret
DELETE /api/v1/secrets/{path}              # Soft-delete secret
GET    /api/v1/secrets/{path}/versions     # List versions
POST   /api/v1/secrets/{path}/rotate       # Trigger rotation
POST   /api/v1/secrets/encrypt             # Transit encrypt
POST   /api/v1/secrets/decrypt             # Transit decrypt
GET    /api/v1/secrets/audit               # Audit log (paginated)
POST   /api/v1/secrets/wrap                # Response-wrap a secret
GET    /api/v1/secrets/health              # Vault health + rotation status

POST   /api/v1/credentials/oauth/initiate  # Start OAuth flow for connector
GET    /api/v1/credentials/oauth/callback  # OAuth callback handler
POST   /api/v1/credentials/validate        # Test stored credentials
GET    /api/v1/credentials/{connector_id}  # Get credential metadata (never values)
POST   /api/v1/credentials/{connector_id}/rotate  # Rotate connector credential
```

## Verify Commands

```bash
# Secrets manager importable
cd ~/Scripts/Archon && python -c "from backend.app.secrets.manager import SecretsManager; print('OK')"

# Vault client importable  
cd ~/Scripts/Archon && python -c "from security.vault.client import VaultClient; print('OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_secrets/ --tb=short -q

# Vault Helm values are valid YAML
cd ~/Scripts/Archon && python -c "import yaml; yaml.safe_load(open('infra/vault/helm-values.yaml')); print('OK')"

# No plaintext secrets in codebase
cd ~/Scripts/Archon && ! grep -rn 'password\s*=\s*"[^"]*"' --include='*.py' backend/ security/ || echo 'FAIL: Hardcoded secrets found'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Vault initializes and unseals in Docker Compose AND Kubernetes
- [ ] SecretsManager SDK works for get/put/delete/rotate/encrypt/decrypt
- [ ] Dynamic database credentials generate with configurable TTL
- [ ] PKI engine issues valid mTLS certificates
- [ ] Transit encryption round-trips correctly for arbitrary payloads
- [ ] Rotation engine rotates secrets on schedule with webhook notification
- [ ] OAuth credential wizard completes full flow for at least 3 providers (Microsoft, Google, Salesforce)
- [ ] RBAC enforces tenant isolation (tenant A cannot read tenant B's secrets)
- [ ] Break-glass procedure works with dual approval
- [ ] Audit log captures every secret access with actor, path, action, result
- [ ] Zero plaintext secrets in logs, traces, or error messages (verified by automated scan)
- [ ] Air-gapped mode works with Raft storage + Shamir unseal
- [ ] All endpoints match `contracts/openapi.yaml`
- [ ] 85%+ test coverage
- [ ] Admin UI renders secrets tree, credential wizard, rotation dashboard
