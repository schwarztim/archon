# Archon Deployment Guide

> Comprehensive guide for deploying the Archon AI Orchestration Platform on Kubernetes — from local development clusters to production multi-cloud environments.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start with Helm](#quick-start-with-helm)
3. [Cloud-Specific Deployment](#cloud-specific-deployment)
   - [AWS EKS](#aws-eks)
   - [Azure AKS](#azure-aks)
   - [GCP GKE](#gcp-gke)
4. [ArgoCD GitOps Setup](#argocd-gitops-setup)
5. [Monitoring Setup](#monitoring-setup)
6. [Air-Gap / Offline Installation](#air-gap--offline-installation)
7. [Configuration Reference](#configuration-reference)
8. [Upgrading](#upgrading)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| `kubectl` | 1.28+ | Kubernetes CLI |
| `helm` | 3.14+ | Helm chart management |
| `terraform` | 1.5+ | Infrastructure provisioning (cloud deployments) |
| `docker` | 24+ | Container image builds (optional) |
| `argocd` CLI | 2.10+ | GitOps management (optional) |

### Kubernetes Cluster Requirements

- **Kubernetes**: 1.28 or later
- **Nodes**: Minimum 3 nodes, each with 4 CPU / 8 GB RAM
- **Storage**: Default StorageClass configured (e.g., `gp3`, `managed-csi`, `standard`)
- **Ingress controller**: NGINX, ALB, or cloud-native ingress
- **cert-manager** (recommended): For automatic TLS certificate provisioning

### External Dependencies

Archon requires **PostgreSQL 16+** and **Redis 7+**. You can either:

- Provision them via the included Terraform modules (recommended for production)
- Use managed services configured externally
- Run them in-cluster via sub-charts (development only)

---

## Quick Start with Helm

Deploy Archon on any Kubernetes cluster in under 5 minutes.

### 1. Add prerequisites

```bash
# Create the namespace
kubectl create namespace archon

# Create the database secret
kubectl create secret generic archon-db \
  --namespace archon \
  --from-literal=password='YOUR_DB_PASSWORD'

# Create the Redis secret
kubectl create secret generic archon-redis \
  --namespace archon \
  --from-literal=password='YOUR_REDIS_PASSWORD'
```

### 2. Install the Helm chart

```bash
cd infra/helm/archon

helm install archon . \
  --namespace archon \
  --set postgresql.host=YOUR_PG_HOST \
  --set postgresql.existingSecret=archon-db \
  --set redis.host=YOUR_REDIS_HOST \
  --set redis.existingSecret=archon-redis \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=archon.example.com \
  --wait --timeout 10m
```

### 3. Verify deployment

```bash
# Check all pods are running
kubectl get pods -n archon

# Test the health endpoint
kubectl port-forward svc/archon-backend 8000:8000 -n archon &
curl http://localhost:8000/health
```

### Minimal values override (values-quickstart.yaml)

```yaml
backend:
  replicaCount: 1
  autoscaling:
    enabled: false
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi

frontend:
  replicaCount: 1

postgresql:
  host: postgres.example.com
  existingSecret: archon-db

redis:
  host: redis.example.com
  existingSecret: archon-redis

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: archon.local
      paths:
        - path: /api
          pathType: Prefix
          service: backend
        - path: /
          pathType: Prefix
          service: frontend
```

```bash
helm install archon . -n archon -f values-quickstart.yaml --wait
```

---

## Cloud-Specific Deployment

Each cloud provider has a dedicated Terraform module under `infra/terraform/` that provisions the Kubernetes cluster, managed database, Redis, object storage, and networking.

### AWS EKS

#### 1. Configure Terraform variables

```bash
cd infra/terraform/aws

cat > terraform.tfvars <<'EOF'
aws_region        = "us-east-1"
environment       = "production"
cluster_name      = "archon-prod"
kubernetes_version = "1.30"

# Networking
vpc_cidr             = "10.0.0.0/16"
private_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
public_subnet_cidrs  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

# Compute
node_instance_types = ["t3.xlarge"]
node_desired_size   = 3
node_min_size       = 2
node_max_size       = 10

# Database
rds_instance_class        = "db.r6g.large"
rds_allocated_storage     = 100
rds_max_allocated_storage = 500
db_password               = "CHANGE_ME"   # Use -var or TF_VAR_ env var in practice

# Cache
redis_node_type = "cache.r6g.large"
EOF
```

#### 2. Provision infrastructure

```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

#### 3. Configure kubectl

```bash
aws eks update-kubeconfig \
  --name archon-prod \
  --region us-east-1
```

#### 4. Deploy Archon

```bash
# Retrieve outputs
PG_HOST=$(terraform output -raw rds_endpoint)
REDIS_HOST=$(terraform output -raw redis_endpoint)

cd ../../helm/archon
helm install archon . -n archon --create-namespace \
  --set postgresql.host="$PG_HOST" \
  --set postgresql.existingSecret=archon-db \
  --set redis.host="$REDIS_HOST" \
  --set redis.existingSecret=archon-redis \
  --set ingress.enabled=true \
  --set ingress.className=alb \
  --set 'ingress.annotations.kubernetes\.io/ingress\.class=alb' \
  --wait --timeout 10m
```

### Azure AKS

#### 1. Configure and provision

```bash
cd infra/terraform/azure

cat > terraform.tfvars <<'EOF'
azure_location     = "eastus2"
environment        = "production"
cluster_name       = "archon-prod"
kubernetes_version = "1.30"

vnet_address_space = "10.0.0.0/16"
aks_subnet_cidr    = "10.0.0.0/20"
db_subnet_cidr     = "10.0.16.0/24"

node_vm_size  = "Standard_D4s_v5"
node_count    = 3
node_min_count = 2
node_max_count = 10

postgres_sku_name   = "GP_Standard_D4s_v3"
postgres_storage_mb = 131072
db_password         = "CHANGE_ME"

redis_capacity = 2
redis_family   = "C"
redis_sku_name = "Standard"
EOF

terraform init && terraform plan -out=tfplan && terraform apply tfplan
```

#### 2. Configure kubectl and deploy

```bash
az aks get-credentials \
  --resource-group archon-prod-production-rg \
  --name archon-prod

# Then deploy with Helm as shown in the Quick Start section,
# substituting the Terraform outputs for PG/Redis hosts.
```

### GCP GKE

#### 1. Configure and provision

```bash
cd infra/terraform/gcp

cat > terraform.tfvars <<'EOF'
gcp_project_id = "my-project-id"
gcp_region     = "us-central1"
environment    = "production"
cluster_name   = "archon-prod"

nodes_subnet_cidr = "10.0.0.0/20"
pods_cidr         = "10.4.0.0/14"
services_cidr     = "10.8.0.0/20"
master_cidr       = "172.16.0.0/28"

node_machine_type = "e2-standard-4"
node_count        = 3
node_min_count    = 2
node_max_count    = 10

cloudsql_tier      = "db-custom-4-16384"
cloudsql_disk_size = 100
db_password        = "CHANGE_ME"

redis_memory_size_gb = 4
EOF

terraform init && terraform plan -out=tfplan && terraform apply tfplan
```

#### 2. Configure kubectl and deploy

```bash
gcloud container clusters get-credentials archon-prod \
  --region us-central1 \
  --project my-project-id

# Then deploy with Helm using Terraform outputs.
```

---

## ArgoCD GitOps Setup

Archon ships with an ArgoCD Application manifest at `infra/argocd/application.yaml` that enables fully automated GitOps deployment.

### 1. Install ArgoCD

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=available deployment/argocd-server \
  -n argocd --timeout=300s
```

### 2. Access the ArgoCD UI

```bash
# Get the initial admin password
argocd admin initial-password -n argocd

# Port-forward (or configure Ingress)
kubectl port-forward svc/argocd-server -n argocd 8443:443
# Open https://localhost:8443
```

### 3. Register the Archon repository

```bash
argocd login localhost:8443 --insecure

argocd repo add https://github.com/archon-ai/archon.git \
  --username <git-user> \
  --password <git-token>
```

### 4. Apply the Archon Application

```bash
kubectl apply -f infra/argocd/application.yaml
```

This creates:

- **AppProject** `archon` — scoped to the `archon` and `archon-monitoring` namespaces
- **Application** `archon` — deploys the Helm chart from `infra/helm/archon/`
- **Application** `archon-monitoring` — deploys kube-prometheus-stack into `archon-monitoring`

### 5. Environment-specific overrides

Create per-environment values files and reference them in the ArgoCD Application:

```yaml
# infra/helm/archon/values-production.yaml
backend:
  replicaCount: 4
  autoscaling:
    minReplicas: 4
    maxReplicas: 20
config:
  logLevel: WARN
  debug: "false"
  corsOrigins: "https://archon.example.com"
```

Update the ArgoCD Application source:

```yaml
spec:
  source:
    helm:
      valueFiles:
        - values.yaml
        - values-production.yaml
```

### Sync and rollback

```bash
# Manual sync
argocd app sync archon

# Rollback to a previous revision
argocd app rollback archon <REVISION_NUMBER>

# View sync status
argocd app get archon
```

---

## Monitoring Setup

### Prometheus + Grafana

The monitoring stack is defined in `infra/monitoring/prometheus-values.yaml` and can be deployed standalone or via the ArgoCD monitoring Application.

#### Standalone installation

```bash
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo update

helm install archon-monitoring \
  prometheus-community/kube-prometheus-stack \
  --namespace archon-monitoring --create-namespace \
  -f infra/monitoring/prometheus-values.yaml \
  --set grafana.adminPassword='CHANGE_ME' \
  --wait --timeout 10m
```

#### What you get

| Component | Purpose |
|-----------|---------|
| Prometheus | Metrics collection with 15-day retention |
| Grafana | Dashboards with auto-loaded Archon panels |
| Alertmanager | Alert routing (Slack, PagerDuty, email) |
| kube-state-metrics | Kubernetes object metrics |
| node-exporter | Host-level metrics |

#### Pre-configured alerts

The values file includes Archon-specific PrometheusRules:

| Alert | Condition | Severity |
|-------|-----------|----------|
| `ArchonBackendDown` | Backend pod unreachable for 2 min | critical |
| `ArchonHighErrorRate` | 5xx rate > 5% for 5 min | warning |
| `ArchonHighLatency` | p95 > 200ms for 5 min | warning |
| `ArchonPodRestarting` | > 3 restarts in 1 hour | warning |
| `ArchonHighMemoryUsage` | Container memory > 85% of limit | warning |
| `ArchonHighCPUUsage` | Container CPU > 85% of limit | warning |
| `ArchonPVCAlmostFull` | PVC usage > 85% | warning |

#### Accessing Grafana

```bash
kubectl port-forward svc/archon-monitoring-grafana \
  -n archon-monitoring 3000:80

# Open http://localhost:3000 (admin / <your-password>)
```

#### Adding custom dashboards

Create a ConfigMap with the `grafana_dashboard` label and the sidecar auto-imports it:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: archon-custom-dashboard
  namespace: archon-monitoring
  labels:
    grafana_dashboard: "1"
data:
  archon-overview.json: |
    { ... Grafana dashboard JSON ... }
```

---

## Air-Gap / Offline Installation

For environments with no internet access.

### 1. Bundle generation (run on a connected machine)

```bash
# Pull and save all required container images
IMAGES=(
  "archon/backend:0.1.0"
  "archon/frontend:0.1.0"
  "quay.io/prometheus/prometheus:v2.53.0"
  "grafana/grafana:11.1.0"
  "quay.io/prometheus/alertmanager:v0.27.0"
  "registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.12.0"
  "quay.io/prometheus/node-exporter:v1.8.1"
)

mkdir -p archon-airgap-bundle/images
for img in "${IMAGES[@]}"; do
  filename=$(echo "$img" | tr '/:' '__').tar
  docker pull "$img"
  docker save "$img" -o "archon-airgap-bundle/images/$filename"
done

# Package the Helm chart
helm package infra/helm/archon -d archon-airgap-bundle/

# Copy monitoring values
cp infra/monitoring/prometheus-values.yaml archon-airgap-bundle/

# Copy this guide
cp infra/docs/deployment-guide.md archon-airgap-bundle/

# Create the tarball
tar czf archon-airgap-bundle.tar.gz archon-airgap-bundle/
```

### 2. Transfer

Copy `archon-airgap-bundle.tar.gz` to the air-gapped environment via USB drive, SFTP to a bastion, or approved transfer mechanism.

### 3. Load images into a local registry

```bash
tar xzf archon-airgap-bundle.tar.gz
cd archon-airgap-bundle

# Start a local registry if you don't have one
docker run -d -p 5000:5000 --name registry registry:2

# Load and push each image
for tarfile in images/*.tar; do
  docker load -i "$tarfile"
done

# Re-tag and push to your local registry
for img in "${IMAGES[@]}"; do
  local_tag="registry.internal:5000/$img"
  docker tag "$img" "$local_tag"
  docker push "$local_tag"
done
```

### 4. Install with local registry override

```bash
helm install archon ./archon-0.1.0.tgz \
  --namespace archon --create-namespace \
  --set global.imageRegistry=registry.internal:5000 \
  --set postgresql.host=YOUR_PG_HOST \
  --set redis.host=YOUR_REDIS_HOST \
  --wait --timeout 10m
```

### 5. Validate no outbound calls

```bash
# Deploy a network policy that blocks all egress and verify pods still run
kubectl apply -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-external-egress
  namespace: archon
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8
        - ipBlock:
            cidr: 172.16.0.0/12
        - ipBlock:
            cidr: 192.168.0.0/16
EOF

# All pods should remain healthy
kubectl get pods -n archon -w
```

---

## Configuration Reference

### Key Helm values

| Value | Default | Description |
|-------|---------|-------------|
| `global.imageRegistry` | `""` | Override registry for all images (air-gap) |
| `backend.replicaCount` | `2` | Backend pod replicas |
| `backend.autoscaling.enabled` | `true` | Enable HPA |
| `backend.autoscaling.maxReplicas` | `10` | HPA max replicas |
| `backend.resources.requests.cpu` | `250m` | CPU request |
| `backend.resources.requests.memory` | `512Mi` | Memory request |
| `backend.podDisruptionBudget.enabled` | `true` | Enable PDB |
| `frontend.enabled` | `true` | Deploy frontend |
| `ingress.enabled` | `false` | Enable ingress |
| `postgresql.host` | `""` | PostgreSQL hostname |
| `redis.host` | `""` | Redis hostname |
| `networkPolicy.enabled` | `false` | Enable network policies |
| `config.logLevel` | `INFO` | Application log level |

### Environment variables

All Archon configuration uses the `ARCHON_` prefix (via Pydantic-settings):

| Variable | Description |
|----------|-------------|
| `ARCHON_LOG_LEVEL` | Logging level (DEBUG, INFO, WARN, ERROR) |
| `ARCHON_DEBUG` | Enable debug mode |
| `ARCHON_CORS_ORIGINS` | Allowed CORS origins |
| `ARCHON_DATABASE_URL` | PostgreSQL connection string |
| `ARCHON_REDIS_URL` | Redis connection string |

---

## Upgrading

### Helm upgrade

```bash
# Review changes
helm diff upgrade archon infra/helm/archon -n archon

# Apply
helm upgrade archon infra/helm/archon \
  -n archon --wait --timeout 10m

# Verify
kubectl rollout status deployment/archon-backend -n archon
```

### ArgoCD upgrade

Simply push changes to the Git repository. ArgoCD auto-syncs if `automated` sync is enabled. To trigger a manual sync:

```bash
argocd app sync archon
```

### Rollback

```bash
# Helm
helm rollback archon <REVISION> -n archon

# ArgoCD
argocd app rollback archon <REVISION>

# Git (preferred with GitOps)
git revert <COMMIT_SHA>
git push origin main
```

---

## Troubleshooting

### Pods not starting

```bash
# Check pod events
kubectl describe pod -l app.kubernetes.io/component=backend -n archon

# Check logs
kubectl logs -l app.kubernetes.io/component=backend -n archon --tail=100

# Common causes:
# - ImagePullBackOff: wrong image tag or missing imagePullSecrets
# - CrashLoopBackOff: database unreachable or missing env vars
# - Pending: insufficient resources or unbound PVC
```

### Database connection failures

```bash
# Verify the secret exists
kubectl get secret archon-db -n archon -o jsonpath='{.data.password}' | base64 -d

# Test connectivity from inside the cluster
kubectl run pg-test --rm -it --image=postgres:16 --restart=Never -n archon -- \
  psql "postgresql://archon:<password>@<host>:5432/archon" -c "SELECT 1"
```

### Ingress not working

```bash
# Check ingress resource
kubectl get ingress -n archon
kubectl describe ingress -n archon

# Verify the ingress class exists
kubectl get ingressclass

# Check controller logs
kubectl logs -l app.kubernetes.io/name=ingress-nginx -n ingress-nginx --tail=50
```

### Helm install failures

```bash
# Dry-run first
helm install archon infra/helm/archon -n archon --dry-run --debug

# Check for template rendering issues
helm template archon infra/helm/archon | kubectl apply --dry-run=client -f -

# If a release is stuck in a failed state
helm uninstall archon -n archon
# Then re-install
```

### ArgoCD sync failures

```bash
# Check application status
argocd app get archon

# View sync details
argocd app sync archon --dry-run

# Force refresh from Git
argocd app get archon --refresh

# Common causes:
# - Schema validation errors (ServerSideApply usually fixes this)
# - Namespace doesn't exist (ensure CreateNamespace=true in syncOptions)
# - RBAC: ArgoCD service account needs cluster-admin or scoped permissions
```

### Monitoring not scraping Archon metrics

```bash
# Verify ServiceMonitor is picked up
kubectl get servicemonitor -n archon-monitoring

# Check Prometheus targets
kubectl port-forward svc/archon-monitoring-prometheus -n archon-monitoring 9090:9090
# Open http://localhost:9090/targets and look for archon-backend

# Ensure labels match: the Prometheus instance must have
# serviceMonitorSelectorNilUsesHelmValues: false
# (already set in our values file)
```

### Resource pressure

```bash
# Check node resources
kubectl top nodes
kubectl top pods -n archon

# Scale up manually if HPA hasn't caught up
kubectl scale deployment archon-backend -n archon --replicas=5

# Check HPA status
kubectl get hpa -n archon
kubectl describe hpa archon-backend -n archon
```

### Air-gap specific issues

```bash
# Verify all images are available in local registry
for img in archon/backend:0.1.0 archon/frontend:0.1.0; do
  docker pull registry.internal:5000/$img && echo "OK: $img" || echo "MISSING: $img"
done

# If pods have ImagePullBackOff, check:
# 1. global.imageRegistry is set correctly
# 2. Node containerd/docker trusts the local registry (insecure-registries or CA cert)
# 3. The image tags match exactly
```

### Collecting a support bundle

```bash
# Gather diagnostics
kubectl cluster-info dump --namespaces archon,archon-monitoring \
  --output-directory ./archon-support-bundle/

# Include Helm state
helm get all archon -n archon > ./archon-support-bundle/helm-release.txt

# Package
tar czf archon-support-$(date +%Y%m%d).tar.gz ./archon-support-bundle/
```

---

## Additional Resources

- **Helm chart**: `infra/helm/archon/` — see `values.yaml` for all options
- **Terraform modules**: `infra/terraform/{aws,azure,gcp}/`
- **ArgoCD manifests**: `infra/argocd/application.yaml`
- **Monitoring values**: `infra/monitoring/prometheus-values.yaml`
- **Agent-17 specification**: `agents/prompts/agent-17-deployment.md`
