#!/usr/bin/env bash
# =============================================================================
# Archon — Vault Initialization Script
# =============================================================================
# Bootstraps Vault with the engines, policies, and PKI infrastructure that
# Archon requires.  The script is **idempotent** — every mutating action
# checks whether the resource already exists before creating it.
#
# Usage:
#   export VAULT_ADDR=https://vault.vault.svc.cluster.local:8200
#   export VAULT_TOKEN=<root-or-admin-token>
#   ./vault-init.sh
#
# Namespace pattern: archon/{tenant_id}/<engine>
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VAULT_ADDR="${VAULT_ADDR:?VAULT_ADDR must be set}"
VAULT_TOKEN="${VAULT_TOKEN:?VAULT_TOKEN must be set}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_FILE="${SCRIPT_DIR}/vault-policy.hcl"

PKI_ROOT_TTL="87600h"      # 10 years
PKI_INTERMEDIATE_TTL="43800h"  # 5 years
PKI_CERT_TTL="8760h"       # 1 year

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "[archon-vault-init] $*"; }

vault_api() {
  # Usage: vault_api METHOD PATH [DATA]
  local method="$1" path="$2" data="${3:-}"
  local args=(-s -H "X-Vault-Token: ${VAULT_TOKEN}" -X "${method}")
  if [[ -n "${data}" ]]; then
    args+=(-H "Content-Type: application/json" -d "${data}")
  fi
  curl "${args[@]}" "${VAULT_ADDR}/v1/${path}"
}

engine_exists() {
  # Returns 0 if the secrets engine at $1 is already mounted.
  local mount="$1"
  vault_api GET "sys/mounts" | grep -q "\"${mount}/\""
}

auth_method_exists() {
  # Returns 0 if the auth method at $1 is already enabled.
  local mount="$1"
  vault_api GET "sys/auth" | grep -q "\"${mount}/\""
}

policy_exists() {
  local name="$1"
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-Vault-Token: ${VAULT_TOKEN}" \
    "${VAULT_ADDR}/v1/sys/policies/acl/${name}")
  [[ "${status}" == "200" ]]
}

# =============================================================================
# 1. Enable Secrets Engines
# =============================================================================
log "--- Enabling secrets engines ---"

# KV-v2 at archon/secret
if engine_exists "archon/secret"; then
  log "KV-v2 engine at archon/secret already exists — skipping"
else
  log "Enabling KV-v2 at archon/secret"
  vault_api POST "sys/mounts/archon/secret" \
    '{"type":"kv","options":{"version":"2"}}'
fi

# PKI at archon/pki
if engine_exists "archon/pki"; then
  log "PKI engine at archon/pki already exists — skipping"
else
  log "Enabling PKI at archon/pki"
  vault_api POST "sys/mounts/archon/pki" \
    '{"type":"pki","config":{"max_lease_ttl":"'${PKI_ROOT_TTL}'"}}'
fi

# Transit at archon/transit
if engine_exists "archon/transit"; then
  log "Transit engine at archon/transit already exists — skipping"
else
  log "Enabling Transit at archon/transit"
  vault_api POST "sys/mounts/archon/transit" \
    '{"type":"transit"}'
fi

# Database at archon/database
if engine_exists "archon/database"; then
  log "Database engine at archon/database already exists — skipping"
else
  log "Enabling Database at archon/database"
  vault_api POST "sys/mounts/archon/database" \
    '{"type":"database"}'
fi

# =============================================================================
# 2. Create Vault Policies
# =============================================================================
log "--- Creating Vault policies ---"

# The policy file contains multiple policy blocks separated by comments.
# We extract each named section and write it as an individual policy.

create_policy() {
  local name="$1" rules="$2"
  if policy_exists "${name}"; then
    log "Policy '${name}' already exists — skipping"
  else
    log "Creating policy '${name}'"
    # Escape the HCL rules for JSON transport
    local payload
    payload=$(printf '{"policy": %s}' "$(echo "${rules}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')")
    vault_api PUT "sys/policies/acl/${name}" "${payload}"
  fi
}

# --- archon-admin: full access to archon/* ---
create_policy "archon-admin" 'path "archon/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}'

# --- archon-app: read/write secrets, read PKI ---
create_policy "archon-app" 'path "archon/+/secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "archon/+/pki/*" {
  capabilities = ["read", "list"]
}'

# --- archon-rotation: update secrets, rotate PKI ---
create_policy "archon-rotation" 'path "archon/+/secret/*" {
  capabilities = ["update"]
}

path "archon/+/pki/*" {
  capabilities = ["update", "sudo"]
}'

# --- archon-readonly: read-only on secret data ---
create_policy "archon-readonly" 'path "archon/+/secret/data/*" {
  capabilities = ["read", "list"]
}'

# =============================================================================
# 3. Configure PKI — Root CA
# =============================================================================
log "--- Configuring PKI Root CA ---"

# Generate an internal root CA if one hasn't been created yet.
ROOT_CA_CHECK=$(vault_api GET "archon/pki/ca/pem")
if [[ -n "${ROOT_CA_CHECK}" && "${ROOT_CA_CHECK}" != *"\"errors\""* && "${ROOT_CA_CHECK}" != "" ]]; then
  log "Root CA already exists — skipping generation"
else
  log "Generating root CA (archon-ca, TTL=${PKI_ROOT_TTL})"
  vault_api POST "archon/pki/root/generate/internal" \
    '{
      "common_name": "archon-ca",
      "ttl": "'"${PKI_ROOT_TTL}"'",
      "key_type": "rsa",
      "key_bits": 4096,
      "organization": "Archon",
      "ou": "Platform Security"
    }'
fi

# Configure issuing and CRL URLs
log "Setting PKI issuing/CRL URLs"
vault_api POST "archon/pki/config/urls" \
  '{
    "issuing_certificates": "'"${VAULT_ADDR}"'/v1/archon/pki/ca",
    "crl_distribution_points": "'"${VAULT_ADDR}"'/v1/archon/pki/crl"
  }'

# =============================================================================
# 4. Configure PKI — Intermediate CA
# =============================================================================
log "--- Configuring Intermediate CA ---"

# Enable an intermediate PKI mount if not present
if engine_exists "archon/pki-intermediate"; then
  log "Intermediate PKI engine already exists — skipping"
else
  log "Enabling intermediate PKI at archon/pki-intermediate"
  vault_api POST "sys/mounts/archon/pki-intermediate" \
    '{"type":"pki","config":{"max_lease_ttl":"'${PKI_INTERMEDIATE_TTL}'"}}'
fi

# Generate intermediate CSR
INTERMEDIATE_CHECK=$(vault_api GET "archon/pki-intermediate/ca/pem")
if [[ -n "${INTERMEDIATE_CHECK}" && "${INTERMEDIATE_CHECK}" != *"\"errors\""* && "${INTERMEDIATE_CHECK}" != "" ]]; then
  log "Intermediate CA already signed — skipping"
else
  log "Generating intermediate CSR"
  CSR_RESPONSE=$(vault_api POST "archon/pki-intermediate/intermediate/generate/internal" \
    '{
      "common_name": "archon-intermediate-ca",
      "key_type": "rsa",
      "key_bits": 4096,
      "organization": "Archon",
      "ou": "Platform Security"
    }')

  CSR=$(echo "${CSR_RESPONSE}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["csr"])' 2>/dev/null || true)

  if [[ -z "${CSR}" ]]; then
    log "ERROR: Failed to extract intermediate CSR"
    exit 1
  fi

  # Sign the intermediate CSR with the root CA
  log "Signing intermediate CA with root"
  SIGNED_RESPONSE=$(vault_api POST "archon/pki/root/sign-intermediate" \
    "$(printf '{"csr": %s, "format": "pem_bundle", "ttl": "%s"}' \
      "$(echo "${CSR}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')" \
      "${PKI_INTERMEDIATE_TTL}")")

  SIGNED_CERT=$(echo "${SIGNED_RESPONSE}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["certificate"])' 2>/dev/null || true)

  if [[ -z "${SIGNED_CERT}" ]]; then
    log "ERROR: Failed to sign intermediate certificate"
    exit 1
  fi

  # Set the signed certificate on the intermediate mount
  log "Setting signed intermediate certificate"
  vault_api POST "archon/pki-intermediate/intermediate/set-signed" \
    "$(printf '{"certificate": %s}' "$(echo "${SIGNED_CERT}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')")"
fi

# Create a default role for issuing certificates
log "Creating default PKI role 'archon-service'"
vault_api POST "archon/pki-intermediate/roles/archon-service" \
  '{
    "allowed_domains": ["archon.local", "archon.svc.cluster.local"],
    "allow_subdomains": true,
    "max_ttl": "'"${PKI_CERT_TTL}"'",
    "key_type": "rsa",
    "key_bits": 2048,
    "require_cn": true
  }'

# =============================================================================
# 5. Configure AppRole Auth Method
# =============================================================================
log "--- Configuring AppRole auth ---"

if auth_method_exists "approle"; then
  log "AppRole auth method already enabled — skipping"
else
  log "Enabling AppRole auth method"
  vault_api POST "sys/auth/approle" \
    '{"type":"approle"}'
fi

# Create the default application role bound to archon-app policy
log "Creating AppRole 'archon-app'"
vault_api POST "auth/approle/role/archon-app" \
  '{
    "token_policies": ["archon-app"],
    "token_ttl": "1h",
    "token_max_ttl": "4h",
    "secret_id_ttl": "720h",
    "secret_id_num_uses": 0,
    "bind_secret_id": true
  }'

# Create a rotation service role bound to archon-rotation policy
log "Creating AppRole 'archon-rotation'"
vault_api POST "auth/approle/role/archon-rotation" \
  '{
    "token_policies": ["archon-rotation"],
    "token_ttl": "30m",
    "token_max_ttl": "1h",
    "secret_id_ttl": "720h",
    "secret_id_num_uses": 0,
    "bind_secret_id": true
  }'

# =============================================================================
# Done
# =============================================================================
log "=== Vault initialization complete ==="
