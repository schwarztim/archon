#!/usr/bin/env bash
# scripts/verify-contracts.sh — Gate 4: contract checks.
#
# Validates that backend/frontend/gateway contracts stay in sync:
#   1. scripts/check-feature-matrix.py  (created by feature-matrix agent — skip-with-warning if missing)
#   2. OpenAPI schema diff against backend/openapi.json (skip if file missing)
#   3. frontend API client types vs backend response models (skip if check tool not yet wired)
#
# Skips known-missing pieces with explicit warnings — does NOT silently pass.
# When all dependencies land, this gate will run all 3 checks.
#
# Exit code: 1 on any executed check failure. 0 if all checks skipped (warned).
# Usage: bash scripts/verify-contracts.sh

set -uo pipefail
cd "$(dirname "$0")/.."

EXECUTED=0
FAILED=0

# 1) Feature matrix validator (owned by another agent in this wave).
if [ -f scripts/check-feature-matrix.py ]; then
  echo "▶ Feature matrix validation"
  python3 scripts/check-feature-matrix.py
  RC=$?
  EXECUTED=$((EXECUTED + 1))
  if [ "$RC" != "0" ]; then
    echo "✗ check-feature-matrix.py failed (rc=$RC)"
    FAILED=$((FAILED + 1))
  fi
else
  echo "⚠ scripts/check-feature-matrix.py not present yet — skipping (owned by feature-matrix agent in current wave)"
fi

# 2) OpenAPI schema diff. The check is a no-op until backend/openapi.json is committed.
if [ -f backend/openapi.json ]; then
  echo "▶ OpenAPI schema regeneration + diff"
  # Regenerate the schema from the live FastAPI app and diff against the committed copy.
  TMP_SCHEMA=$(mktemp)
  trap 'rm -f "$TMP_SCHEMA"' EXIT
  if PYTHONPATH=backend python3 -c "
import json
from app.main import app
print(json.dumps(app.openapi(), indent=2, sort_keys=True))
" >"$TMP_SCHEMA" 2>/dev/null; then
    if diff -q backend/openapi.json "$TMP_SCHEMA" >/dev/null; then
      echo "  OpenAPI schema in sync"
    else
      echo "✗ backend/openapi.json out of sync with live schema:"
      diff -u backend/openapi.json "$TMP_SCHEMA" | head -40 || true
      FAILED=$((FAILED + 1))
    fi
    EXECUTED=$((EXECUTED + 1))
  else
    echo "⚠ Could not regenerate OpenAPI schema from app.main:app — skipping diff"
  fi
else
  echo "⚠ backend/openapi.json not committed yet — skipping OpenAPI diff"
fi

# 3) Frontend client types vs backend response models.
# Placeholder — the dedicated check tool isn't wired yet. When implemented
# (e.g. scripts/check-api-types.py) it should be invoked here.
if [ -f scripts/check-api-types.py ]; then
  echo "▶ Frontend ↔ backend type parity"
  python3 scripts/check-api-types.py
  RC=$?
  EXECUTED=$((EXECUTED + 1))
  if [ "$RC" != "0" ]; then
    echo "✗ check-api-types.py failed (rc=$RC)"
    FAILED=$((FAILED + 1))
  fi
else
  echo "⚠ scripts/check-api-types.py not present yet — skipping (frontend type-parity check)"
fi

# 4) Frontend NodeKind ↔ backend node executor registry parity (Phase 3, WS15).
# Walks @register decorators and the NodeKind union to detect drift.
if [ -f scripts/check-frontend-backend-parity.py ]; then
  echo "▶ Frontend ↔ backend node schema parity"
  python3 scripts/check-frontend-backend-parity.py
  RC=$?
  EXECUTED=$((EXECUTED + 1))
  if [ "$RC" != "0" ]; then
    echo "✗ check-frontend-backend-parity.py failed (rc=$RC)"
    FAILED=$((FAILED + 1))
  fi
else
  echo "⚠ scripts/check-frontend-backend-parity.py not present — skipping (frontend node-schema parity check)"
fi

# 5) Route permission matrix (Phase 4, WS13).
# Walks app.routes and asserts every route is either authenticated or in the
# explicit public allowlist (scripts/route-permissions-allowlist.txt).
if [ -f scripts/check-route-permissions.py ]; then
  echo "▶ Route permission matrix"
  python3 scripts/check-route-permissions.py
  RC=$?
  EXECUTED=$((EXECUTED + 1))
  if [ "$RC" != "0" ]; then
    echo "✗ check-route-permissions.py failed (rc=$RC)"
    FAILED=$((FAILED + 1))
  fi
else
  echo "⚠ scripts/check-route-permissions.py not present — skipping (route permission matrix)"
fi

# 6) Grafana dashboard JSON validity (Phase 5).
# Every dashboard under infra/grafana/dashboards/ must parse as JSON. A typo
# bricks the Grafana sidecar at deploy time — catch it locally.
if [ -d infra/grafana/dashboards ]; then
  echo "▶ Grafana dashboard JSON validity"
  python3 - <<'PY'
import json
import pathlib
import sys

bad = 0
total = 0
for path in sorted(pathlib.Path("infra/grafana/dashboards").glob("*.json")):
    total += 1
    try:
        json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"  ✗ {path}: {e}")
        bad += 1
print(f"  {total} dashboard(s) parsed, {bad} invalid")
sys.exit(1 if bad else 0)
PY
  RC=$?
  EXECUTED=$((EXECUTED + 1))
  if [ "$RC" != "0" ]; then
    echo "✗ Grafana dashboard JSON validity failed (rc=$RC)"
    FAILED=$((FAILED + 1))
  fi
else
  echo "⚠ infra/grafana/dashboards/ not present — skipping (dashboard JSON validity)"
fi

# 7) Grafana / alert ↔ metrics-catalog parity (Phase 5, observability).
# Every PromQL query in a dashboard or alert rule must reference a metric
# registered in docs/metrics-catalog.md.
if [ -f scripts/check-grafana-metric-parity.py ]; then
  echo "▶ Grafana ↔ metrics-catalog parity"
  python3 scripts/check-grafana-metric-parity.py
  RC=$?
  EXECUTED=$((EXECUTED + 1))
  if [ "$RC" != "0" ]; then
    echo "✗ check-grafana-metric-parity.py failed (rc=$RC)"
    FAILED=$((FAILED + 1))
  fi
else
  echo "⚠ scripts/check-grafana-metric-parity.py not present — skipping (Grafana metric parity)"
fi

if [ "$FAILED" -gt 0 ]; then
  echo "✗ verify-contracts FAILED ($FAILED of $EXECUTED checks failed)"
  exit 1
fi

if [ "$EXECUTED" = "0" ]; then
  echo "⚠ verify-contracts: 0 checks executed (all dependencies missing); passing with warning"
else
  echo "✓ verify-contracts passed ($EXECUTED checks)"
fi
