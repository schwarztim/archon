"""Central metrics emission service for the Archon orchestration platform.

Delegates all storage to ``app.middleware.metrics_middleware`` so there is
a single source of truth for both in-process counters and Prometheus
exposition rendering. Every public ``record_*`` function is non-blocking —
a metric-system failure MUST NOT abort the calling code path.

All metric names carry the ``archon_`` prefix. Counter names end in
``_total``; histogram names end in ``_seconds``; gauge names carry no suffix.
"""

from __future__ import annotations

import logging

from app.middleware import metrics_middleware as _mm

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Queue metrics
# ---------------------------------------------------------------------------


def record_queue_depth(*, tenant_id: str = "unknown", queue_name: str = "default", value: int = 0) -> None:
    """Set ``archon_queue_depth`` gauge for the given tenant + queue."""
    try:
        _mm._queue_depth_gauges[(_mm._safe_str(tenant_id), _mm._safe_str(queue_name))] = max(0, int(value))
    except Exception as exc:  # noqa: BLE001
        log.debug("record_queue_depth failed: %s", exc)


def record_queue_drained(*, tenant_id: str = "unknown", queue_name: str = "default", count: int = 1) -> None:
    """Increment ``archon_queue_drain_rate_total`` for the given queue."""
    try:
        _mm._queue_drain_counts[(_mm._safe_str(tenant_id), _mm._safe_str(queue_name))] += max(0, int(count))
    except Exception as exc:  # noqa: BLE001
        log.debug("record_queue_drained failed: %s", exc)


# ---------------------------------------------------------------------------
# Worker metrics
# ---------------------------------------------------------------------------


def record_worker_heartbeat(*, worker_id: str = "unknown") -> None:
    """Increment ``archon_worker_heartbeats_total`` for the given worker."""
    try:
        _mm._worker_heartbeat_counts[_mm._safe_str(worker_id)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_worker_heartbeat failed: %s", exc)


def record_worker_active_tasks(*, worker_id: str = "unknown", value: int = 0) -> None:
    """Set ``archon_worker_active_tasks`` gauge for the given worker."""
    try:
        _mm._worker_active_tasks[_mm._safe_str(worker_id)] = max(0, int(value))
    except Exception as exc:  # noqa: BLE001
        log.debug("record_worker_active_tasks failed: %s", exc)


# ---------------------------------------------------------------------------
# Task metrics
# ---------------------------------------------------------------------------


def record_task_claimed(*, queue_name: str = "default") -> None:
    """Increment ``archon_tasks_claimed_total`` for the given queue."""
    try:
        _mm._tasks_claimed_counts[_mm._safe_str(queue_name)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_task_claimed failed: %s", exc)


def record_task_completed(*, queue_name: str = "default") -> None:
    """Increment ``archon_tasks_completed_total`` for the given queue."""
    try:
        _mm._tasks_completed_counts[_mm._safe_str(queue_name)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_task_completed failed: %s", exc)


def record_task_failed(*, queue_name: str = "default") -> None:
    """Increment ``archon_tasks_failed_total`` for the given queue."""
    try:
        _mm._tasks_failed_counts[_mm._safe_str(queue_name)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_task_failed failed: %s", exc)


# ---------------------------------------------------------------------------
# Run metrics
# ---------------------------------------------------------------------------


def record_run(*, status: str = "completed", trigger_type: str = "api") -> None:
    """Increment ``archon_runs_total`` for the given status + trigger_type."""
    try:
        bounded_status = _mm._bound(status, _mm._ALLOWED_STATUS)
        _mm._runs_total_counts[
            (bounded_status, _mm._safe_str(trigger_type)[:32])
        ] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_run failed: %s", exc)


def record_run_duration(seconds: float, *, status: str = "completed", trigger_type: str = "api") -> None:
    """Observe ``archon_run_duration_seconds`` histogram."""
    try:
        bounded_status = _mm._bound(status, _mm._ALLOWED_STATUS)
        tt = _mm._safe_str(trigger_type)[:32]
        key = (bounded_status, tt)
        _mm._run_duration_sums[key] += float(seconds)
        _mm._run_duration_counts[key] += 1
        for bucket in _mm._HISTOGRAM_BUCKETS:
            if seconds <= bucket:
                _mm._run_duration_buckets[(bounded_status, tt, bucket)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_run_duration failed: %s", exc)


# ---------------------------------------------------------------------------
# Activity metrics
# ---------------------------------------------------------------------------


def record_activity_retry(*, activity_type: str = "unknown") -> None:
    """Increment ``archon_activity_retries_total`` for the given activity_type."""
    try:
        _mm._activity_retry_counts[_mm._safe_str(activity_type)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_activity_retry failed: %s", exc)


def record_activity_heartbeat_age(seconds: float, *, activity_type: str = "unknown") -> None:
    """Set ``archon_activity_heartbeat_age_seconds`` gauge."""
    try:
        _mm._activity_heartbeat_age[_mm._safe_str(activity_type)] = max(0.0, float(seconds))
    except Exception as exc:  # noqa: BLE001
        log.debug("record_activity_heartbeat_age failed: %s", exc)


# ---------------------------------------------------------------------------
# Schedule metrics
# ---------------------------------------------------------------------------


def record_schedule_fire(*, schedule_id: str = "unknown") -> None:
    """Increment ``archon_schedule_fires_total``."""
    try:
        _mm._schedule_fires_counts[_mm._safe_str(schedule_id)[:64]] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_schedule_fire failed: %s", exc)


def record_schedule_missed(*, schedule_id: str = "unknown") -> None:
    """Increment ``archon_schedule_missed_total``."""
    try:
        _mm._schedule_missed_counts[_mm._safe_str(schedule_id)[:64]] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_schedule_missed failed: %s", exc)


# ---------------------------------------------------------------------------
# Pipeline metrics
# ---------------------------------------------------------------------------


def record_pipeline_ingress(*, provider: str = "unknown") -> None:
    """Increment ``archon_pipeline_ingress_total`` for the given provider."""
    try:
        _mm._pipeline_ingress_counts[_mm._safe_str(provider)[:64]] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_pipeline_ingress failed: %s", exc)


def record_pipeline_callback(*, provider: str = "unknown") -> None:
    """Increment ``archon_pipeline_callback_total`` for the given provider."""
    try:
        _mm._pipeline_callback_counts[_mm._safe_str(provider)[:64]] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_pipeline_callback failed: %s", exc)


# ---------------------------------------------------------------------------
# Policy / DLP / Budget metrics
# ---------------------------------------------------------------------------


def record_policy_deny(*, action: str = "unknown", reason: str = "unknown") -> None:
    """Increment ``archon_policy_denies_total`` for the given action + reason."""
    try:
        _mm._policy_deny_counts[
            (_mm._safe_str(action)[:64], _mm._safe_str(reason)[:64])
        ] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_policy_deny failed: %s", exc)


def record_dlp_block(*, tenant_id: str = "unknown") -> None:
    """Increment ``archon_dlp_blocks_total``."""
    try:
        _mm._dlp_block_counts[_mm._safe_str(tenant_id)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_dlp_block failed: %s", exc)


def record_budget_deny(*, tenant_id: str = "unknown") -> None:
    """Increment ``archon_budget_denies_total``."""
    try:
        _mm._budget_deny_counts[_mm._safe_str(tenant_id)] += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("record_budget_deny failed: %s", exc)


# ---------------------------------------------------------------------------
# Snapshot getters (for tests)
# ---------------------------------------------------------------------------


def get_task_claimed_counts() -> dict[str, int]:
    """Return current snapshot of archon_tasks_claimed_total."""
    return dict(_mm._tasks_claimed_counts)


def get_task_completed_counts() -> dict[str, int]:
    """Return current snapshot of archon_tasks_completed_total."""
    return dict(_mm._tasks_completed_counts)


def get_task_failed_counts() -> dict[str, int]:
    """Return current snapshot of archon_tasks_failed_total."""
    return dict(_mm._tasks_failed_counts)


def get_runs_total_counts() -> dict[tuple[str, str], int]:
    """Return current snapshot of archon_runs_total."""
    return dict(_mm._runs_total_counts)


def get_run_duration_counts() -> dict[tuple[str, str], int]:
    """Return current snapshot of archon_run_duration_seconds counts."""
    return dict(_mm._run_duration_counts)


def get_activity_retry_counts() -> dict[str, int]:
    """Return current snapshot of archon_activity_retries_total."""
    return dict(_mm._activity_retry_counts)


def get_schedule_fires_counts() -> dict[str, int]:
    """Return current snapshot of archon_schedule_fires_total."""
    return dict(_mm._schedule_fires_counts)


def get_pipeline_ingress_counts() -> dict[str, int]:
    """Return current snapshot of archon_pipeline_ingress_total."""
    return dict(_mm._pipeline_ingress_counts)
