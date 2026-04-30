# CI Gates Runbook

This runbook documents every Continuous Integration gate in the Archon repository, what each gate proves, how to run it locally, and how to remediate failures. It also defines the **severity policy** that governs the security-scan gate.

The goal is "enterprise proof": every gate produces a binary pass/fail with documented remediation, no advisory `|| true` swallowing, and explicit exception handling.

---

## Gate Overview

| Gate | Workflow / Job | What it proves | Blocker severity | Owner |
|------|----------------|----------------|------------------|-------|
| Lint | `ci.yml` -> `lint` | Backend + gateway Python source passes `ruff check`. | High — blocks all downstream gates. | Backend team |
| Feature matrix validation | `ci.yml` -> `feature-matrix-validate` | `docs/feature-matrix.yaml` is internally consistent with backend wiring. | High — release blocker. | Platform team |
| Verify unit | `ci.yml` -> `verify-unit` | Backend + gateway unit tests pass without live infra. | High. | Backend team |
| Verify integration | `ci.yml` -> `verify-integration` | Integration suite (`tests/integration/`) passes against real Postgres + Redis. **Includes Postgres-only RLS tests** (no longer skipped — `ARCHON_TEST_POSTGRES_URL` is set in CI). | Critical — multi-tenant isolation regressions are P0. | Backend team |
| Verify frontend | `ci.yml` -> `verify-frontend` | Frontend typecheck + Vitest unit tests pass. | High. | Frontend team |
| Verify contracts | `ci.yml` -> `verify-contracts` | OpenAPI schemas match backend, API type parity holds. | High. | Platform team |
| Verify slice | `ci.yml` -> `verify-slice` | Vertical-slice REST heartbeat passes against real infra. | High. | Platform team |
| Build | `ci.yml` -> `build` | All three Dockerfiles build without errors. Depends on every verify gate AND `security-scan`. | Critical — gate to merge. | Platform team |
| Security scan | `ci.yml` -> `security-scan` | Backend + gateway requirements have **no severity-`high` or above** vulnerabilities outside the allowlist. | High — see severity policy below. | Security team |
| Helm smoke | `helm-smoke.yml` -> `helm-smoke` | Helm chart lints clean, renders to non-empty manifests for dev + production overlays, rendered YAML parses, and `kubectl --dry-run=client` accepts the manifests. | High — release blocker for infra changes. | Platform team |

---

## Gate-by-Gate Detail

### 1. Lint

- **Proves:** Static checks via `ruff check backend/` and `ruff check gateway/`.
- **Run locally:** `make lint`
- **On failure:** Read ruff's output, fix the offense (or extend `pyproject.toml` ruff config if the rule is genuinely wrong for the project — requires review).

### 2. Feature matrix validation

- **Proves:** `docs/feature-matrix.yaml` matches the actual feature wiring in code.
- **Run locally:** `python3 scripts/check-feature-matrix.py`
- **On failure:** Either update the feature matrix to match the code (preferred) or fix the code to match the documented contract.

### 3. Verify unit

- **Proves:** Pure unit tests pass (no Postgres, no Redis, no live LLM).
- **Run locally:** `make verify-unit`
- **On failure:** Reproduce locally; fix code or test. **Do not modify the test to make it pass** without a corresponding code fix (root-cause rule).

### 4. Verify integration (Postgres mandatory)

- **Proves:** Integration tests pass with real Postgres + Redis containers. Includes RLS tests that exercise Postgres `ALTER ... ENABLE ROW LEVEL SECURITY` policies. **These tests previously skipped without `ARCHON_TEST_POSTGRES_URL`; CI now sets the env var so they always run.**
- **Run locally:**
  ```bash
  make dev   # start postgres + redis
  ARCHON_TEST_POSTGRES_URL=postgresql+asyncpg://archon:archon@localhost:5432/archon \
    bash scripts/verify-integration.sh
  ```
- **On failure (RLS-specific):** Inspect `backend/tests/test_multi_tenant/test_tenant_isolation.py` failures carefully — RLS regressions mean tenants can see other tenants' rows. **This is a P0 incident.** File an issue, do not paper over with `pytest.mark.skip`.

### 5. Verify frontend

- **Proves:** Frontend typecheck + Vitest unit tests pass.
- **Run locally:** `make verify-frontend`
- **On failure:** Fix the type or test. Frontend is owned by the frontend agent in this wave; read `docs/runbooks/` for context.

### 6. Verify contracts

- **Proves:** OpenAPI exposed by the backend matches the type definitions consumed by the frontend; feature matrix references resolve.
- **Run locally:** `make verify-contracts`
- **On failure:** Regenerate types, update OpenAPI spec, or fix the drift in code.

### 7. Verify slice

- **Proves:** End-to-end vertical slice (REST -> dispatch -> worker -> result) succeeds against real Postgres + Redis. CI runs with `ARCHON_DISPATCH_INLINE=1` so the slice is awaitable.
- **Run locally:** `make slice-up && make verify-slice`
- **On failure:** This is the canary for full-stack regressions. Inspect the failing step in slice logs.

### 8. Build

- **Proves:** All three production Dockerfiles (backend, frontend, gateway) build without errors. Gates merge.
- **Run locally:** `docker build -t archon-backend:ci ./backend` (and equivalent for frontend, gateway).
- **On failure:** Most often a missing dependency or a stale base image. Reproduce locally with `--no-cache`.

### 9. Security scan

- **Proves:** Backend + gateway dependency manifests have no vulnerabilities at or above the configured severity threshold (currently `high`) that are not explicitly allowlisted.
- **Run locally:** `make security-scan` or `bash scripts/security-scan.sh --threshold high`
- **On failure:** See the **Severity policy** section below.

### 10. Helm smoke

- **Proves:**
  1. `helm lint` passes for default values and the production overlay.
  2. `helm template` renders both overlays to non-empty manifest sets.
  3. The rendered YAML parses cleanly through PyYAML.
  4. `kubectl apply --dry-run=client` accepts the production manifests.
- **Run locally:** `make helm-smoke` (requires `helm` and `kubectl` on PATH).
- **On failure:**
  - **Lint failure:** Run `helm lint infra/helm/archon -f infra/helm/archon/values-production.yaml` and fix the reported issue.
  - **Render empty:** A `{{- if }}` block likely excludes everything. Check `templates/_helpers.tpl` and overlay defaults.
  - **YAML parse failure:** A template emits malformed YAML — usually whitespace or unquoted strings.
  - **kubectl dry-run failure:** A manifest violates a built-in Kubernetes schema. Read kubectl's error message; the offending resource and field are named.

---

## Severity Policy (security-scan)

The security-scan gate enforces a deterministic severity threshold.

### Threshold tiers

| Severity | CI behavior | Notes |
|----------|-------------|-------|
| `critical` | **Blocks CI.** Findings must be remediated or allowlisted with First Law-grade rationale. | No exceptions without operator review. |
| `high` | **Blocks CI** at the default threshold. | Default policy: at-or-above `high` blocks. |
| `medium` | Reported but not gating. | Surface in scan output for operator awareness. |
| `low` | Reported but not gating. | Logged in scan output. |

### Configuring threshold

The default is `high`. The threshold is set per-job in `ci.yml`:

```yaml
- name: Run security scan with severity threshold
  run: bash scripts/security-scan.sh --threshold high
```

To tighten to `critical` only (less aggressive), pass `--threshold critical`. To loosen to any finding, pass `--threshold low`. **Loosening below `high` requires a recorded rationale in the operator's session log.**

### Allowlist policy

Vulnerabilities that cannot be remediated immediately (upstream patch unavailable, transitive dependency, false positive) may be allowlisted in `.github/security-allowlist.json`.

**Required fields per entry:**

```json
{
  "cve_ids": ["CVE-2024-12345"],
  "rationale": {
    "CVE-2024-12345": {
      "rationale": "False positive — affected code path is not reachable. Confirmed via grep of <module>.<func>.",
      "review_date": "2026-04-29",
      "next_review_due": "2026-07-28",
      "owner": "@security-team"
    }
  }
}
```

**Re-review cadence:** every **90 days**. The allowlist owner must:

1. Re-read the rationale.
2. Confirm upstream still has no patch (or verify the false-positive analysis still holds).
3. Update `review_date` and `next_review_due`.
4. Remove the entry if the underlying vulnerability has been remediated upstream.

**Audit hook:** an entry whose `next_review_due` is in the past should be flagged by a future automated audit (out of scope for this runbook). Until that exists, the security team is responsible for manual re-review.

### Adding to the allowlist

1. Run `make security-scan` locally — it prints the offending CVE/vulnerability IDs.
2. Open `.github/security-allowlist.json`.
3. Add the ID to `cve_ids` and add a rationale block.
4. Commit with a message like `security: allowlist CVE-2024-12345 — rationale: ...`.
5. The next CI run will pass; the rationale is now in version control history.

### Removing from the allowlist

When the upstream is patched:

1. Bump the offending dependency in `requirements.txt`.
2. Remove the CVE entry from `.github/security-allowlist.json`.
3. Re-run `make security-scan` locally — confirm the finding is gone.
4. Commit both changes together so the allowlist removal is paired with the actual remediation.

---

## Local development

The `make` targets mirror CI exactly. Running each target locally before pushing is the fastest way to avoid CI cycles.

```
make lint              # Gate 1
make verify-unit       # Gate 3
make verify-integration  # Gate 4 (requires postgres + redis via `make dev`)
make verify-frontend   # Gate 5
make verify-contracts  # Gate 6
make verify-slice      # Gate 7 (requires postgres + redis via `make slice-up`)
make security-scan     # Gate 9
make helm-smoke        # Gate 10 (requires helm + kubectl)
```

---

## What changed in P2

P2 (enterprise proof hardening) replaced three soft / advisory gates with hard gates:

1. **`safety check ... || true` is gone.** The security-scan job now uses `scripts/security-scan.sh` with severity gating + an explicit allowlist.
2. **Postgres is mandatory in `verify-integration`.** `ARCHON_TEST_POSTGRES_URL` is set in CI so RLS tests run instead of being skipped. RLS regressions are now caught in PR review.
3. **Helm chart has deploy proof.** `helm-smoke.yml` runs lint + template + YAML parse + kubectl dry-run on every chart change and nightly. Rendered manifests are uploaded as build artifacts for inspection.
