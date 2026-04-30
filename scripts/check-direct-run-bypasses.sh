#!/usr/bin/env bash
# scripts/check-direct-run-bypasses.sh — CI hard gate for the canonical run path.
#
# The Archon durable orchestration plan mandates that production code may NOT
# create `WorkflowRun` records outside of `ExecutionFacade`. Schedules,
# webhooks, event triggers, UI test runs, sub-workflows, and CLI starts must
# all funnel through the facade so every run gets queued tasks, hash-chained
# events, RBAC/policy/DLP/cost gates, and proper lifecycle ownership.
#
# This gate scans `backend/app/` for `WorkflowRun(` constructor calls and
# fails when any are found outside the approved write sites. Tests/factories
# live in `backend/tests/` (not `backend/app/`) so they are out of scope by
# construction. Alembic migrations under `backend/alembic/versions/` are also
# out of scope for the same reason.
#
# Approved write sites inside backend/app/:
#   - backend/app/services/execution_facade.py  (the canonical facade)
#   - backend/app/models/workflow.py             (the class definition itself)
#
# Any other hit is a bypass and must be remediated by routing through
# `ExecutionFacade.start_run(...)` (or whichever facade entrypoint applies).
#
# Usage:
#   bash scripts/check-direct-run-bypasses.sh
#
# Exit codes:
#   0 — no direct WorkflowRun construction outside ExecutionFacade
#   1 — one or more bypasses found (printed as `BYPASS: <file>:<line>: <text>`)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

SCAN_DIR="backend/app"

if [ ! -d "$SCAN_DIR" ]; then
  echo "ERROR: scan directory not found: $SCAN_DIR" >&2
  exit 2
fi

# Collect candidate hits. We scan only constructor calls (`WorkflowRun(`) and
# explicitly skip:
#   - the canonical facade
#   - the model definition file (the class itself)
#   - `WorkflowRunStep(` and `WorkflowRunEvent(` — different types
# We use grep -RInE so behavior matches across macOS/BSD and GNU grep without
# requiring ripgrep.
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

# Step 1: raw matches for `WorkflowRun(` in backend/app/.
# Step 2: drop `WorkflowRunStep(` and `WorkflowRunEvent(` (different types).
# Step 3: drop the approved write sites.
# Step 4: drop type annotation forms like `: WorkflowRun(` is unusual; the
#         construction form `... = WorkflowRun(` or `WorkflowRun(` on its own
#         line is what we want to flag. The `WorkflowRun\(` regex already
#         excludes the bare class declaration `class WorkflowRun(` because we
#         filter that file path explicitly.
grep -RInE 'WorkflowRun\(' "$SCAN_DIR" \
  | grep -vE 'WorkflowRun(Step|Event)\(' \
  | grep -vE '^backend/app/services/execution_facade\.py:' \
  | grep -vE '^backend/app/models/workflow\.py:' \
  > "$TMP" || true

if [ ! -s "$TMP" ]; then
  echo "OK: no direct WorkflowRun construction outside ExecutionFacade"
  exit 0
fi

echo "FAIL: direct WorkflowRun construction detected outside ExecutionFacade"
echo ""
while IFS= read -r line; do
  # `grep -RIn` output is `<file>:<line>:<text>` already.
  echo "BYPASS: $line"
done < "$TMP"
echo ""
echo "Remediation: route the run start through backend/app/services/execution_facade.py."
echo "Tests and Alembic migrations are exempt because they live outside backend/app/."
exit 1
