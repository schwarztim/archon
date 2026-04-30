#!/usr/bin/env bash
# render-helm.sh — render the Archon Helm chart to plain Kubernetes manifests.
#
# Produces:
#   infra/k8s/manifests/dev.yaml         — chart with default values
#   infra/k8s/manifests/production.yaml  — chart with values-production.yaml overlay
#
# Useful for kubectl apply -f workflows that don't run Helm in the cluster
# (Argo CD with kustomize-only post-renderer, GitOps repos that consume raw
# manifests, etc.).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CHART_DIR="${REPO_ROOT}/infra/helm/archon"
OUT_DIR="${REPO_ROOT}/infra/k8s/manifests"

if ! command -v helm >/dev/null 2>&1; then
  echo "ERROR: helm CLI not found on PATH" >&2
  echo "       Install via: brew install helm  OR  https://helm.sh/docs/intro/install/" >&2
  exit 127
fi

mkdir -p "${OUT_DIR}"

echo "==> Rendering dev manifests"
helm template archon "${CHART_DIR}" \
  --namespace archon-dev \
  > "${OUT_DIR}/dev.yaml"

echo "==> Rendering production manifests"
helm template archon "${CHART_DIR}" \
  --namespace archon-production \
  -f "${CHART_DIR}/values-production.yaml" \
  > "${OUT_DIR}/production.yaml"

echo
echo "Rendered:"
echo "  ${OUT_DIR}/dev.yaml"
echo "  ${OUT_DIR}/production.yaml"
