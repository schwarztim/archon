#!/usr/bin/env bash
# scripts/test-worker-canary.sh — non-inline worker dispatch proof.
#
# Plan a6a915dc, P0:
#   The vertical slice canary (test-slice.sh) runs with
#   ARCHON_DISPATCH_INLINE=1 because the in-process FastAPI TestClient cannot
#   await a tracked background task. That proves the dispatcher path. This
#   wrapper proves the production fire-and-forget path that the worker drain
#   loop drives — REST POST creates a queued WorkflowRun; the dispatcher
#   (called via the same entry point worker._drain_loop uses) drains it to
#   completion. Step rows + lifecycle events are persisted.
#
# Default mode: ARCHON_DISPATCH_INLINE=0 (override at your own risk; the test
# explicitly pins this via a fixture so the env value is mostly informational).
#
# Exit code: pytest's exit code (0 on green).
# Usage: bash scripts/test-worker-canary.sh

set -euo pipefail

# Resolve repo root (symlink-safe).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

# ── Test environment ────────────────────────────────────────────────
export LLM_STUB_MODE=true
export ARCHON_ENV=test
export ARCHON_AUTH_DEV_MODE=true
export ARCHON_RATE_LIMIT_ENABLED=false
export ARCHON_VAULT_ADDR="${ARCHON_VAULT_ADDR:-http://localhost:8200}"
export ARCHON_VAULT_TOKEN="${ARCHON_VAULT_TOKEN:-test-token}"
export ARCHON_DATABASE_URL="${ARCHON_DATABASE_URL:-sqlite+aiosqlite:///}"
# Default to fire-and-forget — the test fixture pins this, but exporting it
# keeps anyone reading the script honest about the contract under test.
export ARCHON_DISPATCH_INLINE="${ARCHON_DISPATCH_INLINE:-0}"
export PYTHONPATH=backend

echo "▶ Worker canary (ARCHON_DISPATCH_INLINE=${ARCHON_DISPATCH_INLINE})"
echo "  PYTHONPATH=$PYTHONPATH"
echo "  ARCHON_DATABASE_URL=$ARCHON_DATABASE_URL"
echo

exec python3 -m pytest tests/integration/test_worker_canary.py -v --tb=short
