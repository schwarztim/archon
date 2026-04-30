# Archon Metrics Catalog

> **Canonical metric set** for the Archon orchestration platform. This catalog is the
> contract between the metric emitters in `backend/app/middleware/metrics_middleware.py`
> and Phase 5 dashboards / alert rules. Any PromQL query in a dashboard or alert MUST
> reference a metric registered here.
>
> **Drift detection:** `scripts/check-grafana-metric-parity.py` parses every dashboard
> JSON and every Prometheus alert rule, extracts the metric names from the expressions,
> and verifies each is listed in this catalog. Drift exits non-zero.
>
> **Owners:** W5.1 (emitters), Phase 5 Observability Squad (extension), Phase 5
> consumers (dashboards / alerts).
> **Last updated:** Phase 5 — canonical metric extension.

## Metric Naming Convention

- All Archon-emitted metrics are prefixed `archon_`.
- Counters end in `_total`.
- Histograms end in `_seconds` (and emit `_bucket`, `_sum`, `_count` series).
- Gauges have no suffix (e.g. `archon_active_agents`).
- Labels are `snake_case`; cardinality must stay bounded — paths are normalised by
  `_normalise_path()` (UUIDs and integer ids collapsed to `{id}`).
- Free-form user input (run IDs, step IDs) is **never** used as a label value.
- Status / kind / token-kind labels are bounded; unknown values collapse to
  `unknown` so cardinality stays predictable.
- Emission helpers are non-blocking: a metric-system failure cannot abort the
  caller's code path.

## HTTP Layer (`MetricsMiddleware`)

| Metric | Type | Labels | When emitted | Example query |
|--------|------|--------|--------------|---------------|
| `archon_requests_total` | counter | `method`, `path`, `status` | Each HTTP request (excluding `/metrics`). | `sum by (status) (rate(archon_requests_total[1m]))` |
| `archon_request_duration_seconds` | histogram | `method`, `path` | Each HTTP request — observes dispatch wall-clock. | `histogram_quantile(0.99, sum by (path, le) (rate(archon_request_duration_seconds_bucket[5m])))` |
| `archon_active_agents` | gauge | — | Set on agent pool size change. | `archon_active_agents` |
| `archon_vault_status` | gauge | — | Set on vault connectivity probes (1=up, 0=down). | `archon_vault_status` |
| `archon_executions_total` | counter | `status` | Placeholder; wired by execution service. | `rate(archon_executions_total[5m])` |

## Workflow Orchestration

Emitted from `backend/app/services/run_dispatcher.py` via the
`_emit_run_terminal_metrics`, `_emit_step_metrics`, and `_emit_step_retry`
helpers. All emissions are non-blocking.

| Metric | Type | Labels | When emitted | Example query |
|--------|------|--------|--------------|---------------|
| `archon_workflow_runs_total` | counter | `tenant_id`, `kind`, `status` (legacy 2-label `{status, tenant_id}` line also emitted) | At each terminal: `run.completed`, `run.failed`, `run.cancelled`, `run.paused`. Also on stub-blocked finalisation. `kind` ∈ {`workflow`, `agent`}; `status` bounded. | `sum by (status) (rate(archon_workflow_runs_total[5m]))` |
| `archon_workflow_run_duration_seconds` | histogram | `tenant_id`, `kind`, `status` (legacy unlabeled aggregate also emitted) | At each terminal finalisation, observing elapsed wall-clock. | `histogram_quantile(0.95, rate(archon_workflow_run_duration_seconds_bucket[5m]))` |
| `archon_step_duration_seconds` | histogram | `tenant_id`, `node_type`, `status` | After each step row is persisted. One observation per engine-emitted step. | `histogram_quantile(0.95, sum by (node_type, le) (rate(archon_step_duration_seconds_bucket[5m])))` |
| `archon_step_retries_total` | counter | `tenant_id`, `node_type` | When a step transitions to `retry` (engine-emitted) or the retry orchestrator schedules a Timer (`_maybe_schedule_retry`). | `sum by (node_type) (rate(archon_step_retries_total[5m]))` |
| `archon_run_cancellations_total` | counter | `tenant_id`, `reason` | Whenever a run finalises as cancelled (pre-claim cancel, signal-driven cancel, or in-flight cancel). `reason` is bounded (e.g. `cancel_requested`, `cancel_requested_before_claim`, `user_requested`). | `sum by (reason) (rate(archon_run_cancellations_total[1h]))` |

### Aspirational (not yet emitted)

| Metric | Type | Labels | Status |
|--------|------|--------|--------|
| `archon_worker_heartbeat_seconds` | gauge | `worker_id`, `pool` | Reserved for worker liveness; not yet wired. |
| `archon_workflow_runs_in_progress` | gauge | `tenant_id` | Reserved for live in-progress gauge; not yet wired. |

## Checkpoint Durability

| Metric | Type | Labels | When emitted | Example query |
|--------|------|--------|--------------|---------------|
| `archon_checkpoint_failures_total` | counter | `env`, `reason` | `app.langgraph.checkpointer.get_checkpointer` — when `_get_postgres_checkpointer` raises in a durable env (`production` / `staging`). `reason` ∈ {`import_error`, `connect_error`, `setup_error`}. | `sum by (reason) (rate(archon_checkpoint_failures_total[15m]))` |

## Cost & Token Layer

Emitted from `backend/app/langgraph/llm.py::call_llm_routed`. Every
emitter is non-blocking and skipped when the LLM is in stub mode.

| Metric | Type | Labels | When emitted | Example query |
|--------|------|--------|--------------|---------------|
| `archon_token_usage_total` | counter | `tenant_id`, `provider`, `model`, `kind` (legacy 3-label line also emitted) | After each successful `call_llm` return — separate observations for `prompt` and `completion` tokens. | `sum by (tenant_id, model) (rate(archon_token_usage_total[5m]))` |
| `archon_cost_total` | counter | `tenant_id`, `provider`, `model` (legacy 2-label line also emitted) | After each successful call when `LLMResponse.cost_usd` is populated. | `sum by (tenant_id) (increase(archon_cost_total[1h]))` |

### Aspirational (not yet emitted)

| Metric | Type | Labels | Status |
|--------|------|--------|--------|
| `archon_cost_gate_blocks_total` | counter | `tenant_id`, `reason` | Reserved for cost-gate denials (W4 budget service); not yet wired here. |

## Provider / Model Routing

| Metric | Type | Labels | When emitted | Example query |
|--------|------|--------|--------------|---------------|
| `archon_provider_latency_seconds` | histogram | `provider`, `model`, `status` (`success`/`failure`) | After each `call_llm` invocation in `call_llm_routed` — both success and failure paths. | `histogram_quantile(0.95, rate(archon_provider_latency_seconds_bucket{status="success"}[5m]))` |
| `archon_provider_fallback_total` | counter | `from_provider`, `to_provider`, `reason` | Whenever the fallback chain rolls forward (attempt index > 0). `reason` carries `decision.reason` (e.g. `fallback_after_openai_failed`). | `sum by (from_provider, reason) (rate(archon_provider_fallback_total[15m]))` |
| `archon_model_route_decision_total` | counter | `tenant_id`, `reason` | Routing decisions — emitted by `services/node_executors/llm.py::_record_route_metric`. | `sum by (reason) (rate(archon_model_route_decision_total[1h]))` |

## Tenant / Multi-Tenancy

| Metric | Type | Labels | When emitted |
|--------|------|--------|--------------|
| `archon_tenant_context_missing_total` | counter | `path` | (Aspirational) Requests reaching protected handlers without a tenant context. Not yet wired in this scope. |

## Security / Audit

| Metric | Type | Labels | When emitted |
|--------|------|--------|--------------|
| `archon_dlp_findings_total` | counter | `tenant_id`, `severity`, `pattern` | Each DLP pattern match — emitted by the DLP service. |
| `archon_blocked_requests_total` | counter | `reason` | (Aspirational) Requests blocked by security middleware. |
| `archon_audit_events_total` | counter | `action` | (Aspirational) Audit log emissions. |
| `archon_security_alerts` | gauge | — | (Aspirational) Currently active security alerts. |

## Helper API

`backend/app/metrics.py` exposes two facade helpers for callers that
prefer a generic interface:

```python
from app.metrics import inc_counter, observe_histogram

inc_counter(
    "archon_step_retries_total",
    labels={"tenant_id": tenant_id, "node_type": "llm"},
)

observe_histogram(
    "archon_provider_latency_seconds",
    labels={"provider": "openai", "model": "gpt-4o", "status": "success"},
    value=0.42,
)
```

The dispatch tables in `metrics.py` map metric names to the appropriate
middleware emitter. Unknown names log at DEBUG and are silently dropped
— never raised.

## Cardinality Safety

| Label | Source | Bound |
|---|---|---|
| `status` | Run / step status enum | `{completed, failed, cancelled, paused, skipped, retry, running}` — others coerced to `unknown` |
| `kind` (workflow) | `WorkflowRun.kind` | `{workflow, agent}` — others coerced to `workflow` |
| `kind` (token usage) | LLM helper | `{prompt, completion}` — others coerced to `unknown` |
| `tenant_id` | UUID string | Truncated to 128 chars; `unknown` when absent |
| `node_type` | Engine snapshot | Truncated to 128 chars; `unknown` when absent |
| `provider` / `model` | Router / LiteLLM | Truncated to 128 chars; `unknown` when absent |
| `reason` | Bounded enums per emitter | Truncated to 64 chars |
| `env` | `ARCHON_ENV` | Truncated to 32 chars |

Step IDs and run IDs are never used as label values.

## How to Add a Metric

1. Add the metric definition to this catalog under the appropriate section, with
   labels + when-emitted + an example query.
2. Add the storage dict and the helper function to
   `backend/app/middleware/metrics_middleware.py`. Wrap emission in
   `try/except Exception` so a metric-system failure cannot abort callers.
3. Bound any free-form label values via `_bound()` or `_safe_str()`.
4. Register the rendering block inside `render_metrics()` so the metric
   appears in `/metrics`.
5. Wire callsites at the lifecycle boundary. Prefer thin local helpers
   (e.g. `_emit_run_terminal_metrics`) so the calling module stays tidy.
6. Add a test in `backend/tests/test_metrics_canonical.py` verifying
   storage shape + non-blocking behaviour.
7. Reference the metric from a dashboard panel or alert rule.
8. Run `python3 scripts/check-grafana-metric-parity.py` — it must exit 0.

## Cross-References

- Emitter / storage: `backend/app/middleware/metrics_middleware.py`
- Helper facade: `backend/app/metrics.py`
- Workflow + step emission: `backend/app/services/run_dispatcher.py`
- LLM emission: `backend/app/langgraph/llm.py`
- Checkpoint emission: `backend/app/langgraph/checkpointer.py`
- Tests: `backend/tests/test_metrics_canonical.py`,
  `backend/tests/test_metrics_emission_dispatch.py`,
  `backend/tests/test_metrics_emission.py`
- Dashboards: `infra/grafana/dashboards/archon-*.json`
- Alert rules: `infra/monitoring/alerts/archon-orchestration.yaml` and
  `infra/monitoring/prometheus-values.yaml` (`additionalPrometheusRulesMap`).
- Parity check: `scripts/check-grafana-metric-parity.py`
- Runbook: `docs/runbooks/observability.md`
