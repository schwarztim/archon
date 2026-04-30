#!/usr/bin/env bash
# scripts/run-load-tests.sh — Phase 6 load profile suite.
#
# Drives all 5 load profiles in backend/tests/test_load/ with the stub
# LLM and an in-memory SQLite engine. Designed for local iteration AND
# CI gating (CI defaults to N=10, local defaults to N=50).
#
# Usage:
#   bash scripts/run-load-tests.sh                  # full local run (N=50)
#   bash scripts/run-load-tests.sh --ci             # CI mode (N=10)
#   LOAD_TEST_N=100 bash scripts/run-load-tests.sh  # custom N
#   bash scripts/run-load-tests.sh -k profile_name  # subset selection
#
# Environment variables:
#   LOAD_TEST_N         How many parallel workflows per profile.
#                       Default: 50 (local), 10 (CI).
#   LLM_STUB_MODE       Forced to "true" — load profiles must never
#                       hit a real LLM provider.
#   PYTEST_TIMEOUT      Per-test wall-clock timeout in seconds.
#                       Default: 180 (3 min).
#
# Exits with the pytest exit code so CI can gate on it directly.

set -euo pipefail

# Resolve repo root from this script's location (symlink-safe).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

# ── Flags ───────────────────────────────────────────────────────────
CI_MODE=0
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --ci)
      CI_MODE=1
      ;;
    -h|--help)
      sed -n '2,22p' "$0"
      exit 0
      ;;
    *)
      EXTRA_ARGS+=("$arg")
      ;;
  esac
done

# ── Defaults: CI vs local ───────────────────────────────────────────
if [[ "$CI_MODE" -eq 1 ]]; then
  : "${LOAD_TEST_N:=10}"
  : "${PYTEST_TIMEOUT:=120}"
else
  : "${LOAD_TEST_N:=50}"
  : "${PYTEST_TIMEOUT:=180}"
fi
export LOAD_TEST_N

# ── Test environment ────────────────────────────────────────────────
export LLM_STUB_MODE=true
export ARCHON_ENV=test
export PYTHONPATH=backend
# Disable LangGraph postgres checkpointer in tests — sqlite DSN is not
# parseable by psycopg, and the checkpointer will retry indefinitely.
export LANGGRAPH_CHECKPOINTING=disabled

echo "▶ Phase 6 load profile suite"
echo "  PYTHONPATH=$PYTHONPATH"
echo "  LLM_STUB_MODE=$LLM_STUB_MODE"
echo "  LOAD_TEST_N=$LOAD_TEST_N"
echo "  PYTEST_TIMEOUT=${PYTEST_TIMEOUT}s"
echo "  Mode: $([[ $CI_MODE -eq 1 ]] && echo CI || echo local)"
echo

# ── Run ─────────────────────────────────────────────────────────────
# pytest-timeout is preferred when available — it produces a clear
# per-test failure rather than a hung process. Fall back to the test's
# internal time.monotonic() budget if the plugin isn't installed.
TIMEOUT_FLAG=()
if python3 -c "import pytest_timeout" >/dev/null 2>&1; then
  TIMEOUT_FLAG=(--timeout="${PYTEST_TIMEOUT}")
fi

set +e
python3 -m pytest \
  backend/tests/test_load/ \
  -v \
  --tb=short \
  -p no:cacheprovider \
  "${TIMEOUT_FLAG[@]}" \
  "${EXTRA_ARGS[@]}"
PYTEST_EXIT=$?
set -e

echo
if [[ $PYTEST_EXIT -eq 0 ]]; then
  echo "✓ Phase 6 load profiles passed (N=$LOAD_TEST_N)"
else
  echo "✗ Phase 6 load profiles failed (N=$LOAD_TEST_N) — exit $PYTEST_EXIT"
fi

exit $PYTEST_EXIT
