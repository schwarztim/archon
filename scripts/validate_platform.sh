#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Archon Platform — Full Validation Suite
#
# Runs all validation steps and produces a summary report:
#   1. Backend test suite (pytest)
#   2. Branding verification (no "openairia" references)
#   3. Integration / E2E tests
#   4. API smoke tests
# ─────────────────────────────────────────────────────────────────
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/backend"

OVERALL="PASS"
REPORT=""

header() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  $1"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
}

# ── Step 1: Backend Test Suite ──────────────────────────────────

header "Step 1 — Backend Test Suite"

TEST_OUTPUT=$(python3 -m pytest tests/ --no-header -q 2>&1)
TEST_EXIT=$?
echo "$TEST_OUTPUT" | tail -5

LAST_LINE=$(echo "$TEST_OUTPUT" | grep -E "passed|failed|error" | tail -1)
PASSED=$(echo "$LAST_LINE" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
FAILED=$(echo "$LAST_LINE" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")
ERRORS=$(echo "$LAST_LINE" | grep -oE '[0-9]+ error' | grep -oE '[0-9]+' || echo "0")

REPORT="$REPORT\n## Backend Tests\n- Passed: $PASSED\n- Failed: ${FAILED:-0}\n- Errors: ${ERRORS:-0}\n- Exit code: $TEST_EXIT\n"

if [ "$TEST_EXIT" -ne 0 ]; then
    OVERALL="FAIL"
    echo "  ❌ Test suite FAILED"
else
    echo "  ✅ Test suite PASSED ($PASSED tests)"
fi

# ── Step 2: Branding Verification ───────────────────────────────

header "Step 2 — Branding Verification"

BRAND_HITS=$(grep -ri "openairia" backend/ frontend/src/ \
    --include="*.py" --include="*.tsx" --include="*.ts" 2>/dev/null \
    | grep -v node_modules | grep -v __pycache__ || true)

if [ -z "$BRAND_HITS" ]; then
    echo "  ✅ No 'openairia' branding violations found"
    REPORT="$REPORT\n## Branding\n- Status: CLEAN\n- Violations: 0\n"
else
    echo "  ❌ Branding violations found:"
    echo "$BRAND_HITS"
    REPORT="$REPORT\n## Branding\n- Status: VIOLATIONS FOUND\n- Details:\n$BRAND_HITS\n"
    OVERALL="FAIL"
fi

# ── Step 3: Integration Tests ───────────────────────────────────

header "Step 3 — Integration / E2E Tests"

INTEG_OUTPUT=$(python3 -m pytest tests/integration/ --no-header -q 2>&1)
INTEG_EXIT=$?
echo "$INTEG_OUTPUT" | tail -5

INTEG_LINE=$(echo "$INTEG_OUTPUT" | grep -E "passed|failed|error" | tail -1)
INTEG_PASSED=$(echo "$INTEG_LINE" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
INTEG_FAILED=$(echo "$INTEG_LINE" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")

REPORT="$REPORT\n## Integration Tests\n- Passed: $INTEG_PASSED\n- Failed: ${INTEG_FAILED:-0}\n- Exit code: $INTEG_EXIT\n"

if [ "$INTEG_EXIT" -ne 0 ]; then
    OVERALL="FAIL"
    echo "  ❌ Integration tests FAILED"
else
    echo "  ✅ Integration tests PASSED ($INTEG_PASSED tests)"
fi

# ── Step 4: API Smoke Tests ─────────────────────────────────────

header "Step 4 — API Smoke Tests"

SMOKE_OUTPUT=$(bash "$SCRIPT_DIR/smoke_test.sh" 2>&1)
SMOKE_EXIT=$?
echo "$SMOKE_OUTPUT" | tail -10

if [ "$SMOKE_EXIT" -ne 0 ]; then
    OVERALL="FAIL"
    REPORT="$REPORT\n## Smoke Tests\n- Status: FAIL\n"
else
    REPORT="$REPORT\n## Smoke Tests\n- Status: PASS\n"
fi

# ── Summary ─────────────────────────────────────────────────────

header "Validation Summary"

echo -e "$REPORT"
echo ""
echo "─────────────────────────────────────────────────────────────"
echo "  Overall Result: $OVERALL"
echo "─────────────────────────────────────────────────────────────"

if [ "$OVERALL" = "FAIL" ]; then
    exit 1
else
    exit 0
fi
