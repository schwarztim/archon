#!/usr/bin/env bash
# scripts/test-metrics-real.sh — P3 live observability proof.
#
# Runs the real-workflow metrics emission test:
#   * boots a sqlite-backed FastAPI TestClient,
#   * drives a workflow inline via POST /api/v1/executions,
#   * scrapes GET /metrics,
#   * asserts the canonical archon_* metric names + counters incremented.
#
# Usage:
#   bash scripts/test-metrics-real.sh
#
# Exits with the pytest exit code so CI can gate on it directly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

export LLM_STUB_MODE=true
export ARCHON_ENV=test
export ARCHON_AUTH_DEV_MODE=true
export ARCHON_RATE_LIMIT_ENABLED=false
export ARCHON_DATABASE_URL="${ARCHON_DATABASE_URL:-postgresql+asyncpg://t:t@localhost/t}"
export ARCHON_VAULT_ADDR="${ARCHON_VAULT_ADDR:-http://localhost:8200}"
export ARCHON_VAULT_TOKEN="${ARCHON_VAULT_TOKEN:-test-token}"
export ARCHON_DISPATCH_INLINE=1
export PYTHONPATH=backend

exec python3 -m pytest backend/tests/test_metrics_real_emission.py -v --tb=short "$@"
