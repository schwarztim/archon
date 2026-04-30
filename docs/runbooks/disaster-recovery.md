# Archon Disaster Recovery Runbook

End-to-end procedures for the most severe failure modes Archon can hit.
Every scenario lists RPO/RTO targets, the exact recovery commands, and
a communication template. Treat this as the operator playbook of last
resort — when the regular runbooks (`backup-restore.md`,
`observability.md`, `sso-integration.md`) are insufficient.

## 1. Scope & RTO/RPO Matrix

| # | Scenario                          | RPO       | RTO        | Decision authority |
|---|-----------------------------------|-----------|------------|--------------------|
| 1 | Single-AZ Postgres node loss      | 0         | 5 min      | On-call SRE        |
| 2 | Postgres logical corruption       | 1 hour    | 30 min     | On-call SRE        |
| 3 | Full Postgres loss (data + WAL)   | 24 hours  | 4 hours    | DR commander       |
| 4 | Vault leader loss                 | 0         | 5 min      | On-call SRE        |
| 5 | Vault unseal-key loss             | n/a       | n/a        | DR commander + CIO |
| 6 | Region outage (cloud provider)    | 1 hour    | 4 hours    | DR commander       |
| 7 | Ransomware / catastrophic compromise | 24 hours | 24 hours | DR commander + CIO + Legal |
| 8 | IdP outage (Keycloak / external)  | 0         | 30 min     | On-call SRE        |
| 9 | Backup integrity failure          | n/a       | n/a        | DR commander       |

"DR commander" = the on-call leader for the incident. They own external
comms and approve any destructive recovery action.

## 2. Pre-DR Readiness Checklist (run quarterly)

Before any DR scenario can be exercised, confirm:

- [ ] Most recent daily backup of Postgres is < 25 hours old.
- [ ] Most recent daily backup of Vault is < 25 hours old.
- [ ] `bash scripts/backup-restore-test.sh` was run in the last 30 days.
- [ ] Vault unseal shards are stored in two geographically distinct safes.
- [ ] `VAULT_BACKUP_KEY` exists in the offline KMS escrow.
- [ ] Off-site replica of `${BACKUP_DIR}` synced in the last 24 hours.
- [ ] DR runbook is reachable when production is fully down (printed copy / git mirror).

## 3. Scenario 1 — Single-AZ Postgres Node Loss

**Signals:** `pg_isready` failing on primary, replicas healthy.

**Recovery:**

1. Promote the synchronous replica:
   ```bash
   kubectl exec -n archon postgres-replica-0 -- pg_ctl promote
   ```
2. Update the backend connection URL via DNS or `Endpoints` patch.
3. Confirm: `psql "$ARCHON_DATABASE_URL" -c 'SELECT 1;'`.
4. Re-attach a new replica when the failed AZ recovers.

RPO: 0 (synchronous). RTO: 5 minutes.

## 4. Scenario 2 — Postgres Logical Corruption

**Signals:** Audit hash chain test fails (`test_audit_hash_chain.py`),
or a tenant reports missing rows.

**Recovery:**

1. Stop write traffic — scale `backend` and `worker` to 0 replicas.
2. Identify last good backup:
   ```bash
   ls -lh /var/backups/archon/archon-postgres-*.dump.gz | tail -5
   ```
3. Restore into a clean DB:
   ```bash
   bash scripts/restore-postgres.sh \
     /var/backups/archon/archon-postgres-<UTC>.dump.gz
   ```
4. Replay WAL to RPO target if needed.
5. Re-run validation (see `backup-restore.md` § Post-Restore Validation).
6. Resume write traffic incrementally (10% → 50% → 100%).

RPO: 1 hour. RTO: 30 minutes.

## 5. Scenario 3 — Full Postgres Loss (Data Volume + WAL)

**Signals:** Storage layer destroyed, no in-region replicas.

**Recovery:**

1. Provision a fresh Postgres cluster.
2. Pull latest off-site backup:
   ```bash
   aws s3 cp s3://archon-backups-offsite/postgres/latest.dump.gz \
     /tmp/restore.dump.gz
   aws s3 cp s3://archon-backups-offsite/postgres/latest.dump.gz.sha256 \
     /tmp/restore.dump.gz.sha256
   ```
3. Restore as in Scenario 2.
4. Run schema migration head check: `alembic current`.
5. Re-issue any per-tenant secrets that were rotated since the backup.

RPO: 24 hours. RTO: 4 hours.

## 6. Scenario 4 — Vault Leader Loss

**Signals:** `vault status` returns `standby` on all nodes; clients see
500s on writes.

**Recovery:**

1. Wait 60 seconds for Raft to elect a new leader.
2. If no election succeeds, manually promote a follower:
   ```bash
   vault operator raft list-peers
   vault operator step-down  # on the stuck leader
   ```
3. Confirm: `vault status` shows `active` on exactly one node.

RPO: 0. RTO: 5 minutes.

## 7. Scenario 5 — Vault Unseal-Key Loss

**Signals:** All unseal shards destroyed; the cluster is permanently
sealed.

**This is unrecoverable.** The data is encrypted at rest; the keys ARE
the only decryption authority. Treat the cluster as a total loss and:

1. Provision a new Vault cluster with fresh root tokens and shards.
2. Re-seed `secret/archon/*` from operator-held credentials. Most
   secrets must be rotated upstream (e.g. cloud provider API keys must
   be re-issued by the provider).
3. PKI roots must be regenerated; all issued certificates are now
   orphaned and must be re-issued.

RPO/RTO: not applicable — data is gone. Use this scenario as the
forcing function for the readiness checklist (§2).

## 8. Scenario 6 — Region Outage

**Signals:** Cloud provider status page red for the primary region;
multiple AZ failures simultaneously.

**Recovery:**

1. Activate the standby region. Backend container images are
   pre-staged; volumes are not.
2. Hydrate the standby Postgres from off-site backups (Scenario 3
   procedure, against the standby region's storage).
3. Hydrate the standby Vault from the encrypted snapshot. Have the
   unseal shard holders ready.
4. Update DNS to point the public hostname at the standby region's
   ingress.
5. Confirm at least one read traffic check succeeds; then enable
   writes.

RPO: 1 hour. RTO: 4 hours.

## 9. Scenario 7 — Ransomware / Catastrophic Compromise

**Signals:** Forensic indicators of unauthorized access; data integrity
in question; ransom demand.

**Decision:** DR commander, CIO, and Legal must approve the recovery
path. Engage incident response retainer before touching production.

**Recovery:**

1. Isolate: revoke all write tokens, set Postgres to read-only, set
   Vault to standby-only (no leader).
2. Snapshot current state for forensics — do NOT overwrite.
3. Rebuild from a backup that pre-dates the compromise window. Required:
   - Postgres backup older than the suspected first breach.
   - Vault backup older than the suspected first breach.
4. Rotate every secret currently held by the application:
   ```bash
   # Rotate every kv-v2 secret. Operator-supplied new values:
   for path in $(vault kv list -format=json secret/archon | jq -r '.[]'); do
     echo "Rotate secret/archon/${path}"
     # ... operator-driven, see sso-integration.md § rotation
   done
   ```
5. Rotate IdP client secrets (see `sso-integration.md` § 7.1).
6. Rotate Postgres role passwords; force-reset all user sessions.
7. Rotate any external API keys (OpenAI, Azure, etc.) the backup may
   have referenced.
8. Run a full audit hash chain validation: any chain break indicates
   the attacker tampered with audit data — escalate to Legal.
9. Communicate per the template in §12.

RPO: 24 hours. RTO: 24 hours. Realistically the long pole is rotation
of upstream provider credentials.

## 10. Scenario 8 — IdP Outage

**Signals:** Login fails for all users; `/auth/login` returns 5xx.

**Recovery:**

1. If the IdP is self-hosted Keycloak: check `keycloak` pod / container
   health, restart if needed.
2. If external (Okta, Azure AD): check the provider's status page.
3. Activate emergency local auth ONLY if approved by the DR commander:
   ```bash
   # Time-bounded — set the env var, restart, set a timer to revert.
   ARCHON_AUTH_DEV_MODE=true kubectl rollout restart deploy/backend
   ```
4. Once IdP recovers, immediately revert (`ARCHON_AUTH_DEV_MODE=false`).

RPO: 0 (no data loss). RTO: 30 minutes.

## 11. Scenario 9 — Backup Integrity Failure

**Signals:** `restore-postgres.sh` reports checksum mismatch, or the
round-trip test fails in production.

**Recovery:**

1. Try the off-site copy of the same backup.
2. If both copies fail: step back one day. Note the increased RPO.
3. Open an incident: backup pipeline integrity is broken regardless of
   whether you ultimately recovered.
4. Run `bash scripts/backup-restore-test.sh` against the current
   pipeline before declaring it healthy.

## 12. Communication Templates

### 12.1 Initial customer notice (incident in progress)

```
Subject: [Archon] Service Disruption — Investigating

We are currently investigating a service disruption affecting <SCOPE>.
Started: <UTC TIMESTAMP>
Impact: <USER-FACING SUMMARY>
We will post the next update by <UTC TIMESTAMP + 30 min>.
```

### 12.2 Mid-incident update

```
Subject: [Archon] Service Disruption — Update

Status: <INVESTIGATING | MITIGATING | RECOVERING>
Cause (preliminary): <ONE LINE>
Mitigation: <WHAT WE'RE DOING>
ETA to next update: <UTC TIMESTAMP>
```

### 12.3 Resolution notice

```
Subject: [Archon] Service Restored

Service restored as of <UTC TIMESTAMP>.
Total impact window: <DURATION>
Affected functionality: <SCOPE>
A full post-incident review will be published within 5 business days.
```

### 12.4 Data-impact notice (Scenario 7 only)

Always include Legal in the review chain. Template intentionally
omitted from this document — pull from the incident-response runbook
in the security repo.

## 13. Post-Incident Required Actions

After every Sev-1 / Sev-2:

- [ ] Write a post-mortem within 5 business days.
- [ ] File issues for every "we got lucky" finding.
- [ ] Update this runbook with any procedure deltas discovered.
- [ ] Schedule a tabletop exercise within 30 days for the same scenario.
- [ ] Rotate any credentials touched during the recovery.

## 14. Cross-Reference

- Backup mechanics: `backup-restore.md`
- IdP / SSO recovery details: `sso-integration.md`
- Runtime telemetry / dashboards: `observability.md`
