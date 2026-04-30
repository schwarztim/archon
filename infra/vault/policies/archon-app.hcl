# Policy: archon-app
# Grants the Archon backend + worker read access to application secrets
# under secret/data/archon/* (KV v2 layout).
#
# Mounted at: secret/  (KV v2)
# Consumed by: backend, worker (token bound at deploy time)

path "secret/data/archon/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/archon/*" {
  capabilities = ["read", "list"]
}

# PKI: allow signing tenant-scoped client certs (issuance only — no root mgmt).
path "pki/issue/archon-tenant" {
  capabilities = ["create", "update"]
}

path "pki/sign/archon-tenant" {
  capabilities = ["create", "update"]
}
