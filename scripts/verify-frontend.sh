#!/usr/bin/env bash
# scripts/verify-frontend.sh — Gate 3: frontend typecheck + Vitest unit tests.
#
# Runs:
#   - npm ci --prefer-offline (in CI; skipped if node_modules already current)
#   - npm run typecheck       (tsc -b --noEmit)
#   - npm run test -- --run   (Vitest, single-pass)
#
# Does NOT require the backend to be running.
#
# Exit code: 1 on any failure.
# Usage: bash scripts/verify-frontend.sh

set -uo pipefail
cd "$(dirname "$0")/.."

if [ ! -d frontend ]; then
  echo "✗ frontend/ directory not found"
  exit 1
fi

cd frontend

if ! command -v npm >/dev/null 2>&1; then
  echo "✗ npm not installed; cannot run verify-frontend"
  exit 1
fi

# Install/refresh dependencies. In CI, ARCHON_CI=1 forces a clean `npm ci`;
# locally, fall back to a fast existence check.
if [ "${ARCHON_CI:-0}" = "1" ]; then
  echo "▶ npm ci --prefer-offline"
  npm ci --prefer-offline
else
  if [ ! -d node_modules ]; then
    echo "▶ node_modules missing — running npm ci --prefer-offline"
    npm ci --prefer-offline
  fi
fi

echo "▶ Frontend typecheck (tsc -b --noEmit)"
npm run typecheck
RC_TYPECHECK=$?

echo "▶ Frontend tests (vitest run)"
npm run test -- --run
RC_TEST=$?

if [ "$RC_TYPECHECK" != "0" ] || [ "$RC_TEST" != "0" ]; then
  echo "✗ verify-frontend FAILED (typecheck=$RC_TYPECHECK test=$RC_TEST)"
  exit 1
fi

echo "✓ verify-frontend passed"
