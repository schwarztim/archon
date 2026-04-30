# Archon Backup & Restore Runbook

Operational guide for backing up and restoring Archon's two stateful
data stores: Postgres (workflow, agent, audit, billing data) and Vault
(secrets, KV-v2 entries, PKI material).

## 1. Scope

| Store    | What it holds                                           | Backup tool                        |
|----------|---------------------------------------------------------|------------------------------------|
| Postgres | Tenants, agents, executions, audit hash chain, budgets  | `scripts/backup-postgres.sh`       |
| Vault    | Secrets at `secret/archon/*`, PKI roots, dynamic creds  | `scripts/backup-vault.sh`          |
| Redis    | Ephemeral queue/cache state — NOT backed up by design   | n/a (tolerates loss)               |

All backup artifacts are written to `${BACKUP_DIR}` (default `./backups`)
with UTC timestamps in their filenames and SHA-256 sidecars.

## 2. Backup Schedule (Recommended)

| Cadence      | What runs                                               | Retention         |
|--------------|---------------------------------------------------------|-------------------|
| Hourly       | Postgres WAL archive (continuous, see §6)               | 24 hours          |
| Daily 02:00Z | Full `pg_dump` via `backup-postgres.sh`                 | 30 days           |
| Daily 02:15Z | Vault Raft snapshot via `backup-vault.sh`               | 30 days           |
| Weekly       | Off-site replication of yesterday's full backups        | 1 year            |
| Monthly      | Restore round-trip drill via `backup-restore-test.sh`   | n/a (audit log)   |

Run the daily jobs from a dedicated backup host or Kubernetes CronJob;
do NOT run them from inside the application pods.

## 3. Backup Procedure

### 3.1 Postgres (full)

```bash
BACKUP_DIR=/var/backups/archon \
DB_URL="$ARCHON_DATABASE_URL" \
bash scripts/backup-postgres.sh
```

Artifacts:

- `archon-postgres-<UTC>.dump.gz` — gzip-wrapped `pg_dump --format=custom`
- `archon-postgres-<UTC>.dump.gz.sha256` — checksum

The script uses `--no-owner --no-privileges` so the dump is portable
across DB roles. It does NOT capture role/grant state — that is managed
in Alembic migrations.

### 3.2 Vault (Raft)

```bash
BACKUP_DIR=/var/backups/archon \
VAULT_ADDR=https://vault.archon.example \
VAULT_TOKEN=$VAULT_BACKUP_TOKEN \
VAULT_BACKUP_KEY=$BACKUP_AES_PASSPHRASE \
bash scripts/backup-vault.sh
```

Artifacts:

- `archon-vault-<UTC>.snap.enc` — AES-256-CBC encrypted Raft snapshot
- `archon-vault-<UTC>.snap.enc.sha256` — checksum

The encryption key MUST be stored separately from the backup (different
KMS, different region). Losing it means losing the backup.

### 3.3 Vault (KV-only fallback)

For dev-mode Vault (no Raft backend) or when you only need the
KV entries:

```bash
BACKUP_DIR=./backups \
VAULT_ADDR=http://127.0.0.1:8200 \
VAULT_TOKEN=$VAULT_TOKEN \
bash scripts/backup-vault.sh --kv-only --no-encrypt
```

This is the mode used by the round-trip test.

## 4. Restore Procedure

### 4.1 Postgres

```bash
DB_URL="$ARCHON_DATABASE_URL" \
bash scripts/restore-postgres.sh \
  /var/backups/archon/archon-postgres-20260101T020000Z.dump.gz
```

Steps the script performs:

1. Verify SHA-256 of the dump file.
2. Prompt for confirmation (or `--yes` to skip).
3. `pg_restore --clean --if-exists` against the target DB.
4. Run `alembic current` to validate the schema head (skip with
   `--skip-alembic`).

### 4.2 Vault (Raft)

```bash
VAULT_ADDR=https://vault.archon.example \
VAULT_TOKEN=$VAULT_RECOVERY_TOKEN \
VAULT_BACKUP_KEY=$BACKUP_AES_PASSPHRASE \
bash scripts/restore-vault.sh \
  /var/backups/archon/archon-vault-20260101T021500Z.snap.enc
```

The restored cluster is sealed and must be unsealed with the operator
shards (kept off-line per Vault best practice).

### 4.3 Vault (KV-only)

```bash
VAULT_ADDR=http://127.0.0.1:8200 \
VAULT_TOKEN=$VAULT_TOKEN \
bash scripts/restore-vault.sh \
  ./backups/archon-vault-20260101T021500Z.snap --kv-only
```

## 5. Post-Restore Validation

After every restore, run all of:

| Check | Command | Pass criteria |
|-------|---------|---------------|
| Schema head | `alembic current` | matches the head from `backend/alembic/versions/` |
| Hash chain  | `pytest backend/tests/test_audit_hash_chain.py` | all chain checks pass |
| Smoke flow  | `bash scripts/smoke_test.sh` | exits 0 |
| Vault read  | `vault kv get secret/archon/jwt` | returns expected fields |
| Round-trip | `bash scripts/backup-restore-test.sh` | exits 0 |

If the audit hash chain test fails, the restore must be rejected — the
chain is non-repudiable and a break indicates either the backup was
tampered with or the restore was incomplete.

## 6. RTO / RPO Targets

| Scenario                              | RTO target  | RPO target  |
|---------------------------------------|-------------|-------------|
| Logical Postgres corruption           | 30 minutes  | ≤ 1 hour    |
| Postgres node loss (replica failover) | 5 minutes   | 0 (sync)    |
| Vault leader loss                     | 5 minutes   | 0 (Raft)    |
| Region outage                         | 4 hours     | 1 hour      |
| Ransomware / catastrophic compromise  | 24 hours    | 24 hours    |

To meet `RPO ≤ 1h` for Postgres, configure WAL archiving:

```ini
# postgresql.conf on the primary
wal_level = replica
archive_mode = on
archive_command = 'aws s3 cp %p s3://archon-wal/%f'
archive_timeout = 300   # ship WAL every 5 min
```

## 7. Common Failure Modes

| Symptom | Cause | Remediation |
|---------|-------|-------------|
| `pg_dump: server version mismatch` | Tooling older than DB | Install `pg_dump` matching the server major. The script does not pin a version; the operator's environment must align. |
| `checksum mismatch` on restore | Disk-level rot or transport corruption | Re-fetch from off-site copy; if both copies are bad, use the prior daily backup. |
| `pg_restore` errors on `CREATE EXTENSION` | Missing extension in target | Pre-install extensions (e.g. `pgcrypto`, `uuid-ossp`) before restoring. |
| Vault snapshot fails with `not enabled` | KV-v2 mount path differs from `secret/` | Override `VAULT_KV_PREFIX` and re-run with `--kv-only`. |
| Vault snapshot restore: `version mismatch` | Snapshot from different Vault major | Restore into a matching version; Raft snapshots are not forward-compatible. |
| Decryption failure | Wrong `VAULT_BACKUP_KEY` | The key is unrecoverable. Try alternate keys; if exhausted, the backup is lost. |
| Test script "skipped" | Missing docker / pg_dump / vault | Install missing tooling. The skip is intentional in CI without those binaries. |

## 8. Operational Notes

- **Never commit** backup artifacts. `.gitignore` must include `backups/`.
- **Off-site copies** must be encrypted in transit (S3/GCS server-side
  encryption is necessary but not sufficient — also wrap with the
  `VAULT_BACKUP_KEY`-style passphrase before upload).
- **Test the round-trip** on a regular cadence. A backup that has never
  been restored is an aspiration, not a backup.
- **Audit access** to backup buckets/volumes — restore credentials are
  effectively root over Postgres + Vault state.
- **WAL archiving** is operator-provisioned (Postgres config); these
  scripts handle full dumps only.

## 9. Cross-Reference

- Disaster scenarios beyond single-store loss: `disaster-recovery.md`.
- SSO/IdP rebuild after a Vault restore: `sso-integration.md`.
- Daily ops dashboards / alerts: `observability.md`.
