#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Archon Postgres Restore
#
# Restores a backup produced by backup-postgres.sh, verifies the
# SHA-256 checksum, and (optionally) validates the schema via Alembic.
#
# Usage:
#   bash scripts/restore-postgres.sh <DUMP_FILE.gz> [--yes] [--skip-alembic] [--help]
#
# Environment:
#   DB_URL     Postgres connection URL
#              (default: postgresql://archon:archon@localhost:5432/archon)
#   ALEMBIC_BIN  Alembic binary path (default: 'alembic' on PATH)
#
# Exit codes:
#   0  success
#   1  bad arguments / tool unavailable
#   2  checksum mismatch
#   3  pg_restore failure
#   4  alembic validation failure
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: restore-postgres.sh <DUMP_FILE.gz> [--yes] [--skip-alembic]

Restores a pg_dump archive after verifying its sidecar SHA-256.

Arguments:
  DUMP_FILE.gz       Path to a *.dump.gz produced by backup-postgres.sh.
                     A *.sha256 sidecar must sit alongside it.

Options:
  --yes              Skip the destructive-action confirmation prompt.
  --skip-alembic     Do not run `alembic current` after restore.

Environment:
  DB_URL             Postgres URL (default: archon dev URL)
  ALEMBIC_BIN        Alembic binary (default: alembic)

Example:
  bash scripts/restore-postgres.sh ./backups/archon-postgres-20260101T000000Z.dump.gz --yes
EOF
}

DUMP_FILE=""
YES="0"
SKIP_ALEMBIC="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --yes) YES="1"; shift ;;
    --skip-alembic) SKIP_ALEMBIC="1"; shift ;;
    -*) echo "[restore-postgres] ERROR: unknown flag $1" >&2; exit 1 ;;
    *) DUMP_FILE="$1"; shift ;;
  esac
done

if [[ -z "${DUMP_FILE}" ]]; then
  usage
  exit 1
fi

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "[restore-postgres] ERROR: dump file not found: ${DUMP_FILE}" >&2
  exit 1
fi

SHA_FILE="${DUMP_FILE}.sha256"
if [[ ! -f "${SHA_FILE}" ]]; then
  echo "[restore-postgres] ERROR: checksum sidecar not found: ${SHA_FILE}" >&2
  exit 1
fi

DB_URL="${DB_URL:-postgresql://archon:archon@localhost:5432/archon}"
DB_URL_LIBPQ="${DB_URL//postgresql+asyncpg/postgresql}"
DB_URL_LIBPQ="${DB_URL_LIBPQ//postgresql+psycopg/postgresql}"

for tool in pg_restore gunzip; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "[restore-postgres] ERROR: $tool not on PATH" >&2
    exit 1
  fi
done

echo "[restore-postgres] verifying checksum: ${SHA_FILE}"
DUMP_DIR="$(dirname "${DUMP_FILE}")"
SHA_FILE_BASENAME="$(basename "${SHA_FILE}")"
if command -v sha256sum >/dev/null 2>&1; then
  if ! (cd "${DUMP_DIR}" && sha256sum -c "${SHA_FILE_BASENAME}"); then
    echo "[restore-postgres] ERROR: checksum mismatch" >&2
    exit 2
  fi
elif command -v shasum >/dev/null 2>&1; then
  if ! (cd "${DUMP_DIR}" && shasum -a 256 -c "${SHA_FILE_BASENAME}"); then
    echo "[restore-postgres] ERROR: checksum mismatch" >&2
    exit 2
  fi
else
  echo "[restore-postgres] ERROR: no sha256sum/shasum available" >&2
  exit 1
fi
echo "[restore-postgres] checksum OK"

if [[ "${YES}" != "1" ]]; then
  cat <<EOF >&2

  ╔══════════════════════════════════════════════════════════════╗
  ║  WARNING: pg_restore --clean --if-exists                     ║
  ║  All existing tables in the target DB will be DROPPED.       ║
  ║  Target: ${DB_URL_LIBPQ%@*}@<redacted>                       ║
  ╚══════════════════════════════════════════════════════════════╝

EOF
  read -rp "Type 'yes' to proceed: " confirm
  if [[ "${confirm}" != "yes" ]]; then
    echo "[restore-postgres] aborted" >&2
    exit 0
  fi
fi

echo "[restore-postgres] decompressing + restoring"
# Pipe gunzip → pg_restore. --clean --if-exists drops conflicting
# objects before recreating them; --no-owner / --no-privileges
# match the dump options.
if ! gunzip -c "${DUMP_FILE}" | pg_restore --clean --if-exists \
     --no-owner --no-privileges --dbname="${DB_URL_LIBPQ}"; then
  echo "[restore-postgres] ERROR: pg_restore failed" >&2
  exit 3
fi
echo "[restore-postgres] restore complete"

if [[ "${SKIP_ALEMBIC}" != "1" ]]; then
  ALEMBIC_BIN="${ALEMBIC_BIN:-alembic}"
  if command -v "${ALEMBIC_BIN}" >/dev/null 2>&1; then
    echo "[restore-postgres] running '${ALEMBIC_BIN} current' for schema validation"
    if ! "${ALEMBIC_BIN}" current 2>&1; then
      echo "[restore-postgres] WARNING: alembic current failed — schema may be drifted" >&2
      exit 4
    fi
    echo "[restore-postgres] schema validation OK"
  else
    echo "[restore-postgres] alembic not installed; skipping schema validation"
  fi
fi

echo "[restore-postgres] complete"
