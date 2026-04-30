#!/usr/bin/env bash
# scripts/run-chaos-tests.sh — run the Phase 6 chaos test suite.
#
# Exercises:
#   - worker crash recovery (lease expiration, multi-worker race)
#   - Postgres transient failures (TimeoutError, persistent failures)
#   - provider 429 storms (circuit breaker open / half_open / closed)
#   - Redis unavailability (rate limiter fail-open, dispatcher independence)
#
# Tests run hermetically against in-memory SQLite and patched module
# boundaries — no docker / postgres / redis required.
#
# Usage:
#   bash scripts/run-chaos-tests.sh           # run all chaos tests
#   bash scripts/run-chaos-tests.sh -k <expr> # filter
#   bash scripts/run-chaos-tests.sh -x        # stop on first failure
#
# Exits with the pytest exit code so CI can gate on it directly.

set -euo pipefail

# Resolve repo root from this script's location (symlink-safe).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

# ── Test environment ────────────────────────────────────────────────
export LLM_STUB_MODE=true
export ARCHON_ENV=test
export PYTHONPATH=backend
export AUTH_DEV_MODE=true
export ARCHON_AUTH_DEV_MODE=true
export ARCHON_RATE_LIMIT_ENABLED=false
export ARCHON_VAULT_ADDR="${ARCHON_VAULT_ADDR:-http://localhost:8200}"
export ARCHON_VAULT_TOKEN="${ARCHON_VAULT_TOKEN:-test-token}"
# NOTE: do NOT override ARCHON_DATABASE_URL.  Chaos tests build their
# own per-test SQLite engine in tests/test_chaos/conftest.py; the
# module-level ``app.database.engine`` uses Postgres-only kwargs
# (pool_size, max_overflow) and is constructed lazily — it never
# connects unless a test explicitly uses it, which the chaos suite
# does not.

echo "▶ Phase 6 chaos test suite"
echo "  PYTHONPATH=$PYTHONPATH"
echo "  LLM_STUB_MODE=$LLM_STUB_MODE"
echo "  ARCHON_DATABASE_URL=${ARCHON_DATABASE_URL:-<default postgres url, lazy>}"
echo

python3 -m pytest backend/tests/test_chaos/ -v --no-header --tb=short "$@"
