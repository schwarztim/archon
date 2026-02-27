#!/bin/sh
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
set -eu

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
: "${VAULT_ADDR:?VAULT_ADDR must be set}"
: "${VAULT_TOKEN:?VAULT_TOKEN must be set}"

PKI_ROOT_TTL="87600h"          # 10 years
PKI_INTERMEDIATE_TTL="43800h"  # 5 years
PKI_CERT_TTL="8760h"           # 1 year

# vault CLI exports so every sub-command picks them up automatically
export VAULT_ADDR
export VAULT_TOKEN
# Silence progress output from vault CLI
export VAULT_FORMAT=json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { printf '[archon-vault-init] %s\n' "$*"; }

# vault_api METHOD PATH [DATA]
# Low-level curl wrapper kept for endpoints where vault CLI has no equivalent.
vault_api() {
  local method
  local path
  local data
  method="$1"
  path="$2"
  data="${3:-}"
  if [ -n "${data}" ]; then
    curl -sf \
      -H "X-Vault-Token: ${VAULT_TOKEN}" \
      -H "Content-Type: application/json" \
      -X "${method}" \
      -d "${data}" \
      "${VAULT_ADDR}/v1/${path}"
  else
    curl -sf \
      -H "X-Vault-Token: ${VAULT_TOKEN}" \
      -X "${method}" \
      "${VAULT_ADDR}/v1/${path}"
  fi
}

# Returns 0 if the secrets engine at $1 is already mounted.
engine_exists() {
  local mount
  mount="$1"
  vault secrets list -format=table 2>/dev/null | grep -q "^${mount}/"
}

# Returns 0 if the auth method at $1 is already enabled.
auth_method_exists() {
  local mount
  mount="$1"
  vault auth list -format=table 2>/dev/null | grep -q "^${mount}/"
}

# Returns 0 if the ACL policy named $1 already exists.
policy_exists() {
  local name
  name="$1"
  vault policy read "${name}" >/dev/null 2>&1
}

# json_str_escape: escape a multi-line string for embedding as a JSON string value.
# Replaces \ → \\, " → \", newlines → \n using awk.
json_str_escape() {
  printf '%s' "$1" | awk '
    NR > 1 { printf "\\n" }
    {
      gsub(/\\/, "\\\\")
      gsub(/"/, "\\\"")
      printf "%s", $0
    }
    END { printf "" }
  '
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
  vault secrets enable -path=archon/secret -version=2 kv
fi

# PKI at archon/pki
if engine_exists "archon/pki"; then
  log "PKI engine at archon/pki already exists — skipping"
else
  log "Enabling PKI at archon/pki"
  vault secrets enable -path=archon/pki -max-lease-ttl="${PKI_ROOT_TTL}" pki
fi

# Transit at archon/transit
if engine_exists "archon/transit"; then
  log "Transit engine at archon/transit already exists — skipping"
else
  log "Enabling Transit at archon/transit"
  vault secrets enable -path=archon/transit transit
fi

# Database at archon/database
if engine_exists "archon/database"; then
  log "Database engine at archon/database already exists — skipping"
else
  log "Enabling Database at archon/database"
  vault secrets enable -path=archon/database database
fi

# =============================================================================
# 2. Create Vault Policies
# =============================================================================
log "--- Creating Vault policies ---"

# create_policy NAME RULES_HCL
create_policy() {
  local name
  local rules
  name="$1"
  rules="$2"
  if policy_exists "${name}"; then
    log "Policy '${name}' already exists — skipping"
  else
    log "Creating policy '${name}'"
    printf '%s\n' "${rules}" | vault policy write "${name}" -
  fi
}

# --- archon-admin: full access to archon/* ---
create_policy "archon-admin" \
'path "archon/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}'

# --- archon-app: read/write secrets, read PKI ---
create_policy "archon-app" \
'path "archon/+/secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "archon/+/pki/*" {
  capabilities = ["read", "list"]
}'

# --- archon-rotation: update secrets, rotate PKI ---
create_policy "archon-rotation" \
'path "archon/+/secret/*" {
  capabilities = ["update"]
}

path "archon/+/pki/*" {
  capabilities = ["update", "sudo"]
}'

# --- archon-readonly: read-only on secret data ---
create_policy "archon-readonly" \
'path "archon/+/secret/data/*" {
  capabilities = ["read", "list"]
}'

# =============================================================================
# 3. Configure PKI — Root CA
# =============================================================================
log "--- Configuring PKI Root CA ---"

# Generate an internal root CA if one hasn't been created yet.
ROOT_CA_CHECK=$(vault_api GET "archon/pki/ca/pem" 2>/dev/null || true)
if [ -n "${ROOT_CA_CHECK}" ] && ! printf '%s' "${ROOT_CA_CHECK}" | grep -q '"errors"'; then
  log "Root CA already exists — skipping generation"
else
  log "Generating root CA (archon-ca, TTL=${PKI_ROOT_TTL})"
  vault write archon/pki/root/generate/internal \
    common_name="archon-ca" \
    ttl="${PKI_ROOT_TTL}" \
    key_type="rsa" \
    key_bits=4096 \
    organization="Archon" \
    ou="Platform Security"
fi

# Configure issuing and CRL URLs
log "Setting PKI issuing/CRL URLs"
vault write archon/pki/config/urls \
  issuing_certificates="${VAULT_ADDR}/v1/archon/pki/ca" \
  crl_distribution_points="${VAULT_ADDR}/v1/archon/pki/crl"

# =============================================================================
# 4. Configure PKI — Intermediate CA
# =============================================================================
log "--- Configuring Intermediate CA ---"

# Enable an intermediate PKI mount if not present
if engine_exists "archon/pki-intermediate"; then
  log "Intermediate PKI engine already exists — skipping"
else
  log "Enabling intermediate PKI at archon/pki-intermediate"
  vault secrets enable \
    -path=archon/pki-intermediate \
    -max-lease-ttl="${PKI_INTERMEDIATE_TTL}" \
    pki
fi

# Generate intermediate CSR and sign it if not already done
INTERMEDIATE_CHECK=$(vault_api GET "archon/pki-intermediate/ca/pem" 2>/dev/null || true)
if [ -n "${INTERMEDIATE_CHECK}" ] && ! printf '%s' "${INTERMEDIATE_CHECK}" | grep -q '"errors"'; then
  log "Intermediate CA already signed — skipping"
else
  log "Generating intermediate CSR"
  CSR_FILE=$(mktemp)
  CERT_FILE=$(mktemp)
  trap 'rm -f "${CSR_FILE}" "${CERT_FILE}"' EXIT

  VAULT_FORMAT= vault write -field=csr archon/pki-intermediate/intermediate/generate/internal \
    common_name="archon-intermediate-ca" \
    key_type="rsa" \
    key_bits=4096 \
    organization="Archon" \
    ou="Platform Security" > "${CSR_FILE}"

  if [ ! -s "${CSR_FILE}" ]; then
    log "ERROR: Failed to generate intermediate CSR"
    exit 1
  fi

  # Sign the intermediate CSR with the root CA
  log "Signing intermediate CA with root"
  VAULT_FORMAT= vault write -field=certificate archon/pki/root/sign-intermediate \
    csr=@"${CSR_FILE}" \
    format="pem_bundle" \
    ttl="${PKI_INTERMEDIATE_TTL}" > "${CERT_FILE}"

  if [ ! -s "${CERT_FILE}" ]; then
    log "ERROR: Failed to sign intermediate certificate"
    exit 1
  fi

  # Set the signed certificate on the intermediate mount
  log "Setting signed intermediate certificate"
  vault write archon/pki-intermediate/intermediate/set-signed \
    certificate=@"${CERT_FILE}"

  rm -f "${CSR_FILE}" "${CERT_FILE}"
fi

# Create a default role for issuing certificates
log "Creating default PKI role 'archon-service'"
vault write archon/pki-intermediate/roles/archon-service \
  allowed_domains="archon.local,archon.svc.cluster.local" \
  allow_subdomains=true \
  max_ttl="${PKI_CERT_TTL}" \
  key_type="rsa" \
  key_bits=2048 \
  require_cn=true

# =============================================================================
# 5. Configure AppRole Auth Method
# =============================================================================
log "--- Configuring AppRole auth ---"

if auth_method_exists "approle"; then
  log "AppRole auth method already enabled — skipping"
else
  log "Enabling AppRole auth method"
  vault auth enable approle
fi

# Create the default application role bound to archon-app policy
log "Creating AppRole 'archon-app'"
vault write auth/approle/role/archon-app \
  token_policies="archon-app" \
  token_ttl="1h" \
  token_max_ttl="4h" \
  secret_id_ttl="720h" \
  secret_id_num_uses=0 \
  bind_secret_id=true

# Create a rotation service role bound to archon-rotation policy
log "Creating AppRole 'archon-rotation'"
vault write auth/approle/role/archon-rotation \
  token_policies="archon-rotation" \
  token_ttl="30m" \
  token_max_ttl="1h" \
  secret_id_ttl="720h" \
  secret_id_num_uses=0 \
  bind_secret_id=true

# =============================================================================
# Done
# =============================================================================
log "=== Vault initialization complete ==="
