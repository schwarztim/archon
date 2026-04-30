#!/usr/bin/env bash
# scripts/verify-slice.sh — Gate B: vertical-slice end-to-end heartbeat.
#
# Wraps scripts/test-slice.sh and asserts the heartbeat passes the REST path.
# REST-driven mode is enforced unconditionally — there is no transition mode
# and no brittle TestClient/httpx grep. The slice test itself is the gate.
#
# ARCHON_DISPATCH_INLINE=1 is exported so the canary awaits dispatch_run
# inline (same path the production worker uses), allowing the slice to
# observe the durable WorkflowRun in <5s.
#
# Exit code: 0 on success, 1 on slice failure.
# Usage: bash scripts/verify-slice.sh

set -uo pipefail
cd "$(dirname "$0")/.."

export ARCHON_DISPATCH_INLINE=1

bash scripts/test-slice.sh
rc=$?
if [ "$rc" != 0 ]; then
  echo "✗ verify-slice FAILED (rc=$rc)"
  exit 1
fi
echo "✓ verify-slice passed"
