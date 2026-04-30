#!/usr/bin/env bash
# scripts/test-slice.sh — run the REST-driven vertical-slice canary.
#
# This script is the entry point for Wave 0's heartbeat test.  The test it
# runs is intentionally STRICT — it drives the actual product REST surface
# (FastAPI TestClient) and asserts on database rows in workflow_run_steps.
# It is expected to fail (or xfail) on current main until Plan Phase 1 lands.
# A failing test here that names the gap IS the deliverable.
#
# Usage:
#   bash scripts/test-slice.sh                # run with in-memory SQLite
#   bash scripts/test-slice.sh --with-postgres # run against the postgres test
#                                             # container (docker-compose.test.yml)
#
# Exits with the pytest exit code so CI can gate on it directly.

set -euo pipefail

# Resolve repo root from this script's location (symlink-safe).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

# ── Flags ────────────────────────────────────────────────────────────
WITH_POSTGRES=0
for arg in "$@"; do
  case "$arg" in
    --with-postgres) WITH_POSTGRES=1 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: bash scripts/test-slice.sh [--with-postgres]" >&2
      exit 64
      ;;
  esac
done

# ── Test environment ────────────────────────────────────────────────
export LLM_STUB_MODE=true
export ARCHON_ENV=test
export PYTHONPATH=backend

# AUTH_DEV_MODE bypasses Keycloak; rate-limit off so concurrent polls are clean.
export ARCHON_AUTH_DEV_MODE=true
export ARCHON_RATE_LIMIT_ENABLED=false
export ARCHON_VAULT_ADDR="${ARCHON_VAULT_ADDR:-http://localhost:8200}"
export ARCHON_VAULT_TOKEN="${ARCHON_VAULT_TOKEN:-test-token}"

# Inline-dispatch contract: the REST canary asserts the durable run reaches a
# terminal state within its polling budget. With the production fire-and-forget
# pattern the in-process TestClient returns before dispatch starts. Inline mode
# awaits dispatch_run() in the request path so the canary observes the same
# dispatcher path the worker uses, with the run already finalised on response.
# Override with ARCHON_DISPATCH_INLINE=0 to opt out (e.g. soak-test the worker
# drain loop against a real backing process).
export ARCHON_DISPATCH_INLINE="${ARCHON_DISPATCH_INLINE:-1}"

# ── Database backend selection ──────────────────────────────────────
if [[ "$WITH_POSTGRES" -eq 1 ]]; then
  if [[ ! -f "docker-compose.test.yml" ]]; then
    echo "ERROR: --with-postgres requested but docker-compose.test.yml not found" >&2
    echo "Create the test compose file or run without --with-postgres." >&2
    exit 1
  fi
  echo "▶ Booting postgres test container via docker-compose.test.yml"
  docker compose -f docker-compose.test.yml up -d postgres 2>&1 | sed 's/^/  /'
  # docker-compose.test.yml is expected to expose ARCHON_DATABASE_URL via .env
  # or the compose file itself.  The test compose currently exposes pg on 5432
  # — adjust if your local override differs.
  export ARCHON_DATABASE_URL="postgresql+asyncpg://archon:archon@localhost:5432/archon_test"
  # Wait for readiness (max 30s).
  echo "▶ Waiting for postgres readiness..."
  for _ in $(seq 1 30); do
    if docker compose -f docker-compose.test.yml exec -T postgres pg_isready -U archon >/dev/null 2>&1; then
      echo "  postgres ready"
      break
    fi
    sleep 1
  done
else
  # In-memory SQLite — fastest, hermetic, what conftest.py already configures.
  export ARCHON_DATABASE_URL="${ARCHON_DATABASE_URL:-sqlite+aiosqlite:///}"
fi

echo "▶ Vertical-slice REST canary (Wave 0)"
echo "  PYTHONPATH=$PYTHONPATH"
echo "  LLM_STUB_MODE=$LLM_STUB_MODE"
echo "  ARCHON_DATABASE_URL=$ARCHON_DATABASE_URL"
echo "  AUTH_DEV_MODE=$ARCHON_AUTH_DEV_MODE"
echo

# ── Run ─────────────────────────────────────────────────────────────
set +e
python3 -m pytest tests/integration/test_vertical_slice.py -v --tb=short
PYTEST_EXIT=$?
set -e

# ── Teardown ────────────────────────────────────────────────────────
if [[ "$WITH_POSTGRES" -eq 1 ]]; then
  echo
  echo "▶ Tearing down postgres test container"
  docker compose -f docker-compose.test.yml down 2>&1 | sed 's/^/  /' || true
fi

exit $PYTEST_EXIT
