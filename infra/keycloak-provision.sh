#!/usr/bin/env bash
# Provision Keycloak realm, client, users, and roles for Archon.
# Requires: curl, python3
# Usage:  ./infra/keycloak-provision.sh [KEYCLOAK_BASE_URL]
#   e.g.  ./infra/keycloak-provision.sh http://localhost:8180/auth

set -euo pipefail

KC_BASE="${1:-http://localhost:8180/auth}"

echo "▸ Fetching admin token from ${KC_BASE}..."
KC_TOKEN=$(curl -sf -X POST "${KC_BASE}/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli" \
  -d "username=admin" \
  -d "password=admin" \
  -d "grant_type=password" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "  ✓ Token obtained (${#KC_TOKEN} chars)"

echo "▸ Creating 'archon' realm..."
curl -sf -o /dev/null -w "  HTTP %{http_code}\n" -X POST "${KC_BASE}/admin/realms" \
  -H "Authorization: Bearer ${KC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"realm":"archon","enabled":true,"registrationAllowed":false}' || true

echo "▸ Creating 'archon-app' client..."
curl -sf -o /dev/null -w "  HTTP %{http_code}\n" -X POST "${KC_BASE}/admin/realms/archon/clients" \
  -H "Authorization: Bearer ${KC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "archon-app",
    "publicClient": true,
    "directAccessGrantsEnabled": true,
    "redirectUris": ["http://localhost:3000/*"],
    "webOrigins": ["http://localhost:3000"],
    "protocol": "openid-connect",
    "standardFlowEnabled": true
  }' || true

echo "▸ Creating roles..."
for ROLE in admin operator user; do
  curl -sf -o /dev/null -w "  ${ROLE}: HTTP %{http_code}\n" -X POST "${KC_BASE}/admin/realms/archon/roles" \
    -H "Authorization: Bearer ${KC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${ROLE}\"}" || true
done

echo "▸ Creating test users..."
USER_CREDS='{"type":"password","temporary":false,"value":"admin123"}'
curl -sf -o /dev/null -w "  admin: HTTP %{http_code}\n" -X POST "${KC_BASE}/admin/realms/archon/users" \
  -H "Authorization: Bearer ${KC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"email\":\"admin@archon.local\",\"enabled\":true,\"firstName\":\"Admin\",\"lastName\":\"User\",\"credentials\":[${USER_CREDS}]}" || true

USER_CREDS='{"type":"password","temporary":false,"value":"user123"}'
curl -sf -o /dev/null -w "  testuser: HTTP %{http_code}\n" -X POST "${KC_BASE}/admin/realms/archon/users" \
  -H "Authorization: Bearer ${KC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"testuser\",\"email\":\"user@archon.local\",\"enabled\":true,\"firstName\":\"Test\",\"lastName\":\"User\",\"credentials\":[${USER_CREDS}]}" || true

echo "▸ Verifying realm..."
curl -sf "${KC_BASE}/realms/archon/.well-known/openid-configuration" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Issuer: {d[\"issuer\"]}')"

echo "✓ Keycloak provisioning complete."
echo ""
echo "Test login:"
echo "  curl -s -X POST '${KC_BASE}/realms/archon/protocol/openid-connect/token' \\"
echo "    -d 'client_id=archon-app&username=admin&grant_type=password&password=admin123'"
