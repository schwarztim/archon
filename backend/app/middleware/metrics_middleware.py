"""Prometheus metrics middleware for HTTP request tracking.

Collects request count and latency histogram data for all HTTP
requests, exposed via the /metrics endpoint in Prometheus format.

Additional helper functions provide metric emission for token usage,
cost, workflow runs, DLP findings, step durations, retries,
cancellations, provider latency / fallback, and checkpoint failures.

Emission helpers are NON-BLOCKING — every public ``record_*`` /
``observe_*`` function is wrapped in a try/except so a metric-system
failure cannot abort the calling code path (Phase 5 acceptance #3).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)


# Histogram bucket boundaries (seconds)
_HISTOGRAM_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0,
)

# Thread-safe counters  (single-process; fine for dev / per-pod metrics)
_request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
_duration_sums: dict[tuple[str, str], float] = defaultdict(float)
_duration_counts: dict[tuple[str, str], int] = defaultdict(int)
_duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)

# Gauges
_active_agents: int = 0
_vault_status: int = 0

# archon_token_usage_total{tenant_id, model, kind} — legacy 3-tuple store
_token_usage_counts: dict[tuple[str, str, str], int] = defaultdict(int)

# archon_token_usage_total canonical {tenant_id, provider, model, kind}
_token_usage_counts_canonical: dict[tuple[str, str, str, str], int] = defaultdict(int)

# archon_cost_total{tenant_id, model} — legacy 2-tuple store
_cost_totals: dict[tuple[str, str], float] = defaultdict(float)

# archon_cost_total canonical {tenant_id, provider, model}
_cost_totals_canonical: dict[tuple[str, str, str], float] = defaultdict(float)

# archon_workflow_runs_total{status, tenant_id} — legacy 2-tuple store
_workflow_run_counts: dict[tuple[str, str], int] = defaultdict(int)

# archon_workflow_runs_total canonical {tenant_id, kind, status}
_workflow_run_counts_canonical: dict[tuple[str, str, str], int] = defaultdict(int)

# archon_workflow_run_duration_seconds — legacy unlabeled histogram
_workflow_duration_sums: list[float] = [0.0]
_workflow_duration_counts: list[int] = [0]
_workflow_duration_buckets: dict[float, int] = defaultdict(int)

# archon_workflow_run_duration_seconds canonical {tenant_id, kind, status}
_workflow_duration_sums_canonical: dict[tuple[str, str, str], float] = defaultdict(float)
_workflow_duration_counts_canonical: dict[tuple[str, str, str], int] = defaultdict(int)
_workflow_duration_buckets_canonical: dict[
    tuple[str, str, str, float], int
] = defaultdict(int)

# archon_step_duration_seconds {tenant_id, node_type, status}
_step_duration_sums: dict[tuple[str, str, str], float] = defaultdict(float)
_step_duration_counts: dict[tuple[str, str, str], int] = defaultdict(int)
_step_duration_buckets: dict[tuple[str, str, str, float], int] = defaultdict(int)

# archon_step_retries_total {tenant_id, node_type}
_step_retries_counts: dict[tuple[str, str], int] = defaultdict(int)

# archon_run_cancellations_total {tenant_id, reason}
_run_cancellations_counts: dict[tuple[str, str], int] = defaultdict(int)

# archon_checkpoint_failures_total {env, reason}
_checkpoint_failures_counts: dict[tuple[str, str], int] = defaultdict(int)

# archon_provider_latency_seconds {provider, model, status}
_provider_latency_sums: dict[tuple[str, str, str], float] = defaultdict(float)
_provider_latency_counts: dict[tuple[str, str, str], int] = defaultdict(int)
_provider_latency_buckets: dict[
    tuple[str, str, str, float], int
] = defaultdict(int)

# archon_provider_fallback_total {from_provider, to_provider, reason}
_provider_fallback_counts: dict[tuple[str, str, str], int] = defaultdict(int)

# archon_dlp_findings_total{tenant_id, severity, pattern}
_dlp_finding_counts: dict[tuple[str, str, str], int] = defaultdict(int)


# ──────────────────────────────────────────────
# Label-bounding helpers (Phase 5 acceptance #2)
# ──────────────────────────────────────────────

# Allowed enums for status / kind / reason labels — anything else collapses
# to "other" so unbounded user input cannot blow up cardinality.
_ALLOWED_STATUS = frozenset(
    {"completed", "failed", "cancelled", "paused", "skipped", "retry", "running"}
)
_ALLOWED_KIND = frozenset({"workflow", "agent"})
_ALLOWED_TOKEN_KIND = frozenset({"prompt", "completion"})


def _bound(label: str | None, allowed: frozenset[str], default: str = "unknown") -> str:
    """Return *label* when present in *allowed*, else *default*.

    Prevents unbounded user-supplied values (free-form step IDs / run IDs)
    from inflating Prometheus cardinality. Empty / None → ``"unknown"``.
    """
    if not label:
        return default
    s = str(label)
    return s if s in allowed else default


def _safe_str(value: Any, default: str = "unknown") -> str:
    """Coerce *value* to a non-empty short string; ``default`` on miss."""
    if value is None:
        return default
    s = str(value)
    if not s:
        return default
    # Truncate to keep series cardinality bounded if a bug ever leaks an
    # unbounded value through (defence in depth).
    return s[:128]


def set_active_agents(count: int) -> None:
    """Set current active agent gauge value."""
    global _active_agents
    _active_agents = count


def set_vault_status(up: bool) -> None:
    """Set Vault connectivity gauge (1 = up, 0 = down)."""
    global _vault_status
    _vault_status = 1 if up else 0


def get_request_counts() -> dict[tuple[str, str, int], int]:
    """Return current request count snapshot."""
    return dict(_request_counts)


def get_duration_data() -> dict[str, Any]:
    """Return duration histogram data snapshot."""
    return {
        "sums": dict(_duration_sums),
        "counts": dict(_duration_counts),
        "buckets": dict(_duration_buckets),
    }


def get_active_agents() -> int:
    """Return active agents gauge."""
    return _active_agents


def get_vault_status() -> int:
    """Return vault status gauge."""
    return _vault_status


# ──────────────────────────────────────────────
# Metric emission helpers — backward compatible signatures
# ──────────────────────────────────────────────
#
# Every helper is wrapped in a try/except. A metric-system failure
# MUST NOT abort the calling code path (Phase 5 acceptance #3).


def record_token_usage(
    tenant_id: str,
    model: str,
    kind: str,
    count: int,
    *,
    provider: str = "unknown",
) -> None:
    """Increment ``archon_token_usage_total`` for the given labels.

    Args:
        tenant_id: Tenant identifier; ``"unknown"`` when absent.
        model: Model name (e.g. ``"gpt-4o"``).
        kind: ``"prompt"`` or ``"completion"`` — bounded.
        count: Number of tokens to add.
        provider: Upstream provider name (``openai``, ``anthropic``, …).
    """
    try:
        bounded_kind = _bound(kind, _ALLOWED_TOKEN_KIND)
        tid = _safe_str(tenant_id)
        mdl = _safe_str(model)
        prv = _safe_str(provider)
        # Legacy 3-tuple store (used by older tests / dashboards)
        _token_usage_counts[(tid, mdl, bounded_kind)] += count
        # Canonical 4-tuple store with provider label
        _token_usage_counts_canonical[(tid, prv, mdl, bounded_kind)] += count
    except Exception as exc:  # noqa: BLE001 — emission must never raise
        log.debug("record_token_usage failed: %s", exc)


def record_cost(
    tenant_id: str,
    model: str,
    amount_usd: float,
    *,
    provider: str = "unknown",
) -> None:
    """Increment ``archon_cost_total`` for the given labels.

    Args:
        tenant_id: Tenant identifier.
        model: Model name.
        amount_usd: Cost in USD to add.
        provider: Upstream provider name.
    """
    try:
        tid = _safe_str(tenant_id)
        mdl = _safe_str(model)
        prv = _safe_str(provider)
        _cost_totals[(tid, mdl)] += amount_usd
        _cost_totals_canonical[(tid, prv, mdl)] += amount_usd
    except Exception as exc:  # noqa: BLE001
        log.debug("record_cost failed: %s", exc)


def record_workflow_run(
    status: str,
    tenant_id: str,
    *,
    kind: str = "workflow",
) -> None:
    """Increment ``archon_workflow_runs_total`` for the given labels.

    Args:
        status: Run outcome — ``completed``, ``failed``, ``cancelled``.
        tenant_id: Tenant identifier.
        kind: Run kind from the WorkflowRun model — ``workflow`` / ``agent``.
    """
    try:
        bounded_status = _bound(status, _ALLOWED_STATUS)
        bounded_kind = _bound(kind, _ALLOWED_KIND, default="workflow")
        tid = _safe_str(tenant_id)
        _workflow_run_counts[(bounded_status, tid)] += 1
        _workflow_run_counts_canonical[(tid, bounded_kind, bounded_status)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_workflow_run failed: %s", exc)


def record_workflow_duration(
    seconds: float,
    *,
    tenant_id: str = "unknown",
    kind: str = "workflow",
    status: str = "completed",
) -> None:
    """Record a workflow run duration into the histogram.

    Legacy unlabeled histogram is preserved for backward compatibility;
    canonical labeled histogram is also written.
    """
    try:
        # Legacy unlabeled histogram
        _workflow_duration_sums[0] += seconds
        _workflow_duration_counts[0] += 1
        for bucket in _HISTOGRAM_BUCKETS:
            if seconds <= bucket:
                _workflow_duration_buckets[bucket] += 1

        # Canonical labeled histogram
        bounded_kind = _bound(kind, _ALLOWED_KIND, default="workflow")
        bounded_status = _bound(status, _ALLOWED_STATUS)
        tid = _safe_str(tenant_id)
        key = (tid, bounded_kind, bounded_status)
        _workflow_duration_sums_canonical[key] += seconds
        _workflow_duration_counts_canonical[key] += 1
        for bucket in _HISTOGRAM_BUCKETS:
            if seconds <= bucket:
                _workflow_duration_buckets_canonical[
                    (tid, bounded_kind, bounded_status, bucket)
                ] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_workflow_duration failed: %s", exc)


def record_step_duration(
    seconds: float,
    *,
    tenant_id: str = "unknown",
    node_type: str = "unknown",
    status: str = "completed",
) -> None:
    """Record ``archon_step_duration_seconds`` observation."""
    try:
        bounded_status = _bound(status, _ALLOWED_STATUS)
        tid = _safe_str(tenant_id)
        nt = _safe_str(node_type)
        key = (tid, nt, bounded_status)
        _step_duration_sums[key] += seconds
        _step_duration_counts[key] += 1
        for bucket in _HISTOGRAM_BUCKETS:
            if seconds <= bucket:
                _step_duration_buckets[(tid, nt, bounded_status, bucket)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_step_duration failed: %s", exc)


def record_step_retry(
    *,
    tenant_id: str = "unknown",
    node_type: str = "unknown",
) -> None:
    """Increment ``archon_step_retries_total{tenant_id, node_type}``."""
    try:
        tid = _safe_str(tenant_id)
        nt = _safe_str(node_type)
        _step_retries_counts[(tid, nt)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_step_retry failed: %s", exc)


def record_run_cancellation(
    *,
    tenant_id: str = "unknown",
    reason: str = "unknown",
) -> None:
    """Increment ``archon_run_cancellations_total{tenant_id, reason}``."""
    try:
        tid = _safe_str(tenant_id)
        # Reason is bounded by the dispatcher's known set; coerce free
        # text to a short label.
        rsn = _safe_str(reason)[:64]
        _run_cancellations_counts[(tid, rsn)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_run_cancellation failed: %s", exc)


def record_checkpoint_failure(
    *,
    env: str = "unknown",
    reason: str = "unknown",
) -> None:
    """Increment ``archon_checkpoint_failures_total{env, reason}``."""
    try:
        e = _safe_str(env)[:32]
        r = _safe_str(reason)[:64]
        _checkpoint_failures_counts[(e, r)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_checkpoint_failure failed: %s", exc)


def record_provider_latency(
    seconds: float,
    *,
    provider: str = "unknown",
    model: str = "unknown",
    status: str = "success",
) -> None:
    """Record ``archon_provider_latency_seconds`` observation."""
    try:
        prv = _safe_str(provider)
        mdl = _safe_str(model)
        # Provider call status is success | failure
        st = status if status in {"success", "failure"} else "unknown"
        key = (prv, mdl, st)
        _provider_latency_sums[key] += seconds
        _provider_latency_counts[key] += 1
        for bucket in _HISTOGRAM_BUCKETS:
            if seconds <= bucket:
                _provider_latency_buckets[(prv, mdl, st, bucket)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_provider_latency failed: %s", exc)


def record_provider_fallback(
    *,
    from_provider: str = "unknown",
    to_provider: str = "unknown",
    reason: str = "unknown",
) -> None:
    """Increment ``archon_provider_fallback_total`` for a fallback event."""
    try:
        fp = _safe_str(from_provider)
        tp = _safe_str(to_provider)
        rsn = _safe_str(reason)[:64]
        _provider_fallback_counts[(fp, tp, rsn)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_provider_fallback failed: %s", exc)


def record_dlp_finding(tenant_id: str, severity: str, pattern: str) -> None:
    """Increment ``archon_dlp_findings_total`` for the given labels.

    Preserved (W4 emitter). Wrapped in try/except.
    """
    try:
        tid = _safe_str(tenant_id)
        sev = _safe_str(severity)[:32]
        pat = _safe_str(pattern)[:64]
        _dlp_finding_counts[(tid, sev, pat)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_dlp_finding failed: %s", exc)


# ──────────────────────────────────────────────
# Snapshot getters
# ──────────────────────────────────────────────


def get_token_usage_counts() -> dict[tuple[str, str, str], int]:
    """Return current token usage snapshot (legacy 3-tuple keys)."""
    return dict(_token_usage_counts)


def get_token_usage_counts_canonical() -> dict[tuple[str, str, str, str], int]:
    """Return canonical 4-tuple {tenant_id, provider, model, kind} snapshot."""
    return dict(_token_usage_counts_canonical)


def get_cost_totals() -> dict[tuple[str, str], float]:
    """Return current cost totals snapshot (legacy 2-tuple)."""
    return dict(_cost_totals)


def get_cost_totals_canonical() -> dict[tuple[str, str, str], float]:
    """Return canonical {tenant_id, provider, model} cost snapshot."""
    return dict(_cost_totals_canonical)


def get_workflow_run_counts() -> dict[tuple[str, str], int]:
    """Return current workflow run count snapshot (legacy)."""
    return dict(_workflow_run_counts)


def get_workflow_run_counts_canonical() -> dict[tuple[str, str, str], int]:
    """Return canonical {tenant_id, kind, status} workflow run snapshot."""
    return dict(_workflow_run_counts_canonical)


def get_step_duration_counts() -> dict[tuple[str, str, str], int]:
    """Return per-key step duration sample counts."""
    return dict(_step_duration_counts)


def get_step_retries_counts() -> dict[tuple[str, str], int]:
    """Return ``archon_step_retries_total`` snapshot."""
    return dict(_step_retries_counts)


def get_run_cancellations_counts() -> dict[tuple[str, str], int]:
    """Return ``archon_run_cancellations_total`` snapshot."""
    return dict(_run_cancellations_counts)


def get_checkpoint_failures_counts() -> dict[tuple[str, str], int]:
    """Return ``archon_checkpoint_failures_total`` snapshot."""
    return dict(_checkpoint_failures_counts)


def get_provider_latency_counts() -> dict[tuple[str, str, str], int]:
    """Return per-key provider latency sample counts."""
    return dict(_provider_latency_counts)


def get_provider_fallback_counts() -> dict[tuple[str, str, str], int]:
    """Return ``archon_provider_fallback_total`` snapshot."""
    return dict(_provider_fallback_counts)


def get_dlp_finding_counts() -> dict[tuple[str, str, str], int]:
    """Return current DLP finding count snapshot."""
    return dict(_dlp_finding_counts)


def _normalise_path(path: str) -> str:
    """Collapse UUID / int path segments to reduce cardinality."""
    import re

    path = re.sub(
        r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "/{id}",
        path,
    )
    path = re.sub(r"/\d+", "/{id}", path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records per-request Prometheus metrics."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Record request count and latency for every HTTP request."""
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        path = _normalise_path(request.url.path)
        start = time.monotonic()

        response = await call_next(request)

        duration = time.monotonic() - start
        status = response.status_code

        _request_counts[(method, path, status)] += 1
        _duration_sums[(method, path)] += duration
        _duration_counts[(method, path)] += 1
        for bucket in _HISTOGRAM_BUCKETS:
            if duration <= bucket:
                _duration_buckets[(method, path, bucket)] += 1

        return response


def render_metrics() -> str:
    """Render all collected metrics in Prometheus exposition format."""
    lines: list[str] = []

    # archon_requests_total
    lines.append("# HELP archon_requests_total Total HTTP requests")
    lines.append("# TYPE archon_requests_total counter")
    for (method, path, status), count in sorted(_request_counts.items()):
        lines.append(
            f'archon_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
        )

    # archon_request_duration_seconds
    lines.append("# HELP archon_request_duration_seconds Request latency histogram")
    lines.append("# TYPE archon_request_duration_seconds histogram")
    for (method, path) in sorted(_duration_sums.keys()):
        for bucket in _HISTOGRAM_BUCKETS:
            val = _duration_buckets.get((method, path, bucket), 0)
            lines.append(
                f'archon_request_duration_seconds_bucket{{method="{method}",path="{path}",le="{bucket}"}} {val}'
            )
        lines.append(
            f'archon_request_duration_seconds_bucket{{method="{method}",path="{path}",le="+Inf"}} {_duration_counts[(method, path)]}'
        )
        lines.append(
            f'archon_request_duration_seconds_sum{{method="{method}",path="{path}"}} {_duration_sums[(method, path)]:.6f}'
        )
        lines.append(
            f'archon_request_duration_seconds_count{{method="{method}",path="{path}"}} {_duration_counts[(method, path)]}'
        )

    # archon_executions_total (placeholder – wired by execution service)
    lines.append("# HELP archon_executions_total Execution count by status")
    lines.append("# TYPE archon_executions_total counter")

    # archon_active_agents
    lines.append("# HELP archon_active_agents Current active agent count")
    lines.append("# TYPE archon_active_agents gauge")
    lines.append(f"archon_active_agents {_active_agents}")

    # archon_vault_status
    lines.append("# HELP archon_vault_status Vault connection status (1=up 0=down)")
    lines.append("# TYPE archon_vault_status gauge")
    lines.append(f"archon_vault_status {_vault_status}")

    # archon_token_usage_total — emit BOTH the legacy 3-label series and
    # the canonical 4-label series so older dashboards (and tests) keep
    # working while new dashboards can adopt the provider label.
    lines.append("# HELP archon_token_usage_total Total LLM tokens consumed")
    lines.append("# TYPE archon_token_usage_total counter")
    for (tenant_id, model, kind), count in sorted(_token_usage_counts.items()):
        lines.append(
            f'archon_token_usage_total{{tenant_id="{tenant_id}",'
            f'model="{model}",kind="{kind}"}} {count}'
        )
    for (tenant_id, provider, model, kind), count in sorted(
        _token_usage_counts_canonical.items()
    ):
        lines.append(
            f'archon_token_usage_total{{tenant_id="{tenant_id}",'
            f'provider="{provider}",model="{model}",kind="{kind}"}} {count}'
        )

    # archon_cost_total — emit BOTH legacy and canonical lines.
    lines.append("# HELP archon_cost_total Total LLM cost in USD")
    lines.append("# TYPE archon_cost_total counter")
    for (tenant_id, model), amount in sorted(_cost_totals.items()):
        lines.append(
            f'archon_cost_total{{tenant_id="{tenant_id}",model="{model}"}} {amount:.6f}'
        )
    for (tenant_id, provider, model), amount in sorted(
        _cost_totals_canonical.items()
    ):
        lines.append(
            f'archon_cost_total{{tenant_id="{tenant_id}",'
            f'provider="{provider}",model="{model}"}} {amount:.6f}'
        )

    # archon_workflow_runs_total — emit BOTH legacy and canonical lines
    # to preserve existing dashboard queries while supporting the new
    # {tenant_id, kind, status} contract.
    lines.append("# HELP archon_workflow_runs_total Workflow run count by tenant/kind/status")
    lines.append("# TYPE archon_workflow_runs_total counter")
    for (status, tenant_id), count in sorted(_workflow_run_counts.items()):
        lines.append(
            f'archon_workflow_runs_total{{status="{status}",tenant_id="{tenant_id}"}} {count}'
        )
    for (tenant_id, kind, status), count in sorted(
        _workflow_run_counts_canonical.items()
    ):
        lines.append(
            f'archon_workflow_runs_total{{tenant_id="{tenant_id}",'
            f'kind="{kind}",status="{status}"}} {count}'
        )

    # archon_workflow_run_duration_seconds — legacy unlabeled aggregate
    # plus canonical labeled histogram.
    lines.append("# HELP archon_workflow_run_duration_seconds Workflow run wall-clock duration")
    lines.append("# TYPE archon_workflow_run_duration_seconds histogram")
    for bucket in _HISTOGRAM_BUCKETS:
        val = _workflow_duration_buckets.get(bucket, 0)
        lines.append(
            f'archon_workflow_run_duration_seconds_bucket{{le="{bucket}"}} {val}'
        )
    lines.append(
        f'archon_workflow_run_duration_seconds_bucket{{le="+Inf"}} {_workflow_duration_counts[0]}'
    )
    lines.append(
        f'archon_workflow_run_duration_seconds_sum {_workflow_duration_sums[0]:.6f}'
    )
    lines.append(
        f'archon_workflow_run_duration_seconds_count {_workflow_duration_counts[0]}'
    )
    for key in sorted(_workflow_duration_counts_canonical.keys()):
        tenant_id, kind, status = key
        for bucket in _HISTOGRAM_BUCKETS:
            val = _workflow_duration_buckets_canonical.get(
                (tenant_id, kind, status, bucket), 0
            )
            lines.append(
                f'archon_workflow_run_duration_seconds_bucket{{tenant_id="{tenant_id}",'
                f'kind="{kind}",status="{status}",le="{bucket}"}} {val}'
            )
        lines.append(
            f'archon_workflow_run_duration_seconds_bucket{{tenant_id="{tenant_id}",'
            f'kind="{kind}",status="{status}",le="+Inf"}} '
            f'{_workflow_duration_counts_canonical[key]}'
        )
        lines.append(
            f'archon_workflow_run_duration_seconds_sum{{tenant_id="{tenant_id}",'
            f'kind="{kind}",status="{status}"}} '
            f'{_workflow_duration_sums_canonical[key]:.6f}'
        )
        lines.append(
            f'archon_workflow_run_duration_seconds_count{{tenant_id="{tenant_id}",'
            f'kind="{kind}",status="{status}"}} '
            f'{_workflow_duration_counts_canonical[key]}'
        )

    # archon_step_duration_seconds {tenant_id, node_type, status}
    lines.append("# HELP archon_step_duration_seconds Step execution duration")
    lines.append("# TYPE archon_step_duration_seconds histogram")
    for key in sorted(_step_duration_counts.keys()):
        tenant_id, node_type, status = key
        for bucket in _HISTOGRAM_BUCKETS:
            val = _step_duration_buckets.get(
                (tenant_id, node_type, status, bucket), 0
            )
            lines.append(
                f'archon_step_duration_seconds_bucket{{tenant_id="{tenant_id}",'
                f'node_type="{node_type}",status="{status}",le="{bucket}"}} {val}'
            )
        lines.append(
            f'archon_step_duration_seconds_bucket{{tenant_id="{tenant_id}",'
            f'node_type="{node_type}",status="{status}",le="+Inf"}} '
            f'{_step_duration_counts[key]}'
        )
        lines.append(
            f'archon_step_duration_seconds_sum{{tenant_id="{tenant_id}",'
            f'node_type="{node_type}",status="{status}"}} '
            f'{_step_duration_sums[key]:.6f}'
        )
        lines.append(
            f'archon_step_duration_seconds_count{{tenant_id="{tenant_id}",'
            f'node_type="{node_type}",status="{status}"}} '
            f'{_step_duration_counts[key]}'
        )

    # archon_step_retries_total {tenant_id, node_type}
    lines.append("# HELP archon_step_retries_total Step retry count")
    lines.append("# TYPE archon_step_retries_total counter")
    for (tenant_id, node_type), count in sorted(_step_retries_counts.items()):
        lines.append(
            f'archon_step_retries_total{{tenant_id="{tenant_id}",'
            f'node_type="{node_type}"}} {count}'
        )

    # archon_run_cancellations_total {tenant_id, reason}
    lines.append("# HELP archon_run_cancellations_total Run cancellation count")
    lines.append("# TYPE archon_run_cancellations_total counter")
    for (tenant_id, reason), count in sorted(_run_cancellations_counts.items()):
        lines.append(
            f'archon_run_cancellations_total{{tenant_id="{tenant_id}",'
            f'reason="{reason}"}} {count}'
        )

    # archon_checkpoint_failures_total {env, reason}
    lines.append("# HELP archon_checkpoint_failures_total LangGraph checkpointer failure count")
    lines.append("# TYPE archon_checkpoint_failures_total counter")
    for (env, reason), count in sorted(_checkpoint_failures_counts.items()):
        lines.append(
            f'archon_checkpoint_failures_total{{env="{env}",'
            f'reason="{reason}"}} {count}'
        )

    # archon_provider_latency_seconds {provider, model, status}
    lines.append("# HELP archon_provider_latency_seconds LLM provider call latency")
    lines.append("# TYPE archon_provider_latency_seconds histogram")
    for key in sorted(_provider_latency_counts.keys()):
        provider, model, status = key
        for bucket in _HISTOGRAM_BUCKETS:
            val = _provider_latency_buckets.get(
                (provider, model, status, bucket), 0
            )
            lines.append(
                f'archon_provider_latency_seconds_bucket{{provider="{provider}",'
                f'model="{model}",status="{status}",le="{bucket}"}} {val}'
            )
        lines.append(
            f'archon_provider_latency_seconds_bucket{{provider="{provider}",'
            f'model="{model}",status="{status}",le="+Inf"}} '
            f'{_provider_latency_counts[key]}'
        )
        lines.append(
            f'archon_provider_latency_seconds_sum{{provider="{provider}",'
            f'model="{model}",status="{status}"}} '
            f'{_provider_latency_sums[key]:.6f}'
        )
        lines.append(
            f'archon_provider_latency_seconds_count{{provider="{provider}",'
            f'model="{model}",status="{status}"}} '
            f'{_provider_latency_counts[key]}'
        )

    # archon_provider_fallback_total {from_provider, to_provider, reason}
    lines.append("# HELP archon_provider_fallback_total LLM provider fallback count")
    lines.append("# TYPE archon_provider_fallback_total counter")
    for (from_provider, to_provider, reason), count in sorted(
        _provider_fallback_counts.items()
    ):
        lines.append(
            f'archon_provider_fallback_total{{from_provider="{from_provider}",'
            f'to_provider="{to_provider}",reason="{reason}"}} {count}'
        )

    # archon_model_route_decision_total {tenant_id, reason} — written by
    # node_executors/llm.py via dynamic attribute on this module. Render
    # only when present.
    route_bucket = globals().get("_route_decision_counts")
    if route_bucket:
        lines.append("# HELP archon_model_route_decision_total Model routing decisions")
        lines.append("# TYPE archon_model_route_decision_total counter")
        for (tenant_id, reason), count in sorted(route_bucket.items()):
            lines.append(
                f'archon_model_route_decision_total{{tenant_id="{tenant_id}",'
                f'reason="{reason}"}} {count}'
            )

    # archon_dlp_findings_total
    lines.append("# HELP archon_dlp_findings_total DLP pattern match count by tenant/severity/pattern")
    lines.append("# TYPE archon_dlp_findings_total counter")
    for (tenant_id, severity, pattern), count in sorted(_dlp_finding_counts.items()):
        lines.append(
            f'archon_dlp_findings_total{{tenant_id="{tenant_id}",severity="{severity}",pattern="{pattern}"}} {count}'
        )

    return "\n".join(lines) + "\n"
