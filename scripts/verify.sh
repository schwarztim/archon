#!/usr/bin/env bash
# scripts/verify.sh — top-level verification: runs all 5 named gates in order.
#
# Gates:
#   1. verify-unit         — backend + gateway unit tests (no live infra)
#   2. verify-integration  — tests/integration/ (excluding slice)
#   3. verify-frontend     — typecheck + Vitest
#   4. verify-contracts    — feature matrix + OpenAPI diff + API type parity
#   5. verify-slice        — vertical slice REST heartbeat
#
# Each gate is a standalone script under scripts/verify-*.sh — the same
# scripts CI runs. No drift between local and CI.
#
# Exit code: 1 on first failing gate (fail-fast). Each gate's pass/fail is
# echoed before the next runs.
# Usage: bash scripts/verify.sh

set -uo pipefail
cd "$(dirname "$0")/.."

GATES=(
  "verify-unit"
  "verify-integration"
  "verify-frontend"
  "verify-contracts"
  "verify-slice"
)

FAILED_GATE=""
for gate in "${GATES[@]}"; do
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "  Gate: $gate"
  echo "════════════════════════════════════════════════════════════"
  if bash "scripts/${gate}.sh"; then
    echo "──→ $gate: PASS"
  else
    echo "──→ $gate: FAIL"
    FAILED_GATE="$gate"
    break
  fi
done

echo ""
echo "════════════════════════════════════════════════════════════"
if [ -n "$FAILED_GATE" ]; then
  echo "✗ verify FAILED at gate: $FAILED_GATE"
  exit 1
fi
echo "✓ verify passed (all 5 gates)"
