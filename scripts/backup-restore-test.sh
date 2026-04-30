#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Archon Backup/Restore Round-Trip Test
#
# Spins up a clean Postgres + Vault stack, seeds sample data, runs
# backup → wipe → restore, and verifies the data survived.
#
# Skips cleanly (exit 0) when Docker / pg_dump / vault CLI is missing.
#
# Usage:
#   bash scripts/backup-restore-test.sh [--help]
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: backup-restore-test.sh

Round-trips the Postgres and Vault backup scripts:
  1. Bring up a sandbox stack via docker compose (postgres + vault).
  2. Seed deterministic sample data.
  3. Run backup-postgres.sh + backup-vault.sh --kv-only.
  4. Drop the schema / clear KV.
  5. Run restore-postgres.sh + restore-vault.sh --kv-only.
  6. Diff the restored data against the seed and assert equality.

Exits 0 with "skipped" when the host lacks Docker / pg_dump / vault.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_BACKUP_DIR="$(mktemp -d -t archon-backup-test-XXXXXX)"
trap 'rm -rf "${TEST_BACKUP_DIR}"' EXIT

skip() {
  echo "[backup-restore-test] skipped — $1"
  exit 0
}

# ── Tooling preflight ───────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || skip "docker not available"
docker info >/dev/null 2>&1       || skip "docker daemon not reachable"
command -v pg_dump >/dev/null 2>&1 || skip "pg_dump not on PATH"
command -v pg_restore >/dev/null 2>&1 || skip "pg_restore not on PATH"
command -v psql >/dev/null 2>&1 || skip "psql not on PATH"
command -v vault >/dev/null 2>&1 || skip "vault CLI not on PATH"

# ── Sandbox postgres ─────────────────────────────────────────────────
PG_CONTAINER="archon-bk-test-pg"
VAULT_CONTAINER="archon-bk-test-vault"
PG_PORT="55432"
VAULT_PORT="58200"

cleanup_containers() {
  docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${VAULT_CONTAINER}" >/dev/null 2>&1 || true
}
trap 'cleanup_containers; rm -rf "${TEST_BACKUP_DIR}"' EXIT

cleanup_containers

echo "[backup-restore-test] starting postgres sandbox on :${PG_PORT}"
docker run -d --rm --name "${PG_CONTAINER}" \
  -e POSTGRES_USER=archon -e POSTGRES_PASSWORD=archon -e POSTGRES_DB=archon \
  -p "${PG_PORT}:5432" postgres:16-alpine >/dev/null

echo "[backup-restore-test] starting vault sandbox on :${VAULT_PORT}"
docker run -d --rm --name "${VAULT_CONTAINER}" \
  --cap-add=IPC_LOCK \
  -e VAULT_DEV_ROOT_TOKEN_ID=test-root \
  -e VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200 \
  -p "${VAULT_PORT}:8200" hashicorp/vault:1.15 >/dev/null

# Wait for postgres ready.
i=0
while ! docker exec "${PG_CONTAINER}" pg_isready -U archon >/dev/null 2>&1; do
  i=$((i + 1))
  if [[ $i -gt 30 ]]; then
    echo "[backup-restore-test] FAIL: postgres did not become ready"
    exit 1
  fi
  sleep 1
done

# Wait for vault ready.
export VAULT_ADDR="http://127.0.0.1:${VAULT_PORT}"
export VAULT_TOKEN="test-root"
i=0
while ! vault status >/dev/null 2>&1; do
  i=$((i + 1))
  if [[ $i -gt 30 ]]; then
    echo "[backup-restore-test] FAIL: vault did not become ready"
    exit 1
  fi
  sleep 1
done

PG_URL="postgresql://archon:archon@localhost:${PG_PORT}/archon"

# ── Seed sample data ─────────────────────────────────────────────────
echo "[backup-restore-test] seeding sample data"
psql "${PG_URL}" >/dev/null <<'SQL'
CREATE TABLE bk_sample (id INT PRIMARY KEY, name TEXT NOT NULL);
INSERT INTO bk_sample VALUES
  (1, 'alpha'),
  (2, 'beta'),
  (3, 'gamma');
SQL

vault kv put secret/archon/test \
  marker="round-trip-canary" \
  count="3" >/dev/null

# ── Backup ──────────────────────────────────────────────────────────
echo "[backup-restore-test] running postgres backup"
BACKUP_DIR="${TEST_BACKUP_DIR}" DB_URL="${PG_URL}" \
  bash "${REPO_ROOT}/scripts/backup-postgres.sh"

echo "[backup-restore-test] running vault backup (kv-only, no encrypt)"
BACKUP_DIR="${TEST_BACKUP_DIR}" \
  VAULT_KV_PREFIX="secret/archon" \
  bash "${REPO_ROOT}/scripts/backup-vault.sh" --kv-only --no-encrypt

# Locate produced artifacts.
PG_DUMP="$(find "${TEST_BACKUP_DIR}" -name 'archon-postgres-*.dump.gz' -type f | head -1)"
VAULT_SNAP="$(find "${TEST_BACKUP_DIR}" -name 'archon-vault-*.snap' -type f | head -1)"

if [[ -z "${PG_DUMP}" || -z "${VAULT_SNAP}" ]]; then
  echo "[backup-restore-test] FAIL: backup artifacts not found"
  ls -la "${TEST_BACKUP_DIR}" >&2
  exit 1
fi

# ── Wipe ────────────────────────────────────────────────────────────
echo "[backup-restore-test] wiping postgres data"
psql "${PG_URL}" >/dev/null <<'SQL'
DROP TABLE bk_sample;
SQL

echo "[backup-restore-test] wiping vault data"
vault kv delete secret/archon/test >/dev/null

# ── Restore ─────────────────────────────────────────────────────────
echo "[backup-restore-test] running postgres restore"
DB_URL="${PG_URL}" \
  bash "${REPO_ROOT}/scripts/restore-postgres.sh" "${PG_DUMP}" --yes --skip-alembic

echo "[backup-restore-test] running vault restore (kv-only)"
bash "${REPO_ROOT}/scripts/restore-vault.sh" "${VAULT_SNAP}" --kv-only --yes

# ── Verify ──────────────────────────────────────────────────────────
echo "[backup-restore-test] verifying postgres data"
ROW_COUNT="$(psql "${PG_URL}" -tA -c 'SELECT COUNT(*) FROM bk_sample;' 2>/dev/null || echo 0)"
NAMES="$(psql "${PG_URL}" -tA -c "SELECT name FROM bk_sample ORDER BY id;" 2>/dev/null | tr '\n' ',' || true)"

if [[ "${ROW_COUNT}" != "3" ]]; then
  echo "[backup-restore-test] FAIL: expected 3 rows, got ${ROW_COUNT}"
  exit 1
fi
if [[ "${NAMES}" != "alpha,beta,gamma," ]]; then
  echo "[backup-restore-test] FAIL: unexpected row names: ${NAMES}"
  exit 1
fi

echo "[backup-restore-test] verifying vault data"
MARKER="$(vault kv get -field=marker secret/archon/test 2>/dev/null || echo '')"
if [[ "${MARKER}" != "round-trip-canary" ]]; then
  echo "[backup-restore-test] FAIL: vault marker missing/wrong: '${MARKER}'"
  exit 1
fi

echo "[backup-restore-test] PASS"
exit 0
