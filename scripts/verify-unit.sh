#!/usr/bin/env bash
# scripts/verify-unit.sh — Gate 1: unit tests (no live infra required).
#
# Runs:
#   - backend/tests/ (excluding known-failures.txt entries that require live infra)
#   - gateway/tests/ (excluding test_guardrails.py which has known infra coupling)
#   - python -m pytest -m unit (any test explicitly marked as unit; no-op if none)
#
# Environment:
#   LLM_STUB_MODE=true  — stub LLM calls (no live API)
#
# Exit code: 1 on any test failure. No `|| true` masking.
# Usage: bash scripts/verify-unit.sh

set -uo pipefail
cd "$(dirname "$0")/.."

export LLM_STUB_MODE=true
export PYTHONPATH=backend

KNOWN_FAILURES_FILE="scripts/known-failures.txt"

# Build --ignore flags from known-failures.txt.
# Each non-comment, non-blank line: first token is the test path (relative to repo root).
build_ignore_flags() {
  local file="$1"
  local prefix="$2"  # only include entries that start with this path prefix
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

BACKEND_IGNORES=$(build_ignore_flags "$KNOWN_FAILURES_FILE" "backend/tests")
echo "▶ Backend unit tests (ignores: ${BACKEND_IGNORES:-none})"
# shellcheck disable=SC2086
python3 -m pytest backend/tests/ -q -p no:warnings $BACKEND_IGNORES
RC_BACKEND=$?

echo "▶ Gateway tests"
(
  cd gateway && python3 -m pytest tests/ -q -p no:warnings \
    --ignore=tests/test_guardrails.py
)
RC_GATEWAY=$?

echo "▶ Tests marked @pytest.mark.unit"
# Run -m unit per-tree to avoid conftest path collisions across roots.
# pytest exit code 5 = "no tests collected" — treat as success (the marker
# is optional; this is a forward-compatibility hook for when tests adopt it).
RC_MARKED=0
for tree in backend tests gateway; do
  if [ ! -d "$tree" ]; then continue; fi
  python3 -m pytest -m unit -q -p no:warnings "$tree/" --rootdir="$tree" 2>/dev/null
  rc=$?
  if [ "$rc" = "5" ] || [ "$rc" = "0" ]; then
    continue
  fi
  echo "  ↳ $tree: rc=$rc"
  RC_MARKED=$rc
done
if [ "$RC_MARKED" = "0" ]; then
  echo "  (no tests marked @pytest.mark.unit yet — forward-compatible)"
fi

if [ "$RC_BACKEND" != "0" ] || [ "$RC_GATEWAY" != "0" ] || [ "$RC_MARKED" != "0" ]; then
  echo "✗ verify-unit FAILED (backend=$RC_BACKEND gateway=$RC_GATEWAY marked=$RC_MARKED)"
  exit 1
fi

echo "✓ verify-unit passed"
