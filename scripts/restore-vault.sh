#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Archon Vault Restore
#
# Restores a snapshot produced by backup-vault.sh. Mirrors the
# Raft / KV-only modes of the backup script.
#
# Usage:
#   bash scripts/restore-vault.sh <SNAP_FILE[.enc]> [--kv-only] [--yes] [--help]
#
# Environment:
#   VAULT_ADDR        Vault address (default: http://127.0.0.1:8200)
#   VAULT_TOKEN       Vault auth token (required)
#   VAULT_BACKUP_KEY  AES-256 passphrase (required for *.enc files)
#   VAULT_KV_PREFIX   KV prefix (used for sanity logs in --kv-only mode)
#
# Exit codes:
#   0  success
#   1  bad arguments / tooling missing
#   2  decryption failure
#   3  checksum mismatch
#   4  raft restore failure
#   5  KV import failure
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: restore-vault.sh <SNAP_FILE[.enc]> [--kv-only] [--yes]

Restores a Vault snapshot.  Mirrors the modes from backup-vault.sh.

Options:
  --kv-only      Treat the input as a tar archive of `vault kv get -format=json`
                 dumps (one file per leaf path) and re-write each one with
                 `vault kv put`.
  --yes          Skip the destructive-action confirmation prompt.

Environment:
  VAULT_ADDR        Vault address (default: http://127.0.0.1:8200)
  VAULT_TOKEN       Vault auth token (required)
  VAULT_BACKUP_KEY  AES-256 passphrase (required for *.enc files)
EOF
}

SNAP_FILE=""
KV_ONLY="0"
YES="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --kv-only) KV_ONLY="1"; shift ;;
    --yes) YES="1"; shift ;;
    -*) echo "[restore-vault] ERROR: unknown flag $1" >&2; exit 1 ;;
    *) SNAP_FILE="$1"; shift ;;
  esac
done

if [[ -z "${SNAP_FILE}" ]]; then
  usage
  exit 1
fi
if [[ ! -f "${SNAP_FILE}" ]]; then
  echo "[restore-vault] ERROR: snapshot not found: ${SNAP_FILE}" >&2
  exit 1
fi

if ! command -v vault >/dev/null 2>&1; then
  echo "[restore-vault] ERROR: vault CLI not on PATH" >&2
  exit 1
fi

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
export VAULT_ADDR
if [[ -z "${VAULT_TOKEN:-}" ]]; then
  echo "[restore-vault] ERROR: VAULT_TOKEN must be set" >&2
  exit 1
fi
export VAULT_TOKEN

# Verify checksum if sidecar exists.
SHA_FILE="${SNAP_FILE}.sha256"
if [[ -f "${SHA_FILE}" ]]; then
  echo "[restore-vault] verifying checksum"
  SNAP_DIR="$(dirname "${SNAP_FILE}")"
  SHA_BASE="$(basename "${SHA_FILE}")"
  if command -v sha256sum >/dev/null 2>&1; then
    if ! (cd "${SNAP_DIR}" && sha256sum -c "${SHA_BASE}"); then
      echo "[restore-vault] ERROR: checksum mismatch" >&2
      exit 3
    fi
  elif command -v shasum >/dev/null 2>&1; then
    if ! (cd "${SNAP_DIR}" && shasum -a 256 -c "${SHA_BASE}"); then
      echo "[restore-vault] ERROR: checksum mismatch" >&2
      exit 3
    fi
  fi
fi

# Decrypt if needed.
WORK_FILE="${SNAP_FILE}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

if [[ "${SNAP_FILE}" == *.enc ]]; then
  if [[ -z "${VAULT_BACKUP_KEY:-}" ]]; then
    read -rsp "Backup encryption passphrase: " VAULT_BACKUP_KEY
    echo
  fi
  WORK_FILE="${TMP_DIR}/$(basename "${SNAP_FILE%.enc}")"
  if ! openssl enc -d -aes-256-cbc -pbkdf2 \
       -in "${SNAP_FILE}" -out "${WORK_FILE}" \
       -pass env:VAULT_BACKUP_KEY; then
    echo "[restore-vault] ERROR: decryption failed" >&2
    exit 2
  fi
fi

if [[ "${YES}" != "1" ]]; then
  cat <<EOF >&2

  ╔══════════════════════════════════════════════════════════════╗
  ║  WARNING: vault restore will overwrite cluster state.        ║
  ║  Target: ${VAULT_ADDR}                                       ║
  ╚══════════════════════════════════════════════════════════════╝

EOF
  read -rp "Type 'yes' to proceed: " confirm
  if [[ "${confirm}" != "yes" ]]; then
    echo "[restore-vault] aborted" >&2
    exit 0
  fi
fi

if [[ "${KV_ONLY}" == "1" ]]; then
  if ! command -v jq >/dev/null 2>&1; then
    echo "[restore-vault] ERROR: jq required for --kv-only mode" >&2
    exit 1
  fi
  EXTRACT_DIR="${TMP_DIR}/extract"
  mkdir -p "${EXTRACT_DIR}"
  if ! tar -xf "${WORK_FILE}" -C "${EXTRACT_DIR}"; then
    echo "[restore-vault] ERROR: failed to untar snapshot" >&2
    exit 5
  fi
  echo "[restore-vault] importing KV entries"
  count=0
  for f in "${EXTRACT_DIR}"/*.json; do
    [[ -f "$f" ]] || continue
    # Path is encoded by replacing '/' with '_' in the original backup.
    base="$(basename "${f}" .json)"
    path="${base//_//}"
    data="$(jq -c '.data.data' "${f}" 2>/dev/null || echo 'null')"
    if [[ "${data}" == "null" ]]; then
      echo "[restore-vault] WARNING: skipping ${path} (no .data.data)" >&2
      continue
    fi
    # Convert JSON object to k=v args for `vault kv put`.
    kv_args=()
    while IFS= read -r kv; do
      kv_args+=("${kv}")
    done < <(echo "${data}" | jq -r 'to_entries[] | "\(.key)=\(.value|tostring)"')
    if [[ ${#kv_args[@]} -eq 0 ]]; then
      continue
    fi
    if ! vault kv put "${path}" "${kv_args[@]}" >/dev/null 2>&1; then
      echo "[restore-vault] WARNING: failed to write ${path}" >&2
    else
      count=$((count + 1))
    fi
  done
  echo "[restore-vault] imported ${count} KV entries"
else
  echo "[restore-vault] running raft snapshot restore"
  if ! vault operator raft snapshot restore -force "${WORK_FILE}"; then
    echo "[restore-vault] ERROR: raft snapshot restore failed" >&2
    exit 4
  fi
fi

echo "[restore-vault] complete"
