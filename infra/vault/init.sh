#!/usr/bin/env sh
# ─────────────────────────────────────────────────────────────────────
# Archon Vault Bootstrap (DEV ONLY)
#
# Idempotent initializer for the local docker-compose Vault dev server.
# Enables secret engines, writes the archon-app policy, and seeds
# placeholder secrets the backend + worker expect to find at startup.
#
# Run via:
#   docker compose run --rm vault-init
#   make secrets-init
#
# Production note: this script is for local development only. Production
# deployments must:
#   - run Vault in production mode (not -dev)
#   - rotate the root token after init
#   - replace placeholders with real secrets via vault kv put
#   - apply real PKI roots (not the dev root issued here)
# ─────────────────────────────────────────────────────────────────────
set -eu

VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-archon-dev-root}"
export VAULT_ADDR VAULT_TOKEN

echo "[vault-init] addr=${VAULT_ADDR}"

# Wait for Vault to be reachable. The vault container's healthcheck handles
# the depends_on gate, but we also retry here to defend against slow startup.
i=0
while [ $i -lt 30 ]; do
  if vault status >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

if ! vault status >/dev/null 2>&1; then
  echo "[vault-init] ERROR: vault unreachable at ${VAULT_ADDR}" >&2
  exit 1
fi

# ── Enable secret engines (idempotent) ──────────────────────────────
# kv-v2 at secret/ — already enabled in dev mode by default, but we
# guard with || true so the script is safe to re-run on prod-like
# vaults where it isn't.
echo "[vault-init] enabling kv-v2 at secret/ (idempotent)"
if vault secrets list -format=json | grep -q '"secret/"'; then
  echo "[vault-init]   already enabled"
else
  vault secrets enable -path=secret kv-v2
fi

echo "[vault-init] enabling pki engine (idempotent)"
if vault secrets list -format=json | grep -q '"pki/"'; then
  echo "[vault-init]   already enabled"
else
  vault secrets enable pki
  vault secrets tune -max-lease-ttl=87600h pki
fi

# ── Write archon-app policy from HCL file ───────────────────────────
echo "[vault-init] writing policy archon-app"
vault policy write archon-app /vault/policies/archon-app.hcl

# ── Seed placeholder secrets (DEV ONLY, idempotent overwrite) ───────
# These are placeholders read by the backend on startup. Real values
# must be rotated in via `vault kv put` for production deployments.
echo "[vault-init] seeding placeholder secrets at secret/archon/*"

vault kv put secret/archon/keycloak \
  admin_user="placeholder-keycloak-admin" \
  admin_password="placeholder-keycloak-admin-password" \
  client_secret="placeholder-keycloak-client-secret"

vault kv put secret/archon/database \
  username="archon" \
  password="placeholder-archon-db-password" \
  url="postgresql+asyncpg://archon:archon@postgres:5432/archon"

vault kv put secret/archon/jwt \
  signing_key="placeholder-jwt-signing-key" \
  algorithm="HS256"

vault kv put secret/archon/llm \
  openai_api_key="placeholder-openai-api-key" \
  azure_openai_api_key="placeholder-azure-openai-api-key" \
  azure_openai_endpoint="placeholder-azure-openai-endpoint"

vault kv put secret/archon/redis \
  url="redis://redis:6379/0" \
  password="placeholder-redis-password"

# ── Configure PKI for tenant cert issuance (best-effort dev setup) ──
# Generate a self-signed root only if not already present. The check
# uses `vault read` exit status as a proxy for "is configured".
echo "[vault-init] configuring PKI root (idempotent)"
if vault read -format=json pki/cert/ca >/dev/null 2>&1; then
  echo "[vault-init]   PKI root already configured"
else
  vault write -field=certificate pki/root/generate/internal \
    common_name="archon-dev-root" \
    ttl=87600h >/dev/null
  vault write pki/roles/archon-tenant \
    allowed_domains="archon.local,archon.dev" \
    allow_subdomains=true \
    allow_localhost=true \
    max_ttl=720h >/dev/null
fi

echo "[vault-init] complete"
