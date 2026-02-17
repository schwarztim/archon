"""Prometheus metrics middleware for HTTP request tracking.

Collects request count and latency histogram data for all HTTP
requests, exposed via the /metrics endpoint in Prometheus format.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


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

    return "\n".join(lines) + "\n"
