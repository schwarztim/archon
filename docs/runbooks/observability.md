# Archon Observability Runbook

Operational guide for the Phase 5 observability stack: Grafana dashboards,
Prometheus alert rules, and the metric catalog that ties them to backend
emitters.

## 1. Stack Overview

| Component | Location | Purpose |
|-----------|----------|---------|
| Metrics emitter | `backend/app/middleware/metrics_middleware.py` | Renders the `/metrics` endpoint and exposes helper functions for orchestration / cost / provider events. |
| Metric catalog | `docs/metrics-catalog.md` | Source of truth for the metric contract. Every dashboard/alert metric must be listed here. |
| Dashboards | `infra/grafana/dashboards/archon-*.json` | Grafana 9+ schema. Loaded by sidecar via `grafana_dashboard` ConfigMap label. |
| Alert rules | `infra/monitoring/alerts/archon-orchestration.yaml` + `infra/monitoring/prometheus-values.yaml` | Loaded by `kube-prometheus-stack` via `additionalPrometheusRulesMap`. |
| Parity gate | `scripts/check-grafana-metric-parity.py` | CI gate (called by `scripts/verify-contracts.sh`) that fails on metric drift. |

## 2. Accessing Grafana

```bash
# In-cluster port-forward (assumes default release name).
kubectl -n archon-monitoring port-forward svc/archon-monitoring-grafana 3000:80
open http://localhost:3000
```

Default credentials are governed by the Helm release values; production
deployments should set `grafana.adminPassword` via secret. Default tags route
to the four Archon dashboards:

| Dashboard | UID | Tags |
|-----------|-----|------|
| Archon Orchestration | `archon-orchestration` | `archon`, `orchestration` |
| Archon Cost | `archon-cost` | `archon`, `cost` |
| Archon Providers | `archon-providers` | `archon`, `providers` |
| Archon Tenants | `archon-tenants` | `archon`, `tenants` |

The orchestration dashboard is the entry point — it links to the others.

## 3. Alert Catalog

Each alert below documents: meaning, severity, who is paged, and the response
playbook. All alerts emit `runbook_url` annotations pointing at this section.

### ArchonHighRunFailureRate

- **Meaning:** Tenant workflow failure rate > 10% over 10m.
- **Severity:** warning.
- **Who pages:** orchestration on-call (Slack).
- **Playbook:**
  1. Open the Orchestration dashboard, filter by the failing `tenant_id`.
  2. Check `Step Failures by Node Type` to localize the failure surface.
  3. Cross-reference `Cancellations by Reason` — a spike in
     `cost_gate_budget_exceeded` is not a backend bug.
  4. Pull recent run logs for the tenant: `kubectl logs -l app=archon-orchestrator | grep tenant_id=<id>`.

### ArchonCheckpointFailures

- **Meaning:** Postgres checkpointer has had at least one failure in the last 5m.
- **Severity:** **critical** — durability is at risk.
- **Who pages:** orchestration on-call + DBA.
- **Playbook:**
  1. Verify Postgres reachability: `kubectl exec -it deploy/archon-backend -- psql $DATABASE_URL -c "select 1"`.
  2. Check disk pressure on the Postgres node.
  3. If migrations are recent, roll back: `archonctl checkpoint rollback`.
  4. Until resolved, **disable autonomous workflow scheduling** to limit blast radius.

### ArchonProviderUnhealthy

- **Meaning:** > 50% of provider calls returning `status=error` for 5m.
- **Severity:** warning.
- **Who pages:** providers on-call.
- **Playbook:**
  1. Check the provider's status page.
  2. Open the Providers dashboard — is the same provider also seeing a timeout spike?
  3. If credentials may have rotated, refresh from Vault (`archonctl secrets refresh <provider>`).
  4. Confirm fallback policy is engaging via `Fallbacks` panel.

### ArchonHighFallbackRate

- **Meaning:** Provider fallbacks > 1/s for 10m.
- **Severity:** warning.
- **Who pages:** providers on-call (informational if expected during a known incident).
- **Playbook:**
  1. Identify the dominant `from_provider → to_provider` pair on the Providers dashboard.
  2. If the fallback target itself is degraded, fall back further or pause the affected tenants.
  3. Cost impact: fallbacks often route to more expensive models — sanity-check the Cost dashboard.

### ArchonRunCancellationsSpike

- **Meaning:** Cancellation rate for a single reason > 0.1/s for 5m.
- **Severity:** warning.
- **Who pages:** orchestration on-call.
- **Playbook:**
  1. Inspect `reason` label:
     - `cost_gate_budget_exceeded`: tenant blew budget — operations/finance call.
     - `deadline`: downstream slowness — check provider latency.
     - `user`: unusual user-facing cancellations — frontend incident?
  2. Check `Workflow Run Duration p99` — if it crossed the deadline, latency is the root cause.

### ArchonCostBudgetExceeded

- **Meaning:** Cost-gate is denying new runs because budget exhausted.
- **Severity:** warning.
- **Who pages:** finance + tenant success.
- **Playbook:**
  1. Confirm tenant budget on the Cost dashboard (Top 10 panel).
  2. Either raise the budget (after approval) or notify the tenant.
  3. Track recurrence — repeated busts indicate inadequate budgeting.

### ArchonStuckRunningRuns

- **Meaning:** Non-zero `archon_workflow_runs_in_progress` but zero terminal transitions in the last hour.
- **Severity:** warning.
- **Who pages:** orchestration on-call.
- **Playbook:**
  1. Confirm at least one active worker (Active Workers panel).
  2. Check for pending checkpointer failures (`ArchonCheckpointFailures`).
  3. Inspect orphan rows: `psql -c "select run_id, started_at from runs where status='running' and started_at < now() - interval '1 hour'"`.
  4. If safe, mark stuck runs as `cancelled` with reason `stuck_orphan`.

### ArchonTenantContextMissing

- **Meaning:** Requests reaching protected handlers without a tenant context.
- **Severity:** **critical** — multi-tenancy isolation risk.
- **Who pages:** security on-call + orchestration on-call.
- **Playbook:**
  1. Identify the offending `path` label.
  2. Treat as a P0 — assume cross-tenant data exposure until proven otherwise.
  3. Add the route to the explicit allowlist or require auth, then redeploy.
  4. Audit recent log lines for the path to determine blast radius.

### ArchonStepRetryStorm

- **Meaning:** Step retries > 1/s for 10m on a given `node_type`.
- **Severity:** warning.
- **Who pages:** orchestration on-call.
- **Playbook:**
  1. Identify the `node_type` and inspect step logs.
  2. If the failures are downstream-dependent (provider, database), correlate with the Providers dashboard.
  3. Consider tuning retry policy if the storm is benign churn.

### ArchonNoActiveWorkers

- **Meaning:** No workers have heartbeated in the last minute.
- **Severity:** **critical** — runs cannot progress.
- **Who pages:** orchestration on-call.
- **Playbook:**
  1. `kubectl get pods -n archon -l app=archon-worker` — are pods running?
  2. Check scheduler logs and recent Helm upgrades.
  3. Cordon impacted nodes if a node-level issue is suspected.
  4. Validate heartbeat emitter — `archon_worker_heartbeat_seconds` should update at the configured interval.

## 4. Common Queries

```promql
# Top 5 tenants by run failures over 24h
topk(5, sum by (tenant_id) (increase(archon_workflow_runs_total{status="failed"}[24h])))

# Median step duration by node_type
histogram_quantile(0.5,
  sum by (le, node_type) (rate(archon_step_duration_seconds_bucket[5m]))
)

# Spend per provider in the last 6h
sum by (provider) (increase(archon_cost_total[6h]))

# DLP findings, high severity, last 24h
sum by (tenant_id, pattern) (increase(archon_dlp_findings_total{severity="high"}[24h]))

# Tenant context-missing offenders by path
topk(10, sum by (path) (increase(archon_tenant_context_missing_total[24h])))
```

## 5. Adding a New Metric

The metrics catalog is the contract; the parity gate enforces it.

1. Add the metric definition to `docs/metrics-catalog.md` under the right section.
2. Coordinate with W5.1 to add the helper + `render_metrics()` block to
   `backend/app/middleware/metrics_middleware.py`.
3. Wire callsites at the appropriate orchestration boundary.
4. Add panels to the relevant dashboard or alert rules to the orchestration alerts file.
5. Run `python3 scripts/check-grafana-metric-parity.py` — must exit 0.
6. `bash scripts/verify-contracts.sh` runs the full contract gate including the parity check.

## 6. Drift Triage

When `check-grafana-metric-parity.py` reports DRIFT:

| DRIFT category | What to do |
|----------------|------------|
| **Dashboard references metric not in catalog** | Either add the metric to the catalog (if intentional) or fix the typo in the dashboard. |
| **Alert references metric not in catalog** | Same as above. |
| **Catalog metric not in emitter** (`--strict`) | Tracked under W5.1's TODO list — wire the emitter and re-run. |
| **Emitter metric unused (informational)** | Either add a panel/alert that uses it or remove the emitter to keep the surface area small. |

## 7. Out-of-Scope (Backend-Owned)

The Phase 5 squad does **not** modify backend source. If a metric needs to
be added or relabelled, file the request against W5.1 (`metrics_middleware.py`
owner). Do **not** reach into the backend; the parity check exists precisely
to expose drift early so it can be funneled to the right owner.
