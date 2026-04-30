"""Provider health tracking + circuit breaker.

Phase 4 / WS10 — Model Routing Squad.

Tracks per-provider availability with a rolling-window error rate and a
classic three-state circuit breaker (closed → open → half_open → closed).

The state is held in-process in a module-level singleton.  Callers must
not assume cross-process consistency — the long-lived store of record is
``provider_health_history`` in the DB (written by
``ModelRouterService.record_health_metric``).  This module exists to give
``call_llm_routed`` a fast, synchronous-feeling decision surface that
does not require a DB round-trip on every call.

Public surface
--------------

    check_provider(session, provider)            → ProviderHealth
    record_provider_call(session, provider, ...) → None
    is_circuit_open(session, provider)           → bool
    reset_state()                                → None  (test helper)

The ``session`` argument is accepted for API symmetry — callers that hold
an AsyncSession are expected to pass it so the function can later be
extended to persist samples without changing the call sites.  The current
implementation is in-memory only.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Circuit breaker tuning ─────────────────────────────────────────────
FAILURE_THRESHOLD = 5         # consecutive failures before opening
RECOVERY_TIMEOUT_S = 30.0     # cooldown before half-open
ROLLING_WINDOW_SIZE = 50      # samples kept per provider


# ── Public dataclass ────────────────────────────────────────────────


@dataclass
class ProviderHealth:
    """Snapshot of a provider's runtime health."""

    provider: str
    healthy: bool
    error_rate: float                    # rolling-window error rate, 0.0–1.0
    p99_latency_ms: float | None
    last_error: str | None
    last_check_at: datetime | None
    circuit_state: str                   # "closed" | "open" | "half_open"


# ── Internal per-provider state ─────────────────────────────────────


@dataclass
class _ProviderState:
    """Mutable state held for each provider."""

    samples: deque = field(default_factory=lambda: deque(maxlen=ROLLING_WINDOW_SIZE))
    consecutive_failures: int = 0
    circuit_state: str = "closed"        # closed | open | half_open
    opened_at_monotonic: float | None = None
    last_error: str | None = None
    last_check_at: datetime | None = None


# Module-level registry — keyed by provider name.
_state: dict[str, _ProviderState] = {}


def _get_state(provider: str) -> _ProviderState:
    """Return (creating if needed) the per-provider state record."""
    st = _state.get(provider)
    if st is None:
        st = _ProviderState()
        _state[provider] = st
    return st


def _compute_error_rate(samples: deque) -> float:
    """Compute the failure ratio over the rolling window."""
    if not samples:
        return 0.0
    failures = sum(1 for ok, _lat in samples if not ok)
    return failures / len(samples)


def _compute_p99(samples: deque) -> float | None:
    """Approximate p99 latency over successful samples (ms)."""
    latencies = sorted(lat for ok, lat in samples if ok and lat is not None)
    if not latencies:
        return None
    if len(latencies) == 1:
        return latencies[0]
    idx = int(0.99 * (len(latencies) - 1))
    return latencies[idx]


def _maybe_half_open(st: _ProviderState) -> str:
    """Transition open → half_open after RECOVERY_TIMEOUT_S has elapsed.

    Returns the (possibly-updated) circuit state.
    """
    if st.circuit_state == "open" and st.opened_at_monotonic is not None:
        if (time.monotonic() - st.opened_at_monotonic) > RECOVERY_TIMEOUT_S:
            st.circuit_state = "half_open"
            logger.info(
                "provider_health.circuit_half_open",
                extra={"opened_for_s": time.monotonic() - st.opened_at_monotonic},
            )
    return st.circuit_state


# ── Public API ──────────────────────────────────────────────────────


async def check_provider(session: Any, provider: str) -> ProviderHealth:
    """Return a snapshot of the provider's current health.

    Pure read — does not mutate state other than the open→half_open
    transition that fires on a recovery-timeout boundary.
    """
    st = _get_state(provider)
    state = _maybe_half_open(st)

    error_rate = _compute_error_rate(st.samples)
    p99 = _compute_p99(st.samples)

    healthy = state == "closed" and error_rate < 0.5
    return ProviderHealth(
        provider=provider,
        healthy=healthy,
        error_rate=error_rate,
        p99_latency_ms=p99,
        last_error=st.last_error,
        last_check_at=st.last_check_at,
        circuit_state=state,
    )


async def record_provider_call(
    session: Any,
    provider: str,
    *,
    success: bool,
    latency_ms: float,
    error: str | None = None,
) -> None:
    """Record one call outcome and update circuit state.

    State machine:
    - On success: append sample, reset consecutive_failures, transition
      half_open → closed.
    - On failure: append sample, increment consecutive_failures.  If
      threshold is reached (or we were already half_open), open the
      circuit.
    """
    st = _get_state(provider)
    st.samples.append((bool(success), float(latency_ms)))
    st.last_check_at = datetime.now(timezone.utc)

    if success:
        st.consecutive_failures = 0
        if st.circuit_state in ("half_open", "open"):
            logger.info(
                "provider_health.circuit_closed",
                extra={"provider": provider},
            )
        st.circuit_state = "closed"
        st.opened_at_monotonic = None
    else:
        st.last_error = error
        st.consecutive_failures += 1
        # Half-open trial failed → open immediately.
        if st.circuit_state == "half_open":
            st.circuit_state = "open"
            st.opened_at_monotonic = time.monotonic()
            logger.warning(
                "provider_health.circuit_reopened_after_trial",
                extra={"provider": provider, "error": error},
            )
        elif st.consecutive_failures >= FAILURE_THRESHOLD:
            if st.circuit_state != "open":
                st.circuit_state = "open"
                st.opened_at_monotonic = time.monotonic()
                logger.warning(
                    "provider_health.circuit_opened",
                    extra={
                        "provider": provider,
                        "consecutive_failures": st.consecutive_failures,
                        "error": error,
                    },
                )


async def is_circuit_open(session: Any, provider: str) -> bool:
    """Return True if the circuit is currently open (provider must be skipped).

    Honors the half-open transition: returns False once the cooldown has
    elapsed, allowing exactly one trial call per cooldown cycle.
    """
    st = _get_state(provider)
    state = _maybe_half_open(st)
    return state == "open"


def reset_state() -> None:
    """Clear all in-memory health state.  Test helper."""
    _state.clear()


__all__ = [
    "FAILURE_THRESHOLD",
    "RECOVERY_TIMEOUT_S",
    "ProviderHealth",
    "check_provider",
    "is_circuit_open",
    "record_provider_call",
    "reset_state",
]
