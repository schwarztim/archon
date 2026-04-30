"""Canary-deploy rollback procedure tests.

These tests verify the *decision logic* for canary deployment
promotion vs. rollback. They do not invoke ``helm`` or any cluster —
the helm interaction is mocked. The actual canary metric thresholds
documented below are the contract that the production deploy pipeline
implements.

Canary metric thresholds (production contract):

  * Error rate (5xx + 4xx-non-auth) over 5-minute window:
      - < 1.0%  → continue/promote
      - 1.0%-3.0% → hold (no promote, no rollback)
      - > 3.0%  → rollback

  * P95 latency on ``/api/*`` over 5-minute window:
      - < 1.25× baseline → continue/promote
      - 1.25×-1.5× baseline → hold
      - > 1.5× baseline → rollback

  * Health-check success rate:
      - 100% → continue/promote
      - 99-100% → hold
      - < 99% → rollback (immediate)

  * Soak period: canary must hold "promote" status for ≥ 10 minutes
    before promote is allowed to fire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from unittest.mock import MagicMock

import pytest


# ── Production threshold contract ───────────────────────────────────

ERROR_RATE_PROMOTE_MAX = 0.01
ERROR_RATE_HOLD_MAX = 0.03
LATENCY_RATIO_PROMOTE_MAX = 1.25
LATENCY_RATIO_HOLD_MAX = 1.50
HEALTH_PROMOTE_MIN = 1.00
HEALTH_HOLD_MIN = 0.99
SOAK_MINUTES = 10


Verdict = Literal["promote", "hold", "rollback"]


@dataclass
class CanaryMetrics:
    """Snapshot of canary signals over the evaluation window."""

    error_rate: float
    latency_ratio: float  # canary p95 / baseline p95
    health_success: float
    soak_minutes: int


def evaluate_canary(metrics: CanaryMetrics) -> Verdict:
    """Apply the threshold contract documented in the module docstring.

    Returns ``"rollback"`` if any signal trips the rollback threshold,
    ``"hold"`` if any signal is in the hold band, otherwise ``"promote"``
    after the soak gate passes.
    """
    # Rollback signals (any one trips).
    if metrics.health_success < HEALTH_HOLD_MIN:
        return "rollback"
    if metrics.error_rate > ERROR_RATE_HOLD_MAX:
        return "rollback"
    if metrics.latency_ratio > LATENCY_RATIO_HOLD_MAX:
        return "rollback"

    # Hold signals (any one holds).
    if metrics.health_success < HEALTH_PROMOTE_MIN:
        return "hold"
    if metrics.error_rate > ERROR_RATE_PROMOTE_MAX:
        return "hold"
    if metrics.latency_ratio > LATENCY_RATIO_PROMOTE_MAX:
        return "hold"

    # Soak gate — even when every signal is green, we don't promote
    # until the canary has been steady for SOAK_MINUTES.
    if metrics.soak_minutes < SOAK_MINUTES:
        return "hold"
    return "promote"


def helm_rollback(
    helm_client: MagicMock,
    release: str,
    revision: int | None = None,
) -> dict:
    """Invoke ``helm rollback`` against the supplied client.

    Wraps the helm call to give us a single seam to mock. Mirrors the
    shape of the production deploy script's helm invocation.
    """
    return helm_client.rollback(release=release, revision=revision)


# ── Tests ───────────────────────────────────────────────────────────


def test_canary_metric_eval_promotes_when_all_green() -> None:
    """Every signal in the green band + soak satisfied → promote."""
    metrics = CanaryMetrics(
        error_rate=0.001,           # 0.1%
        latency_ratio=1.05,         # 5% over baseline
        health_success=1.00,
        soak_minutes=SOAK_MINUTES + 5,
    )
    assert evaluate_canary(metrics) == "promote"


def test_canary_metric_eval_holds_in_yellow_band() -> None:
    """A single signal in the hold band → hold, even if others are green."""
    metrics = CanaryMetrics(
        error_rate=0.02,            # in [1%, 3%] → hold
        latency_ratio=1.05,
        health_success=1.00,
        soak_minutes=SOAK_MINUTES + 5,
    )
    assert evaluate_canary(metrics) == "hold"


def test_canary_metric_eval_holds_during_soak() -> None:
    """All signals green but soak unsatisfied → hold."""
    metrics = CanaryMetrics(
        error_rate=0.001,
        latency_ratio=1.05,
        health_success=1.00,
        soak_minutes=SOAK_MINUTES - 1,
    )
    assert evaluate_canary(metrics) == "hold"


def test_rollback_trigger_fires_on_high_error_rate() -> None:
    """Error rate above the hold ceiling → rollback verdict."""
    metrics = CanaryMetrics(
        error_rate=0.05,            # 5%, above hold band
        latency_ratio=1.05,
        health_success=1.00,
        soak_minutes=SOAK_MINUTES + 5,
    )
    assert evaluate_canary(metrics) == "rollback"


def test_rollback_trigger_fires_on_health_check_failure() -> None:
    """Health success below 99% trips an immediate rollback."""
    metrics = CanaryMetrics(
        error_rate=0.001,
        latency_ratio=1.05,
        health_success=0.95,
        soak_minutes=SOAK_MINUTES + 5,
    )
    assert evaluate_canary(metrics) == "rollback"


def test_rollback_succeeds_via_helm_client() -> None:
    """When evaluator returns rollback, helm_rollback() invokes the helm client."""
    helm_client = MagicMock()
    helm_client.rollback.return_value = {
        "release": "archon-backend",
        "revision": 12,
        "status": "deployed",
    }

    metrics = CanaryMetrics(
        error_rate=0.05, latency_ratio=2.0, health_success=0.5, soak_minutes=2
    )
    verdict = evaluate_canary(metrics)
    assert verdict == "rollback"

    result = helm_rollback(helm_client, release="archon-backend", revision=12)

    helm_client.rollback.assert_called_once_with(
        release="archon-backend", revision=12
    )
    assert result["status"] == "deployed"
    assert result["release"] == "archon-backend"


@pytest.mark.parametrize(
    "metrics, expected",
    [
        # Latency ratio above hold band
        (CanaryMetrics(0.001, 2.0, 1.00, SOAK_MINUTES + 1), "rollback"),
        # Latency ratio within hold band
        (CanaryMetrics(0.001, 1.4, 1.00, SOAK_MINUTES + 1), "hold"),
        # Mixed: yellow latency + red health → rollback wins
        (CanaryMetrics(0.001, 1.4, 0.5, SOAK_MINUTES + 1), "rollback"),
    ],
)
def test_canary_eval_table(metrics: CanaryMetrics, expected: Verdict) -> None:
    """Table-driven cross-check of multi-signal precedence."""
    assert evaluate_canary(metrics) == expected
