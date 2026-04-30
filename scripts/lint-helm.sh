#!/usr/bin/env bash
# lint-helm.sh — run `helm lint` against the Archon chart with both default
# and production value sets.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CHART_DIR="${REPO_ROOT}/infra/helm/archon"

if ! command -v helm >/dev/null 2>&1; then
  echo "ERROR: helm CLI not found on PATH" >&2
  echo "       Install via: brew install helm  OR  https://helm.sh/docs/intro/install/" >&2
  exit 127
fi

echo "==> helm lint (defaults)"
helm lint "${CHART_DIR}"

echo
echo "==> helm lint (values-production.yaml overlay)"
helm lint "${CHART_DIR}" -f "${CHART_DIR}/values-production.yaml"
