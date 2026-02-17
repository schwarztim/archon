"""Prometheus-compatible metrics endpoint.

Exposes /metrics in Prometheus exposition format with request counts,
latency histograms, active agent gauges, and Vault status.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.middleware.metrics_middleware import render_metrics

router = APIRouter(tags=["metrics"])

# Legacy counters kept for backward compatibility
_counters: dict[str, int] = {"requests_total": 0, "errors_total": 0}


def inc(name: str, amount: int = 1) -> None:
    """Increment a counter by *amount*."""
    _counters[name] = _counters.get(name, 0) + amount


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Return Prometheus-format metrics."""
    return render_metrics()
