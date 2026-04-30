"""Prometheus-compatible metrics endpoint and shared emission helpers.

Exposes ``/metrics`` in Prometheus exposition format with request counts,
latency histograms, active agent gauges, and Vault status.

Phase 5 also routes the canonical metric helpers — ``inc_counter`` and
``observe_histogram`` — through this module so callers don't have to
import middleware internals. All emission goes through
``app.middleware.metrics_middleware``; this module is a thin facade.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.middleware import metrics_middleware as _mm
from app.middleware.metrics_middleware import render_metrics

log = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])

# Legacy counters kept for backward compatibility
_counters: dict[str, int] = {"requests_total": 0, "errors_total": 0}


def inc(name: str, amount: int = 1) -> None:
    """Increment a counter by *amount*."""
    _counters[name] = _counters.get(name, 0) + amount


# ──────────────────────────────────────────────
# Generic emitters — Phase 5 helper API
# ──────────────────────────────────────────────


_COUNTER_DISPATCH: dict[str, Any] = {
    "archon_workflow_runs_total": _mm.record_workflow_run,
    "archon_step_retries_total": _mm.record_step_retry,
    "archon_run_cancellations_total": _mm.record_run_cancellation,
    "archon_checkpoint_failures_total": _mm.record_checkpoint_failure,
    "archon_provider_fallback_total": _mm.record_provider_fallback,
    "archon_token_usage_total": _mm.record_token_usage,
    "archon_dlp_findings_total": _mm.record_dlp_finding,
}


_HISTOGRAM_DISPATCH: dict[str, Any] = {
    "archon_workflow_run_duration_seconds": _mm.record_workflow_duration,
    "archon_step_duration_seconds": _mm.record_step_duration,
    "archon_provider_latency_seconds": _mm.record_provider_latency,
}


def inc_counter(
    name: str,
    labels: dict[str, str] | None = None,
    value: int | float = 1,
) -> None:
    """Increment a named counter by ``value``, dispatching to the right
    middleware helper.

    Emission is non-blocking — any failure is logged at DEBUG and
    swallowed so a metric system fault cannot abort the caller.

    Unknown counter names are logged but do not raise.
    """
    try:
        labels = labels or {}
        handler = _COUNTER_DISPATCH.get(name)
        if handler is None:
            log.debug("inc_counter: unknown counter name %r", name)
            return

        if name == "archon_workflow_runs_total":
            handler(
                labels.get("status", "unknown"),
                labels.get("tenant_id", "unknown"),
                kind=labels.get("kind", "workflow"),
            )
        elif name == "archon_step_retries_total":
            handler(
                tenant_id=labels.get("tenant_id", "unknown"),
                node_type=labels.get("node_type", "unknown"),
            )
        elif name == "archon_run_cancellations_total":
            handler(
                tenant_id=labels.get("tenant_id", "unknown"),
                reason=labels.get("reason", "unknown"),
            )
        elif name == "archon_checkpoint_failures_total":
            handler(
                env=labels.get("env", "unknown"),
                reason=labels.get("reason", "unknown"),
            )
        elif name == "archon_provider_fallback_total":
            handler(
                from_provider=labels.get("from_provider", "unknown"),
                to_provider=labels.get("to_provider", "unknown"),
                reason=labels.get("reason", "unknown"),
            )
        elif name == "archon_token_usage_total":
            handler(
                labels.get("tenant_id", "unknown"),
                labels.get("model", "unknown"),
                labels.get("kind", "prompt"),
                int(value),
                provider=labels.get("provider", "unknown"),
            )
        elif name == "archon_dlp_findings_total":
            handler(
                labels.get("tenant_id", "unknown"),
                labels.get("severity", "unknown"),
                labels.get("pattern", "unknown"),
            )
    except Exception as exc:  # noqa: BLE001 — never re-raise from emission
        log.debug("inc_counter %s failed: %s", name, exc)


def observe_histogram(
    name: str,
    labels: dict[str, str] | None,
    value: float,
) -> None:
    """Observe a value into a named histogram.

    Non-blocking: any failure is logged at DEBUG. Unknown names are a
    no-op.
    """
    try:
        labels = labels or {}
        handler = _HISTOGRAM_DISPATCH.get(name)
        if handler is None:
            log.debug("observe_histogram: unknown histogram name %r", name)
            return

        if name == "archon_workflow_run_duration_seconds":
            handler(
                value,
                tenant_id=labels.get("tenant_id", "unknown"),
                kind=labels.get("kind", "workflow"),
                status=labels.get("status", "completed"),
            )
        elif name == "archon_step_duration_seconds":
            handler(
                value,
                tenant_id=labels.get("tenant_id", "unknown"),
                node_type=labels.get("node_type", "unknown"),
                status=labels.get("status", "completed"),
            )
        elif name == "archon_provider_latency_seconds":
            handler(
                value,
                provider=labels.get("provider", "unknown"),
                model=labels.get("model", "unknown"),
                status=labels.get("status", "success"),
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("observe_histogram %s failed: %s", name, exc)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Return Prometheus-format metrics."""
    return render_metrics()
