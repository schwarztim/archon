#!/usr/bin/env bash
# scripts/verify-integration.sh — Gate 2: integration tests.
#
# Runs tests/integration/ except the vertical slice (which is verify-slice's gate).
# Honors known-failures.txt exclusions for tests that require live external creds.
#
# In CI, postgres + redis service containers are expected to be running on
# localhost:5432 / localhost:6379 (per ci.yml services block). Locally, run
# `make dev` first to start postgres + redis, or rely on test fixtures that
# fall back to in-process SQLite.
#
# Environment:
#   LLM_STUB_MODE=true  — stub LLM calls (no live API)
#
# Exit code: 1 on any test failure.
# Usage: bash scripts/verify-integration.sh

set -uo pipefail
cd "$(dirname "$0")/.."

export LLM_STUB_MODE=true
export PYTHONPATH=backend

KNOWN_FAILURES_FILE="scripts/known-failures.txt"

build_ignore_flags() {
  local file="$1"
  local prefix="$2"
  local flags=""
  if [ ! -f "$file" ]; then
    return 0
  fi
  while IFS= read -r line; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    local path
    path=$(echo "$line" | awk '{print $1}')
    case "$path" in
      "${prefix}"*)
        flags="$flags --ignore=$path"
        ;;
    esac
  done < "$file"
  echo "$flags"
}

INTEGRATION_IGNORES=$(build_ignore_flags "$KNOWN_FAILURES_FILE" "tests/integration")
# verify-slice owns this file — exclude from the integration gate.
INTEGRATION_IGNORES="$INTEGRATION_IGNORES --ignore=tests/integration/test_vertical_slice.py"

echo "▶ Integration tests (ignores: ${INTEGRATION_IGNORES})"
# shellcheck disable=SC2086
python3 -m pytest tests/integration/ -q -p no:warnings $INTEGRATION_IGNORES
RC=$?

if [ "$RC" != "0" ]; then
  echo "✗ verify-integration FAILED (rc=$RC)"
  exit 1
fi

echo "✓ verify-integration passed"
