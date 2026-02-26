#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Archon Platform — API Smoke Test
#
# Verifies all major endpoints exist and return correct HTTP status
# codes using the FastAPI TestClient (no running server required).
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/backend"

echo "═══════════════════════════════════════════════════════════"
echo "  Archon Platform — API Smoke Test"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Run all checks in Python to avoid subshell counter issues
python3 -c "
import sys
sys.path.insert(0, 'backend')

from fastapi.testclient import TestClient
from app.main import create_app

app = create_app()
client = TestClient(app, raise_server_exceptions=False)

endpoints = [
    # Health (unauthenticated)
    ('GET', '/health', 200),
    ('GET', '/ready', 200),
    ('GET', '/api/v1/health', 200),

    # Core API endpoints — verify they exist (not 404)
    ('GET', '/api/v1/agents/', 'exists'),
    ('GET', '/api/v1/templates/', 'exists'),
    ('GET', '/api/v1/connectors/', 'exists'),
    ('GET', '/api/v1/audit-logs/', 'exists'),
    ('GET', '/api/v1/cost/alerts', 'exists'),
    ('GET', '/api/v1/lifecycle/deployments', 'exists'),
    ('GET', '/api/v1/router/providers', 'exists'),
    ('GET', '/api/v1/governance/policies', 'exists'),
    ('GET', '/api/v1/marketplace/listings', 'exists'),

    # DLP (double-prefixed in actual app)
    ('GET', '/api/v1/dlp/policies', 'exists'),

    # Settings, Admin
    ('GET', '/api/v1/settings', 'exists'),
    ('GET', '/api/v1/admin/users', 'exists'),
]

passed = 0
failed = 0
total = len(endpoints)

for method, path, expected in endpoints:
    try:
        resp = client.get(path)
        actual = resp.status_code

        if expected == 'exists':
            # Any non-404 response means the endpoint is registered
            if actual != 404:
                print(f'  ✅ {path} (HTTP {actual} — endpoint exists)')
                passed += 1
            else:
                print(f'  ❌ {path} (HTTP 404 — endpoint not found)')
                failed += 1
        elif actual == expected:
            print(f'  ✅ {path} (HTTP {actual})')
            passed += 1
        else:
            print(f'  ❌ {path} (expected {expected}, got {actual})')
            failed += 1
    except Exception as e:
        print(f'  ❌ {path} (error: {e})')
        failed += 1

print()
print('─────────────────────────────────────────────────────────────')
print(f'  Results: {passed}/{total} passed, {failed} failed')
print('─────────────────────────────────────────────────────────────')

if failed > 0:
    print('  ⚠️  Some smoke tests failed')
    sys.exit(1)
else:
    print('  ✅ All smoke tests passed')
    sys.exit(0)
"
