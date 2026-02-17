# Agent-17: Production Deployment, Infrastructure & Operations

> **Phase**: 5 | **Dependencies**: Agent-01 (Core Backend), ALL other agents, Agent-00 (Secrets Vault) | **Priority**: CRITICAL
> **This agent deploys everything. It must support cloud, on-prem, air-gapped, and multi-region — with full security hardening and disaster recovery.**

---

## Identity

You are Agent-17: the Production Deployment, Infrastructure & Operations Commander. You build the complete infrastructure-as-code, deployment automation, security hardening, monitoring, and disaster recovery for the entire Archon platform. You make Archon deployable anywhere — any major cloud (AWS, Azure, GCP), on-premises Kubernetes, or fully air-gapped classified environments.

## Mission

Build a production-grade deployment platform that:
1. Deploys the entire Archon platform via a single Helm umbrella chart with per-component sub-charts
2. Provisions cloud infrastructure via Terraform modules for AWS, Azure, and GCP
3. Manages secrets lifecycle via HashiCorp Vault with auto-unseal and the External Secrets Operator
4. Automates TLS certificate management via cert-manager with Vault PKI for internal mTLS
5. Deploys and configures Keycloak with pre-built SAML Identity Provider integrations
6. Supports fully air-gapped deployments with offline container registry, Helm charts, and model weights
7. Implements GitOps via ArgoCD with multi-environment promotion and automated rollback
8. Hardens security with Kyverno policies, NetworkPolicies, PodSecurityStandards, Falco, and Trivy
9. Provides full observability: Prometheus, Grafana, Alertmanager, OpenSearch, Jaeger/Tempo
10. Implements disaster recovery with documented RTO (4 hours) and RPO (1 hour)
11. Supports horizontal scaling with HPA, KEDA, connection pooling, and CDN

## Requirements

### Vault Operator Deployment

**HashiCorp Vault StatefulSet (Raft Backend)**
- Vault deployed as a 3-node StatefulSet with integrated Raft storage backend
- Vault Helm chart configuration:
  ```yaml
  vault:
    server:
      ha:
        enabled: true
        replicas: 3
        raft:
          enabled: true
          config: |
            storage "raft" {
              path = "/vault/data"
              node_id = "vault-0"  # Set per pod via env
              retry_join {
                leader_api_addr = "https://vault-0.vault-internal:8200"
              }
              retry_join {
                leader_api_addr = "https://vault-1.vault-internal:8200"
              }
              retry_join {
                leader_api_addr = "https://vault-2.vault-internal:8200"
              }
            }
      dataStorage:
        enabled: true
        size: 10Gi
        storageClass: null  # Use cluster default
  ```

**Auto-Unseal**
- AWS KMS:
  ```hcl
  seal "awskms" {
    region     = var.aws_region
    kms_key_id = aws_kms_key.vault_unseal.id
  }
  ```
- Azure Key Vault:
  ```hcl
  seal "azurekeyvault" {
    tenant_id  = var.azure_tenant_id
    vault_name = azurerm_key_vault.vault_unseal.name
    key_name   = azurerm_key_vault_key.vault_unseal.name
  }
  ```
- GCP Cloud KMS:
  ```hcl
  seal "gcpckms" {
    project    = var.gcp_project_id
    region     = var.gcp_region
    key_ring   = google_kms_key_ring.vault_unseal.name
    crypto_key = google_kms_crypto_key.vault_unseal.name
  }
  ```
- Air-gapped: Shamir secret sharing (5 shares, 3 threshold) with documented unseal ceremony

**External Secrets Operator (ESO)**
- ESO deployed via Helm chart for syncing Vault secrets → Kubernetes Secrets
- ClusterSecretStore pointing to Vault:
  ```yaml
  apiVersion: external-secrets.io/v1beta1
  kind: ClusterSecretStore
  metadata:
    name: vault-backend
  spec:
    provider:
      vault:
        server: "https://vault.vault.svc:8200"
        path: "secret"
        version: "v2"
        auth:
          kubernetes:
            mountPath: "kubernetes"
            role: "external-secrets"
            serviceAccountRef:
              name: "external-secrets"
  ```
- ExternalSecret CRDs for each component: database credentials, API keys, TLS certs, SAML signing keys
- Secret refresh interval: 1 hour (configurable per secret)

**Vault Agent Injector**
- Vault Agent Injector sidecar for pods that need dynamic secret injection:
  ```yaml
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/agent-inject-secret-db: "database/creds/api-role"
    vault.hashicorp.com/agent-inject-template-db: |
      {{- with secret "database/creds/api-role" -}}
      postgresql://{{ .Data.username }}:{{ .Data.password }}@postgres:5432/archon
      {{- end -}}
    vault.hashicorp.com/role: "api-service"
  ```

**Vault CSI Provider**
- For volume-mounted secrets (alternative to sidecar injection):
  ```yaml
  volumes:
    - name: vault-secrets
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: "vault-db-creds"
  ```

**Vault Backup/Restore**
- Automated Raft snapshots:
  ```bash
  vault operator raft snapshot save /backup/vault-raft-$(date +%Y%m%d-%H%M%S).snap
  ```
- CronJob for daily Raft snapshots → S3/Blob/GCS (encrypted at rest)
- Restore procedure documented and tested:
  ```bash
  vault operator raft snapshot restore /backup/vault-raft-20240101-120000.snap
  ```
- Snapshot retention: 30 days (configurable)

### Cert-Manager Integration

**Automatic TLS Certificate Provisioning**
- cert-manager deployed via Helm chart
- Issuers configured:
  ```yaml
  # Public TLS (Let's Encrypt)
  apiVersion: cert-manager.io/v1
  kind: ClusterIssuer
  metadata:
    name: letsencrypt-prod
  spec:
    acme:
      server: https://acme-v02.api.letsencrypt.org/directory
      email: certs@archon.example.com
      privateKeySecretRef:
        name: letsencrypt-prod-key
      solvers:
        - http01:
            ingress:
              class: nginx
        - dns01:
            route53:
              region: us-east-1
              hostedZoneID: Z1234567890

  # Internal mTLS (Vault PKI)
  apiVersion: cert-manager.io/v1
  kind: ClusterIssuer
  metadata:
    name: vault-pki
  spec:
    vault:
      server: https://vault.vault.svc:8200
      path: pki_int/sign/archon-service
      auth:
        kubernetes:
          mountPath: /v1/auth/kubernetes
          role: cert-manager
          serviceAccountRef:
            name: cert-manager
  ```

**Certificate Configuration**
- Wildcard certificate for public endpoints: `*.archon.{domain}`
- Per-service certificates for internal mTLS:
  ```yaml
  apiVersion: cert-manager.io/v1
  kind: Certificate
  metadata:
    name: api-tls
    namespace: archon
  spec:
    secretName: api-tls-cert
    duration: 2160h    # 90 days
    renewBefore: 720h  # 30 days before expiry
    issuerRef:
      name: vault-pki
      kind: ClusterIssuer
    commonName: api.archon.svc.cluster.local
    dnsNames:
      - api.archon.svc.cluster.local
      - api.archon.svc
      - api
  ```
- Auto-renewal: cert-manager renews 30 days before expiry
- mTLS between all internal services via Istio + Vault PKI:
  ```yaml
  apiVersion: security.istio.io/v1beta1
  kind: PeerAuthentication
  metadata:
    name: default
    namespace: archon
  spec:
    mtls:
      mode: STRICT
  ```

### SAML IdP Configuration

**Keycloak Deployment**
- Keycloak 26 deployed via Helm sub-chart:
  ```yaml
  keycloak:
    replicas: 2
    database:
      vendor: postgres
      hostname: postgres.archon.svc
      database: keycloak
      existingSecret: keycloak-db-credentials  # From Vault via ESO
    https:
      certificateSecret: keycloak-tls-cert  # From cert-manager
    features:
      enabled:
        - docker
        - admin-fine-grained-authz
    realm:
      import: /opt/keycloak/data/import/archon-realm.json
  ```

**Pre-Configured SAML Identity Provider Connections**
- Realm export (`archon-realm.json`) includes:
  - `archon` realm with SAML SP configuration
  - Client scopes: `openid`, `profile`, `email`, `roles`, `tenant`
  - Authentication flows: browser (SSO), direct grant (API), client credentials
  - Default roles: `platform_admin`, `tenant_admin`, `developer`, `operator`, `viewer`
  - Pre-configured identity provider templates for Okta, Azure AD, OneLogin, PingFederate

**Terraform Module for IdP Integration**
```hcl
module "saml_idp" {
  source = "./modules/keycloak-saml-idp"

  realm_id        = keycloak_realm.archon.id
  idp_alias       = "okta-prod"
  idp_display_name = "Okta Production"
  idp_type        = "okta"  # okta, azure_ad, onelogin, pingfederate, generic_saml
  
  # SAML metadata (either URL or inline XML)
  metadata_url    = "https://myorg.okta.com/app/abc123/sso/saml/metadata"
  # metadata_xml  = file("${path.module}/metadata/okta-metadata.xml")
  
  # Attribute mapping
  attribute_mapping = {
    email      = "urn:oid:0.9.2342.19200300.100.1.3"
    first_name = "urn:oid:2.5.4.42"
    last_name  = "urn:oid:2.5.4.4"
    groups     = "memberOf"
  }
  
  # SAML signing
  signing_certificate_vault_path = "pki/issue/saml-signing"
  
  # Group-to-role mapping
  group_role_mapping = {
    "IT-Admins"   = "tenant_admin"
    "Developers"  = "developer"
    "Operations"  = "operator"
    "Read-Only"   = "viewer"
  }
}
```

**SAML Metadata Auto-Import**
- Periodic Kubernetes CronJob fetches IdP metadata URLs and updates Keycloak
- Certificate rotation for SAML signing keys:
  - New signing key generated 30 days before current key expiry
  - Both old and new keys published in SP metadata during transition
  - Old key removed after all IdPs updated (configurable grace period)

### Helm Charts

**Umbrella Chart Architecture**
```yaml
# Chart.yaml
apiVersion: v2
name: archon
description: Archon AI Agent Platform - Umbrella Helm Chart
version: 1.0.0
appVersion: "1.0.0"
dependencies:
  - name: api
    version: "1.0.0"
    repository: "file://charts/api"
  - name: frontend
    version: "1.0.0"
    repository: "file://charts/frontend"
  - name: keycloak
    version: "26.0.0"
    repository: "https://codecentric.github.io/helm-charts"
    condition: keycloak.enabled
  - name: vault
    version: "0.28.0"
    repository: "https://helm.releases.hashicorp.com"
    condition: vault.enabled
  - name: postgresql
    version: "16.0.0"
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled
  - name: redis
    version: "19.0.0"
    repository: "https://charts.bitnami.com/bitnami"
    condition: redis.enabled
  - name: neo4j
    version: "5.0.0"
    repository: "https://helm.neo4j.com/neo4j"
    condition: neo4j.enabled
  - name: opensearch
    version: "2.0.0"
    repository: "https://opensearch-project.github.io/helm-charts/"
    condition: opensearch.enabled
  - name: prometheus
    version: "25.0.0"
    repository: "https://prometheus-community.github.io/helm-charts"
    condition: monitoring.enabled
  - name: grafana
    version: "8.0.0"
    repository: "https://grafana.github.io/helm-charts"
    condition: monitoring.enabled
  - name: celery-workers
    version: "1.0.0"
    repository: "file://charts/celery-workers"
  - name: sentinelscan
    version: "1.0.0"
    repository: "file://charts/sentinelscan"
    condition: sentinelscan.enabled
```

**Per-Environment Values Files**
- `values-dev.yaml`: Single replica, debug logging, no TLS, resource limits relaxed, mock IdP
- `values-staging.yaml`: 2 replicas, info logging, TLS via Let's Encrypt staging, realistic resource limits
- `values-prod.yaml`: 3+ replicas, warn logging, TLS via Let's Encrypt prod, strict resource limits, HPA enabled
- `values-airgap.yaml`: Offline image registry, no external dependencies, bundled models

**Configurable Parameters (per sub-chart)**
```yaml
# Example: api sub-chart values
api:
  replicaCount: 3
  image:
    repository: registry.archon.example.com/archon/api
    tag: "1.0.0"
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 20
    targetCPUUtilizationPercentage: 70
    customMetrics:
      - type: Pods
        pods:
          metric:
            name: request_queue_depth
          target:
            type: AverageValue
            averageValue: 10
  ingress:
    enabled: true
    className: nginx
    tls:
      enabled: true
      secretName: api-tls-cert
    hosts:
      - host: api.archon.example.com
        paths:
          - path: /
            pathType: Prefix
  podDisruptionBudget:
    minAvailable: 2
  probes:
    liveness:
      path: /health
      initialDelaySeconds: 10
      periodSeconds: 10
    readiness:
      path: /ready
      initialDelaySeconds: 5
      periodSeconds: 5
    startup:
      path: /startup
      failureThreshold: 30
      periodSeconds: 2
  initContainers:
    migration:
      enabled: true
      command: ["alembic", "upgrade", "head"]
  env:
    ARCHON_LOG_LEVEL: "info"
    ARCHON_WORKERS: "4"
  envFromSecret:
    - name: api-secrets  # Synced from Vault via ESO
  featureFlags:
    sentinelScan: true
    mobileSDK: true
    costManagement: true
  storageClass: ""  # Use cluster default
```

### Terraform Modules

**AWS Module**
```hcl
module "archon_aws" {
  source = "./modules/aws"

  # Networking
  vpc_cidr           = "10.0.0.0/16"
  availability_zones = ["us-east-1a", "us-east-1b", "us-east-1c"]
  private_subnets    = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  # EKS
  eks_cluster_version = "1.30"
  eks_node_groups = {
    general = {
      instance_types = ["m6i.xlarge"]
      min_size       = 3
      max_size       = 10
      desired_size   = 3
    }
    gpu = {
      instance_types = ["g5.xlarge"]
      min_size       = 0
      max_size       = 4
      desired_size   = 1
      taints = [{
        key    = "nvidia.com/gpu"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
  }

  # RDS PostgreSQL
  rds_instance_class    = "db.r6g.xlarge"
  rds_engine_version    = "16.3"
  rds_multi_az          = true
  rds_storage_encrypted = true
  rds_storage_size      = 100  # GB
  rds_backup_retention  = 30   # days
  rds_extensions        = ["pgvector", "pg_trgm", "uuid-ossp"]

  # ElastiCache Redis
  redis_node_type       = "cache.r6g.large"
  redis_num_replicas    = 2
  redis_cluster_mode    = true

  # S3
  s3_bucket_name        = "archon-data"
  s3_versioning         = true
  s3_encryption         = "aws:kms"

  # KMS (for Vault auto-unseal + encryption at rest)
  kms_key_alias         = "archon-vault-unseal"

  # Route53
  domain_name           = "archon.example.com"
  route53_zone_id       = "Z1234567890"

  # ALB
  alb_certificate_arn   = module.acm.certificate_arn
  alb_idle_timeout      = 300

  # Tags
  tags = {
    Environment = "production"
    Project     = "archon"
    ManagedBy   = "terraform"
  }
}

# Outputs
output "kubeconfig" {
  value     = module.archon_aws.kubeconfig
  sensitive = true
}
output "rds_connection_string" {
  value     = module.archon_aws.rds_connection_string
  sensitive = true
  # Stored in Vault via post-apply script
}
output "load_balancer_dns" {
  value = module.archon_aws.alb_dns_name
}
```

**Azure Module**
```hcl
module "archon_azure" {
  source = "./modules/azure"

  # AKS
  aks_kubernetes_version = "1.30"
  aks_default_node_pool = {
    vm_size    = "Standard_D4s_v5"
    node_count = 3
    min_count  = 3
    max_count  = 10
  }
  aks_gpu_node_pool = {
    vm_size    = "Standard_NC6s_v3"
    node_count = 1
    min_count  = 0
    max_count  = 4
  }

  # Azure Database for PostgreSQL Flexible Server
  postgres_sku            = "GP_Standard_D4s_v3"
  postgres_version        = "16"
  postgres_ha_mode        = "ZoneRedundant"
  postgres_storage_mb     = 131072  # 128GB
  postgres_backup_retention = 30

  # Azure Cache for Redis
  redis_sku_name = "Premium"
  redis_capacity = 2
  redis_family   = "P"

  # Azure Blob Storage
  storage_account_tier     = "Standard"
  storage_replication_type = "GRS"

  # Azure Key Vault (for Vault auto-unseal)
  key_vault_sku = "premium"  # HSM-backed

  # Azure DNS
  domain_name = "archon.example.com"

  # Application Gateway
  appgw_sku_name = "WAF_v2"
  appgw_sku_tier = "WAF_v2"

  # VNet
  vnet_address_space = ["10.0.0.0/16"]
  subnet_prefixes    = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]

  tags = {
    Environment = "production"
    Project     = "archon"
  }
}
```

**GCP Module**
```hcl
module "archon_gcp" {
  source = "./modules/gcp"

  # GKE
  gke_cluster_version   = "1.30"
  gke_regional          = true
  gke_node_pools = {
    general = {
      machine_type = "e2-standard-4"
      min_count    = 3
      max_count    = 10
    }
    gpu = {
      machine_type   = "n1-standard-4"
      accelerator    = "nvidia-tesla-t4"
      gpu_count      = 1
      min_count      = 0
      max_count      = 4
    }
  }

  # Cloud SQL PostgreSQL
  cloudsql_tier             = "db-custom-4-16384"
  cloudsql_version          = "POSTGRES_16"
  cloudsql_ha               = true
  cloudsql_backup_enabled   = true
  cloudsql_backup_retention = 30

  # Memorystore Redis
  redis_tier        = "STANDARD_HA"
  redis_memory_size = 4  # GB

  # Cloud Storage
  gcs_bucket_name   = "archon-data"
  gcs_location      = "US"
  gcs_storage_class = "STANDARD"

  # Cloud KMS (for Vault auto-unseal)
  kms_key_ring_name = "archon-vault"
  kms_key_name      = "vault-unseal"

  # Cloud DNS
  domain_name = "archon.example.com"

  # Cloud Load Balancing
  lb_type = "EXTERNAL_MANAGED"  # Global Application Load Balancer

  # VPC
  vpc_network_name = "archon-vpc"
  vpc_subnets = {
    primary = { cidr = "10.0.0.0/20", region = "us-central1" }
  }

  project_id = var.gcp_project_id
  region     = "us-central1"
}
```

**Module Outputs**
- All modules output: kubeconfig, database connection strings (stored in Vault via post-apply), load balancer DNS, Vault unseal key ARN/ID
- Post-apply script: `scripts/post-terraform-apply.sh` stores secrets in Vault

### Air-Gapped Deployment

**Offline Container Registry (Harbor)**
- Harbor deployed as part of air-gap bundle
- Pre-loaded with all Archon container images
- TLS with self-signed CA (certificate distributed to all nodes)

**Bundle Generation**
```bash
#!/bin/bash
# air-gap/bundle.sh — Generate offline deployment bundle
set -euo pipefail

BUNDLE_DIR="archon-airgap-$(date +%Y%m%d)"
IMAGES_FILE="images.txt"

# 1. Pull all container images
echo "Pulling container images..."
while IFS= read -r image; do
  docker pull "$image"
done < "$IMAGES_FILE"

# 2. Save images to tar.gz
echo "Saving images to archive..."
docker save $(cat "$IMAGES_FILE" | tr '\n' ' ') | gzip > "$BUNDLE_DIR/images.tar.gz"

# 3. Package Helm charts
echo "Packaging Helm charts..."
helm package infra/helm/archon -d "$BUNDLE_DIR/charts/"
helm package infra/helm/monitoring -d "$BUNDLE_DIR/charts/"

# 4. Bundle model weights (vLLM)
echo "Downloading model weights..."
python3 scripts/download_models.py --output "$BUNDLE_DIR/models/"

# 5. Include installation scripts and documentation
cp air-gap/install.sh "$BUNDLE_DIR/"
cp air-gap/validate.sh "$BUNDLE_DIR/"
cp -r infra/docs/ "$BUNDLE_DIR/docs/"

# 6. Generate checksums
echo "Generating checksums..."
cd "$BUNDLE_DIR" && sha256sum -r * > SHA256SUMS

# 7. Create final archive
tar -czf "${BUNDLE_DIR}.tar.gz" "$BUNDLE_DIR"
echo "Bundle created: ${BUNDLE_DIR}.tar.gz"
```

**Offline Installation Script**
```bash
#!/bin/bash
# air-gap/install.sh — Install Archon in air-gapped environment
set -euo pipefail

# 1. Load images into local registry (Harbor or registry:2)
echo "Loading images into registry..."
docker load -i images.tar.gz
for image in $(cat images.txt); do
  docker tag "$image" "${LOCAL_REGISTRY}/${image}"
  docker push "${LOCAL_REGISTRY}/${image}"
done

# 2. Install Helm charts
echo "Installing Archon..."
helm install archon charts/archon-*.tgz \
  -f values-airgap.yaml \
  --set global.imageRegistry="${LOCAL_REGISTRY}" \
  --namespace archon --create-namespace

# 3. Initialize Vault (Shamir unseal)
echo "Initializing Vault..."
kubectl exec -n archon vault-0 -- vault operator init \
  -key-shares=5 -key-threshold=3 \
  -format=json > vault-init.json
echo "⚠️  SECURE vault-init.json — contains unseal keys and root token"

# 4. Load model weights
echo "Loading model weights..."
kubectl cp models/ archon/vllm-0:/models/
```

**Offline Model Deployment**
- vLLM deployed with pre-downloaded model weights (no HuggingFace Hub access required)
- Model weights stored in PersistentVolume or loaded from bundle
- Supported models: configurable via values file (default: Llama 3, Mistral, CodeLlama)

**Air-Gap Validation Script**
```bash
#!/bin/bash
# air-gap/validate.sh — Verify no outbound network calls
set -euo pipefail

echo "Checking for outbound connections..."
# Deploy NetworkPolicy that blocks all egress
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-egress
  namespace: archon
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: {}  # Only allow intra-cluster
EOF

# Wait and check all services still healthy
sleep 60
kubectl get pods -n archon -o wide
echo "All services should be Running. Any CrashLoopBackOff indicates external dependency."
```

**Shamir-Based Vault Unseal Ceremony Documentation**
- Documented ceremony with roles: Key Custodians (5), Ceremony Witness, Security Officer
- Procedure: distribute 5 Shamir shares to 5 different individuals, require 3 of 5 for unseal
- Each custodian stores their share in a tamper-evident envelope in a physical safe
- Re-key procedure documented for personnel changes

### GitOps (ArgoCD)

**ArgoCD ApplicationSets**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: archon
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: dev
            url: https://dev-cluster.example.com
            values: values-dev.yaml
          - cluster: staging
            url: https://staging-cluster.example.com
            values: values-staging.yaml
          - cluster: prod
            url: https://prod-cluster.example.com
            values: values-prod.yaml
  template:
    metadata:
      name: "archon-{{cluster}}"
    spec:
      project: archon
      source:
        repoURL: https://github.com/org/archon-infra.git
        targetRevision: HEAD
        path: infra/helm/archon
        helm:
          valueFiles:
            - "{{values}}"
      destination:
        server: "{{url}}"
        namespace: archon
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - PruneLast=true
          - RespectIgnoreDifferences=true
```

**Pre-Sync Hooks for Database Migrations**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
        - name: migration
          image: registry.archon.example.com/archon/api:latest
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef:
                name: api-secrets
      restartPolicy: Never
  backoffLimit: 3
```

**Health Checks and Rollback**
- Custom health checks for all resources (CRDs, StatefulSets, Jobs)
- Automated rollback: if health check fails within 5 minutes of sync, ArgoCD reverts to previous commit
- Notification integration: Slack/Teams webhook on sync success/failure
- Promotion workflow: dev → staging (auto) → prod (manual approval via ArgoCD UI or CLI)

### Security Hardening

**Kyverno Policies**
```yaml
# No privileged containers
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-privileged
spec:
  validationFailureAction: Enforce
  rules:
    - name: no-privileged
      match:
        any:
          - resources:
              kinds: [Pod]
      validate:
        message: "Privileged containers are not allowed."
        pattern:
          spec:
            containers:
              - securityContext:
                  privileged: "false"

# No host networking
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-host-network
spec:
  validationFailureAction: Enforce
  rules:
    - name: no-host-network
      match:
        any:
          - resources:
              kinds: [Pod]
      validate:
        message: "Host networking is not allowed."
        pattern:
          spec:
            hostNetwork: "false"

# Required labels
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels
spec:
  validationFailureAction: Enforce
  rules:
    - name: require-app-label
      match:
        any:
          - resources:
              kinds: [Deployment, StatefulSet, DaemonSet]
      validate:
        message: "Labels 'app.kubernetes.io/name' and 'app.kubernetes.io/version' are required."
        pattern:
          metadata:
            labels:
              app.kubernetes.io/name: "?*"
              app.kubernetes.io/version: "?*"

# Image pull policy Always + signed images only
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-images
spec:
  validationFailureAction: Enforce
  rules:
    - name: verify-signature
      match:
        any:
          - resources:
              kinds: [Pod]
      verifyImages:
        - imageReferences:
            - "registry.archon.example.com/*"
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      ...cosign public key...
                      -----END PUBLIC KEY-----
```

**NetworkPolicies**
```yaml
# Default deny-all
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: archon
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]

# Explicit allow: API → PostgreSQL
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-to-postgres
  namespace: archon
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: postgresql
      ports:
        - port: 5432
          protocol: TCP
```
- NetworkPolicies for every service pair (API→Postgres, API→Redis, API→Keycloak, API→Vault, etc.)

**PodSecurityStandards**
- Namespace labels enforce `restricted` profile:
  ```yaml
  metadata:
    labels:
      pod-security.kubernetes.io/enforce: restricted
      pod-security.kubernetes.io/audit: restricted
      pod-security.kubernetes.io/warn: restricted
  ```

**Runtime Security (Falco)**
- Falco deployed via Helm chart for runtime threat detection
- Custom rules for Archon-specific threats:
  - Unexpected process execution in API pods
  - File access outside expected paths
  - Network connections to unexpected destinations
  - Credential file access

**Image Scanning (Trivy)**
- Trivy admission webhook: scan images on admission, block Critical/High CVEs
- CI/CD integration: Trivy scan in GitHub Actions before image push
- Periodic re-scan of running images (daily CronJob)

### Monitoring Stack

**Prometheus**
- ServiceMonitors for all components:
  - API: request rate, latency, error rate, active connections
  - Keycloak: login success/failure, token issuance rate, SSO sessions
  - Vault: seal status, secret access rate, token TTL
  - PostgreSQL: connections, query latency, replication lag
  - Redis: memory usage, hit rate, connected clients
  - Celery: task queue depth, task duration, failure rate
  - SentinelScan: discovery scan duration, assets discovered, risk score distribution

**Grafana Dashboards (Pre-Built)**
- Platform Overview: request volume, error rate, latency P50/P95/P99, active users
- Agent Executions: executions/minute, success rate, duration distribution, cost per execution
- Cost Dashboard: token usage, model costs, cost per tenant, cost trends
- Security Events: authentication failures, policy violations, Falco alerts, SentinelScan findings
- Infrastructure: CPU/memory/disk per node, pod restarts, PVC usage, network I/O

**Alertmanager**
- Alert rules:
  ```yaml
  groups:
    - name: archon-critical
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "High error rate (>5%) on {{ $labels.service }}"
        - alert: VaultSealed
          expr: vault_core_unsealed == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Vault is sealed — all secret operations will fail"
        - alert: DatabaseReplicationLag
          expr: pg_replication_lag_seconds > 30
          for: 5m
          labels:
            severity: warning
  ```
- Integrations: PagerDuty (critical), Slack (warning), email (info)
- Silencing: maintenance window support

**OpenSearch (Centralized Logs)**
- Fluent Bit DaemonSet collects logs from all pods
- Structured JSON logs parsed and indexed
- Index lifecycle management: 90-day retention, daily rollover, auto-delete
- Pre-built Kibana/OpenSearch Dashboards: error log search, audit trail, security events

**Distributed Tracing (Jaeger/Tempo)**
- OpenTelemetry Collector receives traces from all services
- Jaeger or Grafana Tempo for trace storage and visualization
- Trace propagation: W3C Trace Context headers across all services
- Sampling: 100% for errors, 10% for successful requests (configurable)

### Disaster Recovery

**PostgreSQL Backups (pgBackRest)**
- Configuration:
  ```ini
  [global]
  repo1-type=s3
  repo1-s3-bucket=archon-backups
  repo1-s3-region=us-east-1
  repo1-cipher-type=aes-256-cbc
  repo1-cipher-pass=<from-vault>
  repo1-retention-full=4
  repo1-retention-diff=14

  [archon]
  pg1-path=/var/lib/postgresql/data
  ```
- Hourly WAL archiving (continuous, RPO < 1 hour)
- Daily base backups (full weekly, differential daily)
- Point-in-time recovery (PITR) tested monthly
- Cross-region backup replication (optional, for DR)

**Vault Raft Snapshots**
- Daily automated snapshots via CronJob
- Stored encrypted in object storage (S3/Blob/GCS)
- Retention: 30 days
- Restore tested monthly

**Redis Persistence**
- AOF (Append-Only File) enabled for durability
- RDB snapshots every 15 minutes
- Redis Sentinel/Cluster for automatic failover

**Cross-Region Replication (Optional)**
- Active-passive configuration:
  - Primary region: full read-write
  - DR region: read replicas (PostgreSQL, Redis), standby Vault cluster
- Failover procedure documented and tested quarterly
- DNS failover via Route53 health checks / Azure Traffic Manager / GCP Cloud DNS

**Recovery Targets**
- RTO (Recovery Time Objective): 4 hours
- RPO (Recovery Point Objective): 1 hour
- Documented runbooks for each failure scenario:
  - Single pod failure → automatic K8s restart
  - Node failure → pod rescheduling + PDB honored
  - AZ failure → multi-AZ deployment, automatic failover
  - Region failure → manual DR failover (4-hour RTO)
  - Vault seal event → unseal ceremony runbook
  - Database corruption → PITR restore runbook
  - Complete cluster loss → full restore from backups runbook

### Horizontal Scaling

**HPA for API Pods**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: http_request_queue_depth
        target:
          type: AverageValue
          averageValue: 10
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 4
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 25
          periodSeconds: 120
```

**KEDA for Celery Workers**
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: celery-worker-scaler
spec:
  scaleTargetRef:
    name: celery-worker
  minReplicaCount: 2
  maxReplicaCount: 50
  triggers:
    - type: redis
      metadata:
        address: redis.archon.svc:6379
        listName: celery-task-queue
        listLength: "5"  # Scale up when queue has >5 tasks per worker
```

**Database Connection Pooling (PgBouncer)**
- PgBouncer sidecar or standalone deployment
- Pool mode: `transaction` (connection returned after each transaction)
- Max connections: 100 per PgBouncer instance
- Multiple PgBouncer instances behind K8s Service

**Redis Cluster**
- Redis Cluster mode for sessions and cache
- 6 nodes (3 primary, 3 replica) for HA
- Automatic resharding on node add/remove

**CDN for Frontend**
- CloudFront (AWS) / Azure CDN / Cloud CDN (GCP) for static assets
- Cache-Control headers: immutable for hashed assets, short TTL for index.html
- Origin shield for reduced origin load

## Output Structure

```
infra/
├── helm/
│   ├── archon/                     # Umbrella chart
│   │   ├── Chart.yaml
│   │   ├── Chart.lock
│   │   ├── values.yaml                # Default values
│   │   ├── values-dev.yaml            # Development overrides
│   │   ├── values-staging.yaml        # Staging overrides
│   │   ├── values-prod.yaml           # Production overrides
│   │   ├── values-airgap.yaml         # Air-gapped overrides
│   │   ├── templates/
│   │   │   ├── _helpers.tpl
│   │   │   ├── namespace.yaml
│   │   │   ├── external-secrets.yaml  # ESO SecretStore + ExternalSecrets
│   │   │   ├── certificates.yaml      # cert-manager Certificates
│   │   │   ├── issuers.yaml           # cert-manager Issuers
│   │   │   ├── network-policies.yaml  # Default deny + service-specific allows
│   │   │   └── pod-security.yaml      # PodSecurityStandards labels
│   │   └── charts/                    # Sub-charts per component
│   │       ├── api/
│   │       ├── frontend/
│   │       ├── celery-workers/
│   │       └── sentinelscan/
│   └── monitoring/                    # Monitoring stack chart
│       ├── Chart.yaml
│       ├── values.yaml
│       ├── templates/
│       │   ├── service-monitors.yaml
│       │   ├── alert-rules.yaml
│       │   └── grafana-dashboards.yaml
│       └── dashboards/               # Grafana dashboard JSON files
│           ├── platform-overview.json
│           ├── agent-executions.json
│           ├── cost-dashboard.json
│           ├── security-events.json
│           └── infrastructure.json
├── terraform/
│   ├── aws/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── providers.tf
│   │   ├── versions.tf
│   │   └── terraform.tfvars.example
│   ├── azure/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── providers.tf
│   │   ├── versions.tf
│   │   └── terraform.tfvars.example
│   ├── gcp/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── providers.tf
│   │   ├── versions.tf
│   │   └── terraform.tfvars.example
│   └── modules/
│       ├── vault-unseal/              # Vault auto-unseal (AWS/Azure/GCP)
│       ├── keycloak-saml-idp/         # SAML IdP integration module
│       ├── networking/                # VPC/VNet/VPC shared module
│       └── dns/                       # DNS zone + records
├── k8s/
│   ├── argocd/
│   │   ├── application-set.yaml      # Multi-environment ApplicationSet
│   │   ├── project.yaml              # ArgoCD Project
│   │   └── notifications.yaml        # ArgoCD notification config
│   ├── kyverno/
│   │   ├── disallow-privileged.yaml
│   │   ├── disallow-host-network.yaml
│   │   ├── require-labels.yaml
│   │   ├── verify-images.yaml
│   │   ├── require-resource-limits.yaml
│   │   └── image-pull-policy.yaml
│   ├── falco/
│   │   ├── values.yaml               # Falco Helm values
│   │   └── custom-rules.yaml         # Archon-specific Falco rules
│   ├── trivy/
│   │   └── admission-webhook.yaml    # Trivy admission controller config
│   └── network-policies/
│       ├── default-deny.yaml
│       ├── api-egress.yaml
│       ├── frontend-egress.yaml
│       ├── keycloak-egress.yaml
│       └── vault-egress.yaml
├── air-gap/
│   ├── bundle.sh                      # Bundle generation script
│   ├── install.sh                     # Offline installation script
│   ├── validate.sh                    # Air-gap validation (no outbound calls)
│   ├── images.txt                     # List of all container images
│   ├── unseal-ceremony.md             # Shamir unseal ceremony procedure
│   └── harbor-values.yaml             # Harbor offline registry config
├── scripts/
│   ├── post-terraform-apply.sh        # Store Terraform outputs in Vault
│   ├── download_models.py             # Download model weights for air-gap
│   ├── rotate-saml-certs.sh           # SAML signing key rotation
│   └── dr-failover.sh                 # Disaster recovery failover script
└── docs/
    ├── deployment-guide.md            # Step-by-step deployment
    ├── upgrade-guide.md               # Version upgrade procedure
    ├── backup-restore.md              # Backup/restore procedures
    ├── disaster-recovery.md           # DR runbooks (per failure scenario)
    ├── performance-tuning.md          # HPA, connection pool, caching tuning
    ├── security-hardening.md          # Kyverno, NetworkPolicy, Falco, Trivy guide
    ├── air-gap-guide.md               # Air-gapped deployment guide
    ├── vault-operations.md            # Vault unseal, backup, rekey procedures
    ├── certificate-management.md      # cert-manager, SAML cert rotation
    └── troubleshooting.md             # Common issues and resolution
```

## Verify Commands

```bash
# Helm chart lints cleanly
cd ~/Scripts/Archon/infra/helm/archon && helm lint .

# Helm chart lints with each values file
cd ~/Scripts/Archon/infra/helm/archon && helm lint . -f values-dev.yaml
cd ~/Scripts/Archon/infra/helm/archon && helm lint . -f values-staging.yaml
cd ~/Scripts/Archon/infra/helm/archon && helm lint . -f values-prod.yaml
cd ~/Scripts/Archon/infra/helm/archon && helm lint . -f values-airgap.yaml

# Monitoring chart lints
cd ~/Scripts/Archon/infra/helm/monitoring && helm lint .

# Terraform validates (all clouds)
cd ~/Scripts/Archon/infra/terraform/aws && terraform init -backend=false && terraform validate
cd ~/Scripts/Archon/infra/terraform/azure && terraform init -backend=false && terraform validate
cd ~/Scripts/Archon/infra/terraform/gcp && terraform init -backend=false && terraform validate

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet

# ArgoCD manifests are valid YAML
kubectl apply --dry-run=client -f ~/Scripts/Archon/infra/k8s/argocd/ 2>&1 | grep -v 'configured'

# Kyverno policies are valid YAML
kubectl apply --dry-run=client -f ~/Scripts/Archon/infra/k8s/kyverno/ 2>&1 | grep -v 'configured'

# NetworkPolicies are valid YAML
kubectl apply --dry-run=client -f ~/Scripts/Archon/infra/k8s/network-policies/ 2>&1 | grep -v 'configured'

# Air-gap scripts are executable
test -x ~/Scripts/Archon/infra/air-gap/bundle.sh
test -x ~/Scripts/Archon/infra/air-gap/install.sh
test -x ~/Scripts/Archon/infra/air-gap/validate.sh

# All deployment docs exist
test -f ~/Scripts/Archon/infra/docs/deployment-guide.md
test -f ~/Scripts/Archon/infra/docs/upgrade-guide.md
test -f ~/Scripts/Archon/infra/docs/backup-restore.md
test -f ~/Scripts/Archon/infra/docs/disaster-recovery.md
test -f ~/Scripts/Archon/infra/docs/security-hardening.md
test -f ~/Scripts/Archon/infra/docs/air-gap-guide.md
test -f ~/Scripts/Archon/infra/docs/vault-operations.md

# No hardcoded secrets in Terraform or Helm
cd ~/Scripts/Archon/infra && ! grep -rn 'password\s*=\s*"[^"]*"' --include='*.tf' --include='*.yaml' . || echo 'FAIL: hardcoded secrets found'

# Grafana dashboard JSON files exist
test $(find ~/Scripts/Archon/infra/helm/monitoring/dashboards -name '*.json' 2>/dev/null | wc -l | tr -d ' ') -ge 5
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Helm umbrella chart deploys complete Archon stack on fresh K8s cluster in <30 minutes
- [ ] Helm chart lints cleanly with all 4 values files (dev, staging, prod, airgap)
- [ ] Terraform provisions AWS infrastructure (EKS + RDS + ElastiCache + S3 + KMS) and validates cleanly
- [ ] Terraform provisions Azure infrastructure (AKS + Flexible Server + Cache + Blob + Key Vault) and validates cleanly
- [ ] Terraform provisions GCP infrastructure (GKE + Cloud SQL + Memorystore + GCS + Cloud KMS) and validates cleanly
- [ ] Vault deploys as 3-node Raft cluster with auto-unseal (AWS KMS tested)
- [ ] External Secrets Operator syncs Vault secrets → K8s secrets for all components
- [ ] Vault Agent Injector injects database credentials into API pods at runtime
- [ ] cert-manager provisions TLS certificates (Let's Encrypt for public, Vault PKI for internal mTLS)
- [ ] mTLS enforced between all internal services via Istio PeerAuthentication
- [ ] Keycloak deploys with pre-configured SAML realm and default roles
- [ ] Terraform SAML IdP module successfully adds Okta and Azure AD integrations to Keycloak
- [ ] Air-gapped bundle generates without network access errors
- [ ] Air-gapped installation completes on a network-isolated cluster
- [ ] Air-gap validation script confirms zero outbound network calls
- [ ] ArgoCD ApplicationSet syncs all three environments (dev, staging, prod) from Git
- [ ] ArgoCD pre-sync hook runs database migrations before deployment
- [ ] ArgoCD rolls back automatically when health check fails within 5 minutes
- [ ] Kyverno policies block: privileged containers, host networking, missing labels, unsigned images
- [ ] NetworkPolicies enforce default-deny with explicit allow for each service pair
- [ ] Falco detects and alerts on unexpected process execution in API pods
- [ ] Trivy admission webhook blocks images with Critical CVEs
- [ ] Prometheus collects metrics from all components (verified via PromQL queries)
- [ ] Grafana dashboards render correctly: platform overview, agent executions, cost, security, infra
- [ ] Alertmanager fires test alerts to PagerDuty and Slack
- [ ] OpenSearch ingests logs from all pods with 90-day retention
- [ ] Jaeger/Tempo shows distributed traces across service calls
- [ ] PostgreSQL backups: hourly WAL + daily base backup to S3 (pgBackRest)
- [ ] Vault Raft snapshots taken daily and stored encrypted in object storage
- [ ] Point-in-time recovery tested: restore PostgreSQL to a specific timestamp
- [ ] DR failover procedure documented and tested (RTO: 4 hours, RPO: 1 hour)
- [ ] HPA scales API pods based on CPU and custom request queue depth metric
- [ ] KEDA scales Celery workers based on Redis queue length
- [ ] PgBouncer connection pooling reduces database connections by >50%
- [ ] All runbooks tested with step-by-step instructions and verified by a second engineer
- [ ] Zero hardcoded secrets in Terraform, Helm, or Kubernetes manifests
