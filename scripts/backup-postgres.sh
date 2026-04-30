#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Archon Postgres Backup
#
# Creates a timestamped, compressed pg_dump of the Archon database with
# a SHA-256 checksum sidecar.
#
# Usage:
#   bash scripts/backup-postgres.sh [--help]
#
# Environment:
#   BACKUP_DIR  Directory for backup output (default: ./backups)
#   DB_URL      Postgres connection URL
#               (default: postgresql://archon:archon@localhost:5432/archon)
#   DB_NAME     Database name override (default: parsed from DB_URL or 'archon')
#
# Output:
#   <BACKUP_DIR>/archon-postgres-<UTC-TIMESTAMP>.dump.gz
#   <BACKUP_DIR>/archon-postgres-<UTC-TIMESTAMP>.dump.gz.sha256
#
# Exit codes:
#   0  success
#   1  pg_dump unavailable
#   2  connection / dump failure
#   3  checksum failure
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: backup-postgres.sh [--help]

Creates a gzip-compressed pg_dump archive with SHA-256 sidecar.

Environment variables:
  BACKUP_DIR  Output directory (default: ./backups)
  DB_URL      Postgres URL (default: postgresql://archon:archon@localhost:5432/archon)
  DB_NAME     Override database name parsed from DB_URL

Examples:
  bash scripts/backup-postgres.sh
  BACKUP_DIR=/var/backups/archon DB_URL=$ARCHON_DATABASE_URL bash scripts/backup-postgres.sh
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DB_URL="${DB_URL:-postgresql://archon:archon@localhost:5432/archon}"

# Strip async drivers (asyncpg / aiosqlite) — pg_dump uses libpq.
DB_URL_LIBPQ="${DB_URL//postgresql+asyncpg/postgresql}"
DB_URL_LIBPQ="${DB_URL_LIBPQ//postgresql+psycopg/postgresql}"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "[backup-postgres] ERROR: pg_dump not on PATH" >&2
  exit 1
fi

if ! command -v gzip >/dev/null 2>&1; then
  echo "[backup-postgres] ERROR: gzip not on PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE_NAME="archon-postgres-${TIMESTAMP}.dump"
OUT_DUMP="${BACKUP_DIR}/${BASE_NAME}.gz"
OUT_SHA="${OUT_DUMP}.sha256"

echo "[backup-postgres] target=${DB_URL_LIBPQ%@*}@<redacted>"
echo "[backup-postgres] output=${OUT_DUMP}"

# Use custom format (-Fc) — compressible, restorable via pg_restore.
# Pipe through gzip for additional compression / portability.
if ! pg_dump --format=custom --no-owner --no-privileges \
     "${DB_URL_LIBPQ}" | gzip -9 > "${OUT_DUMP}"; then
  echo "[backup-postgres] ERROR: pg_dump failed" >&2
  rm -f "${OUT_DUMP}"
  exit 2
fi

# SHA-256 checksum sidecar.
if command -v sha256sum >/dev/null 2>&1; then
  (cd "${BACKUP_DIR}" && sha256sum "${BASE_NAME}.gz" > "${BASE_NAME}.gz.sha256")
elif command -v shasum >/dev/null 2>&1; then
  (cd "${BACKUP_DIR}" && shasum -a 256 "${BASE_NAME}.gz" > "${BASE_NAME}.gz.sha256")
else
  echo "[backup-postgres] ERROR: no sha256sum/shasum available" >&2
  exit 3
fi

SIZE_BYTES="$(wc -c < "${OUT_DUMP}" | tr -d ' ')"
echo "[backup-postgres] size=${SIZE_BYTES} bytes"
echo "[backup-postgres] sha256=$(cut -d' ' -f1 < "${OUT_SHA}")"
echo "[backup-postgres] complete"
