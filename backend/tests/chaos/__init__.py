"""Chaos / load / enterprise-policy test suite (W18a + W18b + W18c).

Tests in this package cover three failure-condition categories:

W18a — Lifecycle Crash/Restart Chaos
    - Worker crash mid-activity: task lease expiry allows reclaim by peer
    - Backend restart mid-run: DB-persisted state survives new session
    - Cancel race: exactly one terminal state (no double-execution)
    - Pause/Resume across restart
    - Terminate kills in-flight ActivityExecution rows

W18b — Queue/Schedule/Pipeline Storm Chaos
    - Queue backlog drains to 100% terminal state
    - Duplicate pipeline event storm: exactly 1 run (idempotency)
    - Schedule catchup after simulated downtime
    - Webhook burst: all events create runs, no duplicates per event_id
    - Overlap=skip under load: skip fires while previous run active

W18c — Enterprise Policy/Data Chaos
    - ARCHON_ENTERPRISE_MODE=true without policy: run denied
    - DLP blocks payload containing PII marker
    - Budget=0 blocks run
    - Vault unavailable fails closed (not silently continues)
    - Egress blocked by default in enterprise mode
    - DLP-flagged input: event history contains redacted version

All tests run against in-memory SQLite; external services are mocked.
Run with: bash scripts/run-chaos-tests.sh
"""
