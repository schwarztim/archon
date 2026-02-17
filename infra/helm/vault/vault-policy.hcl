# =============================================================================
# Archon — Base Vault Policies
# =============================================================================
# Namespace pattern: archon/{tenant_id}/<engine>
# These policies are loaded by vault-init.sh during bootstrap.
# =============================================================================

# ---------------------------------------------------------------------------
# archon-admin
# Full access to all archon/* paths (platform operators).
# ---------------------------------------------------------------------------
path "archon/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}

# ---------------------------------------------------------------------------
# archon-app
# Application-level access:
#   - Read/write secrets for any tenant
#   - Read PKI certificates for any tenant
# ---------------------------------------------------------------------------
path "archon/+/secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "archon/+/pki/*" {
  capabilities = ["read", "list"]
}

# ---------------------------------------------------------------------------
# archon-rotation
# Credential rotation service:
#   - Update secrets for any tenant
#   - Rotate PKI certificates for any tenant
# ---------------------------------------------------------------------------
path "archon/+/secret/*" {
  capabilities = ["update"]
}

path "archon/+/pki/*" {
  capabilities = ["update", "sudo"]
}

# ---------------------------------------------------------------------------
# archon-readonly
# Read-only access to secret data (auditors, dashboards).
# Scoped to the /data/ subpath so metadata stays hidden.
# ---------------------------------------------------------------------------
path "archon/+/secret/data/*" {
  capabilities = ["read", "list"]
}
