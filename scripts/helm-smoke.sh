#!/usr/bin/env bash
# scripts/helm-smoke.sh — render Helm chart + optional kind/minikube smoke.
#
# Proves three things:
#   1. The chart lints clean (defaults + production overlay)
#   2. The chart renders to a non-empty manifest set (defaults + production overlay)
#   3. The rendered YAML is parseable
#   4. (optional) kubectl can dry-run apply the manifests (when kubectl + kind present)
#
# Local fail-soft: if helm CLI is absent, exits 0 with advisory message
# (CI is the gating environment — see .github/workflows/helm-smoke.yml).
#
# Exit codes:
#   0 — pass (or helm CLI absent locally)
#   1 — lint, render, or parse failure
#   2 — rendered output empty (chart produced no manifests)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

CHART="infra/helm/archon"
DEV_RENDER="/tmp/archon-dev-render.yaml"
PROD_RENDER="/tmp/archon-prod-render.yaml"

if ! command -v helm >/dev/null 2>&1; then
  echo "x helm CLI not installed — skipping local smoke (CI installs helm)"
  exit 0
fi

echo "> helm lint (defaults)"
helm lint "$CHART"

echo "> helm lint (production overlay)"
helm lint "$CHART" -f "$CHART/values-production.yaml"

echo "> helm template (defaults)"
helm template archon-test "$CHART" > "$DEV_RENDER"
if [ ! -s "$DEV_RENDER" ]; then
  echo "x rendered defaults manifest is empty: $DEV_RENDER" >&2
  exit 2
fi

echo "> helm template (production overlay)"
helm template archon-test "$CHART" -f "$CHART/values-production.yaml" > "$PROD_RENDER"
if [ ! -s "$PROD_RENDER" ]; then
  echo "x rendered production manifest is empty: $PROD_RENDER" >&2
  exit 2
fi

# Validate rendered YAML parses — surfaces template bugs that produce
# broken multi-doc YAML.
echo "> Validating YAML parses"
python3 - <<'PYEOF'
import sys
import yaml

for path in ("/tmp/archon-dev-render.yaml", "/tmp/archon-prod-render.yaml"):
    with open(path) as f:
        try:
            docs = list(yaml.safe_load_all(f))
        except yaml.YAMLError as e:
            print(f"x YAML parse failed for {path}: {e}", file=sys.stderr)
            sys.exit(1)
    nondoc = [d for d in docs if d is not None]
    print(f"  {path}: {len(nondoc)} manifest(s)")
    if not nondoc:
        print(f"x {path}: rendered to no manifests after parse", file=sys.stderr)
        sys.exit(1)

print("+ YAML valid")
PYEOF

if command -v kubectl >/dev/null 2>&1; then
  echo "> kubectl dry-run apply (production manifests)"
  # Client-side dry-run: validate against built-in schemas without a cluster.
  if kubectl apply --dry-run=client -f "$PROD_RENDER" >/dev/null 2>&1; then
    echo "  + manifests apply cleanly (dry-run=client)"
  else
    # Surface stderr for diagnosis, but only fail when kubectl is genuinely
    # unhappy with the manifest content — not because of missing CRDs.
    kubectl apply --dry-run=client -f "$PROD_RENDER" || {
      echo "x kubectl dry-run apply failed — see stderr above" >&2
      exit 1
    }
  fi
else
  echo "  (kubectl not installed — skipping dry-run apply)"
fi

if command -v kind >/dev/null 2>&1; then
  echo "  (kind installed — kind cluster smoke available; skipping cluster create in default smoke)"
fi

echo "+ helm-smoke passed"
