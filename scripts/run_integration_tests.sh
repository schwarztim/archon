#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# Archon Integration Test Runner
# Orchestrates Docker stack, backend pytest, and Playwright E2E tests
# ──────────────────────────────────────────────────────────────────────

set -e
set -o pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "════════════════════════════════════════════════════════════════"
echo "  Archon Integration Test Suite"
echo "════════════════════════════════════════════════════════════════"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Start minimal test stack
echo ""
echo "▶ Starting Docker test stack..."
docker compose -f docker-compose.test.yml up -d --build --wait

# Wait for backend health
echo ""
echo "▶ Waiting for backend health..."
timeout 120 bash -c 'until curl -sf http://localhost:8000/health > /dev/null 2>&1; do echo -n "."; sleep 2; done' || {
    echo "❌ Backend failed to become healthy"
    docker compose -f docker-compose.test.yml logs backend
    docker compose -f docker-compose.test.yml down -v
    exit 1
}
echo " ✓ Backend healthy"

# Wait for frontend
echo ""
echo "▶ Waiting for frontend..."
timeout 120 bash -c 'until curl -sf http://localhost:3000 > /dev/null 2>&1; do echo -n "."; sleep 2; done' || {
    echo "❌ Frontend failed to start"
    docker compose -f docker-compose.test.yml logs frontend
    docker compose -f docker-compose.test.yml down -v
    exit 1
}
echo " ✓ Frontend ready"

# Create test results directory
mkdir -p test-results

# Run backend integration tests
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Backend Integration Tests (pytest)"
echo "════════════════════════════════════════════════════════════════"
export PYTHONPATH="$PROJECT_ROOT/backend"
python3 -m pytest tests/integration/ -v --tb=short --junitxml=test-results/backend-integration.xml -m integration || {
    BACKEND_EXIT=$?
    echo "❌ Backend integration tests failed with exit code $BACKEND_EXIT"
}

# Run Playwright E2E tests
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Frontend E2E Tests (Playwright)"
echo "════════════════════════════════════════════════════════════════"
cd frontend
npx playwright test --reporter=list || {
    E2E_EXIT=$?
    echo "❌ Playwright E2E tests failed with exit code $E2E_EXIT"
}
cd ..

# Stop Docker stack
echo ""
echo "▶ Stopping Docker test stack..."
docker compose -f docker-compose.test.yml down -v

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Integration Test Suite Complete"
echo "════════════════════════════════════════════════════════════════"
echo "Results: test-results/"
echo "Backend: test-results/backend-integration.xml"
echo "E2E: frontend/playwright-report/"

exit ${BACKEND_EXIT:-0}
