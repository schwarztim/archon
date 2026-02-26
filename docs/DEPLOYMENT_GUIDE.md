# Archon — Deployment Guide

> Version 1.0 | February 2026

---

## 1. Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| Docker | 24.x | Container runtime |
| Docker Compose | 2.x | Local development |
| Kubernetes | 1.29+ | Production deployment |
| Helm | 3.14+ | Chart management |
| kubectl | 1.29+ | Cluster interaction |
| Terraform | 1.7+ | Cloud infrastructure |

---

## 2. Local Development (Docker Compose)

### 2.1 Clone and configure

```bash
git clone https://github.com/your-org/archon.git
cd archon
cp env.example .env
# Edit .env with your secrets (JWT_SECRET, database passwords, etc.)
```

### 2.2 Start all services

```bash
docker compose up -d
```

This starts: PostgreSQL, Redis, Keycloak, MinIO, Backend API, Frontend, Gateway.

### 2.3 Verify health

```bash
curl http://localhost:8000/health   # Backend
curl http://localhost:8080/health   # MCP Gateway
curl http://localhost:3000          # Frontend
```

### 2.4 Default credentials (dev only)

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | admin / admin |
| Backend API | http://localhost:8000/docs | JWT via `/auth/dev-login` |
| Keycloak | http://localhost:8180 | admin / admin |
| MinIO | http://localhost:9001 | minioadmin / minioadmin |

---

## 3. Kubernetes (Production)

### 3.1 Namespace setup

```bash
kubectl create namespace archon
kubectl create namespace archon-staging
```

### 3.2 Secrets

All secrets are managed via HashiCorp Vault. Bootstrap Vault:

```bash
# Apply Vault Helm chart
helm upgrade --install vault infra/helm/vault \
  --namespace vault \
  --create-namespace \
  -f infra/helm/vault/values.yaml

# Initialize and unseal (first time only)
bash infra/helm/vault/vault-init.sh

# Apply Archon policy
vault policy write archon infra/helm/vault/vault-policy.hcl
```

### 3.3 Deploy with Helm

```bash
# Production
helm upgrade --install archon infra/helm/archon-platform \
  --namespace archon \
  --set backend.image.tag=<SHA> \
  --set frontend.image.tag=<SHA> \
  --set gateway.image.tag=<SHA> \
  --set backend.config.databaseUrl="postgresql+asyncpg://..." \
  --set backend.config.redisUrl="redis://..." \
  -f infra/helm/archon-platform/values.yaml

# Staging (uses ArgoCD)
# See infra/argocd/application.yaml
```

### 3.4 Verify deployment

```bash
kubectl get pods -n archon
kubectl rollout status deployment/archon-backend -n archon
kubectl rollout status deployment/archon-gateway -n archon
```

---

## 4. Azure Container Apps (Recommended for Cloud)

### 4.1 Infrastructure provisioning

```bash
cd infra/terraform/azure
terraform init
terraform plan -var-file="prod.tfvars"
terraform apply -var-file="prod.tfvars"
```

### 4.2 Required Azure resources

- **Azure Container Apps** — backend, gateway, frontend
- **Azure Database for PostgreSQL Flexible Server** — primary database
- **Azure Cache for Redis** — session cache and task queue
- **Azure Container Registry** — image storage
- **Azure Key Vault** — secrets management (replaces HashiCorp Vault in cloud)
- **Azure Storage** — object storage (replaces MinIO)

### 4.3 Environment variables

Set these on each Container App:

```
ARCHON_DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/archon
ARCHON_REDIS_URL=rediss://<host>:6380/0
ARCHON_JWT_SECRET=<vault-secret>
ARCHON_AUTH_DEV_MODE=false
ARCHON_SMTP_HOST=<smtp-host>
ARCHON_SMTP_PORT=587
ARCHON_SMTP_FROM=archon@yourdomain.com
ARCHON_SMTP_USERNAME=<smtp-user>
ARCHON_SMTP_PASSWORD=<smtp-password>
ARCHON_TEAMS_WEBHOOK_URL=<teams-incoming-webhook>
```

### 4.4 Container App scaling rules

```yaml
# backend
minReplicas: 2
maxReplicas: 20
rules:
  - name: http-scale
    http:
      metadata:
        concurrentRequests: "50"

# gateway
minReplicas: 1
maxReplicas: 5
```

---

## 5. CI/CD Pipeline

### 5.1 GitHub Actions workflows

| Workflow | Trigger | Steps |
|---------|---------|-------|
| `ci.yml` | Push / PR to `main` | lint, test, test-gateway, build, security-scan |
| `cd.yml` | Push to `main` | build+push images, deploy to staging |

### 5.2 Required secrets (GitHub repository secrets)

```
GHCR_TOKEN          — GitHub Container Registry write token
KUBE_CONFIG_STAGING — kubeconfig for staging cluster (base64)
KUBE_CONFIG_PROD    — kubeconfig for prod cluster (base64)
```

---

## 6. SMTP Configuration

Configure SMTP for email notifications via environment variables or the Settings UI:

```
ARCHON_SMTP_HOST=smtp.sendgrid.net
ARCHON_SMTP_PORT=587
ARCHON_SMTP_FROM=archon@yourdomain.com
ARCHON_SMTP_USERNAME=apikey
ARCHON_SMTP_PASSWORD=<sendgrid-api-key>
```

Or via the Settings API:
```bash
PUT /api/v1/settings
{
  "notifications": {
    "smtp_host": "smtp.sendgrid.net",
    "smtp_port": 587,
    "smtp_from": "archon@yourdomain.com",
    "smtp_username": "apikey",
    "smtp_password": "<key>"
  }
}
```

Test with:
```bash
POST /api/v1/settings/notifications/test
{ "channel": "email", "recipient": "test@example.com" }
```

---

## 7. Microsoft Teams Integration

Add a Teams Incoming Webhook connector to your Teams channel, then configure:

```
ARCHON_TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
```

Or in the Settings UI under **Notifications → Teams Webhook URL**.

Test with:
```bash
POST /api/v1/settings/notifications/test
{ "channel": "teams" }
```

---

## 8. Health & Readiness Checks

| Endpoint | Service | Type |
|---------|---------|------|
| `GET /health` | Backend | Liveness |
| `GET /health/ready` | Backend | Readiness |
| `GET /health` | Gateway | Liveness |
| `GET /metrics` | Backend | Prometheus scrape |

---

## 9. Troubleshooting

### Database connection refused
```bash
kubectl logs deployment/archon-backend -n archon | grep "database"
# Ensure DATABASE_URL is correct and PostgreSQL is reachable
```

### SMTP send failures
```bash
# Check backend logs
kubectl logs deployment/archon-backend -n archon | grep "smtp_send_failed"
# Verify SMTP credentials and TLS support on port 587
```

### Gateway plugin not loading
```bash
kubectl logs deployment/archon-gateway -n archon | grep "plugin"
# Ensure YAML files in gateway/plugins/ are valid
```

---

*This guide is maintained alongside the codebase. For questions, open an issue or see `docs/CONTRIBUTING.md`.*
