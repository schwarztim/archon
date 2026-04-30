#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Archon Vault Backup
#
# Captures a HashiCorp Vault snapshot. Two modes are supported:
#
#   1. Raft mode — `vault operator raft snapshot save` (preferred).
#   2. KV-only fallback — iterates secret/archon/* and exports each
#      KV-v2 entry as JSON. Used when the cluster has no Raft backend
#      (e.g. dev-mode or Consul-backed).
#
# The output is encrypted at rest with operator-supplied AES-256
# (openssl enc -aes-256-cbc -pbkdf2). The encryption key is read from
# VAULT_BACKUP_KEY (env) or prompted interactively. NEVER pass the key
# on the command line.
#
# Usage:
#   bash scripts/backup-vault.sh [--kv-only] [--no-encrypt] [--help]
#
# Environment:
#   BACKUP_DIR         Output directory (default: ./backups)
#   VAULT_ADDR         Vault address (default: http://127.0.0.1:8200)
#   VAULT_TOKEN        Vault auth token
#   VAULT_BACKUP_KEY   AES-256 passphrase for at-rest encryption
#   VAULT_KV_PREFIX    KV path to walk in --kv-only mode (default: secret/archon)
#
# Output:
#   <BACKUP_DIR>/archon-vault-<UTC-TIMESTAMP>.snap[.enc]
#   <BACKUP_DIR>/archon-vault-<UTC-TIMESTAMP>.snap[.enc].sha256
#
# Exit codes:
#   0  success
#   1  vault CLI unavailable / bad arguments
#   2  Raft snapshot failed
#   3  KV walk failed
#   4  encryption failed
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: backup-vault.sh [--kv-only] [--no-encrypt]

Snapshots a HashiCorp Vault cluster (Raft or KV-only) and encrypts the
result with operator-supplied AES-256-CBC.

Options:
  --kv-only      Skip Raft and walk VAULT_KV_PREFIX (default: secret/archon).
                 Use this with dev-mode Vault (no Raft backend).
  --no-encrypt   Skip at-rest encryption (NOT recommended for production).

Environment variables:
  BACKUP_DIR        Output directory (default: ./backups)
  VAULT_ADDR        Vault address (default: http://127.0.0.1:8200)
  VAULT_TOKEN       Vault auth token (required)
  VAULT_BACKUP_KEY  AES-256 passphrase (required unless --no-encrypt)
  VAULT_KV_PREFIX   KV path for --kv-only mode (default: secret/archon)
EOF
}

KV_ONLY="0"
NO_ENCRYPT="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --kv-only) KV_ONLY="1"; shift ;;
    --no-encrypt) NO_ENCRYPT="1"; shift ;;
    *) echo "[backup-vault] ERROR: unknown arg $1" >&2; exit 1 ;;
  esac
done

if ! command -v vault >/dev/null 2>&1; then
  echo "[backup-vault] ERROR: vault CLI not on PATH" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_KV_PREFIX="${VAULT_KV_PREFIX:-secret/archon}"
export VAULT_ADDR

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  echo "[backup-vault] ERROR: VAULT_TOKEN must be set" >&2
  exit 1
fi
export VAULT_TOKEN

mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RAW_FILE="${BACKUP_DIR}/archon-vault-${TIMESTAMP}.snap"

if [[ "${KV_ONLY}" == "1" ]]; then
  echo "[backup-vault] mode=kv-only prefix=${VAULT_KV_PREFIX}"
  if ! command -v jq >/dev/null 2>&1; then
    echo "[backup-vault] ERROR: jq required for --kv-only mode" >&2
    exit 1
  fi
  # KV-v2 list returns paths under <mount>/metadata/<sub>/. We assume
  # mount=secret/. Walk recursively, dump each leaf key as JSON.
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR}"' EXIT

  walk() {
    local prefix="$1"
    local listing
    if ! listing="$(vault kv list -format=json "${prefix}" 2>/dev/null)"; then
      return 0
    fi
    local entries
    entries="$(echo "${listing}" | jq -r '.[]' 2>/dev/null || echo '')"
    while IFS= read -r entry; do
      [[ -z "${entry}" ]] && continue
      if [[ "${entry}" == */ ]]; then
        walk "${prefix}/${entry%/}"
      else
        local full_path="${prefix}/${entry}"
        local sanitized
        sanitized="${full_path//\//_}"
        if ! vault kv get -format=json "${full_path}" \
             > "${TMP_DIR}/${sanitized}.json" 2>/dev/null; then
          echo "[backup-vault] WARNING: could not read ${full_path}" >&2
        fi
      fi
    done <<< "${entries}"
  }

  walk "${VAULT_KV_PREFIX}"
  if ! tar -cf "${RAW_FILE}" -C "${TMP_DIR}" .; then
    echo "[backup-vault] ERROR: tar failed" >&2
    exit 3
  fi
else
  echo "[backup-vault] mode=raft addr=${VAULT_ADDR}"
  if ! vault operator raft snapshot save "${RAW_FILE}"; then
    echo "[backup-vault] ERROR: raft snapshot save failed" >&2
    echo "[backup-vault] Hint: rerun with --kv-only for dev-mode Vault." >&2
    exit 2
  fi
fi

OUT_FILE="${RAW_FILE}"

if [[ "${NO_ENCRYPT}" == "1" ]]; then
  echo "[backup-vault] WARNING: encryption skipped (--no-encrypt)"
else
  if ! command -v openssl >/dev/null 2>&1; then
    echo "[backup-vault] ERROR: openssl required for encryption" >&2
    exit 4
  fi
  if [[ -z "${VAULT_BACKUP_KEY:-}" ]]; then
    echo "[backup-vault] VAULT_BACKUP_KEY not set; prompting interactively" >&2
    read -rsp "Backup encryption passphrase: " VAULT_BACKUP_KEY
    echo
  fi
  if [[ -z "${VAULT_BACKUP_KEY}" ]]; then
    echo "[backup-vault] ERROR: empty encryption passphrase" >&2
    exit 4
  fi
  ENC_FILE="${RAW_FILE}.enc"
  if ! openssl enc -aes-256-cbc -pbkdf2 -salt \
       -in "${RAW_FILE}" -out "${ENC_FILE}" \
       -pass env:VAULT_BACKUP_KEY; then
    echo "[backup-vault] ERROR: openssl enc failed" >&2
    exit 4
  fi
  shred -u "${RAW_FILE}" 2>/dev/null || rm -f "${RAW_FILE}"
  OUT_FILE="${ENC_FILE}"
fi

# Checksum sidecar
SHA_FILE="${OUT_FILE}.sha256"
OUT_BASENAME="$(basename "${OUT_FILE}")"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "${BACKUP_DIR}" && sha256sum "${OUT_BASENAME}" > "${OUT_BASENAME}.sha256")
elif command -v shasum >/dev/null 2>&1; then
  (cd "${BACKUP_DIR}" && shasum -a 256 "${OUT_BASENAME}" > "${OUT_BASENAME}.sha256")
fi

SIZE_BYTES="$(wc -c < "${OUT_FILE}" | tr -d ' ')"
echo "[backup-vault] output=${OUT_FILE} (${SIZE_BYTES} bytes)"
echo "[backup-vault] checksum=${SHA_FILE}"
echo "[backup-vault] complete"
