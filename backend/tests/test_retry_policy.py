"""Unit tests for ``app.services.retry_policy.RetryPolicy``.

Pure-Python tests — no DB, no asyncio. Covers the documented behaviour
of ``compute_delay``, ``should_retry``, and ``from_step_config``.
"""

from __future__ import annotations

import pytest

from app.services.retry_policy import (
    AuthError,
    NotFoundError,
    RetryPolicy,
    TransientError,
    ValidationError,
)


# ── compute_delay ───────────────────────────────────────────────────────


def test_compute_delay_first_attempt_is_zero() -> None:
    """Attempt 1 is the initial try — no delay."""
    policy = RetryPolicy(
        max_attempts=5,
        initial_backoff_seconds=1.0,
        backoff_multiplier=2.0,
        max_backoff_seconds=60.0,
    )
    assert policy.compute_delay(1) == 0.0
    # Defensive: attempt < 1 also yields 0
    assert policy.compute_delay(0) == 0.0
    assert policy.compute_delay(-3) == 0.0


def test_compute_delay_exponential_backoff() -> None:
    """Each subsequent attempt multiplies the prior delay."""
    policy = RetryPolicy(
        max_attempts=10,
        initial_backoff_seconds=1.0,
        backoff_multiplier=2.0,
        max_backoff_seconds=1000.0,
    )
    assert policy.compute_delay(2) == 1.0
    assert policy.compute_delay(3) == 2.0
    assert policy.compute_delay(4) == 4.0
    assert policy.compute_delay(5) == 8.0
    assert policy.compute_delay(6) == 16.0


def test_compute_delay_caps_at_max() -> None:
    """``max_backoff_seconds`` is a hard ceiling on the computed delay."""
    policy = RetryPolicy(
        max_attempts=20,
        initial_backoff_seconds=1.0,
        backoff_multiplier=2.0,
        max_backoff_seconds=10.0,
    )
    # Without the cap: 1, 2, 4, 8, 16, 32, ... — should plateau at 10.
    assert policy.compute_delay(2) == 1.0
    assert policy.compute_delay(3) == 2.0
    assert policy.compute_delay(4) == 4.0
    assert policy.compute_delay(5) == 8.0
    assert policy.compute_delay(6) == 10.0  # would be 16 — capped
    assert policy.compute_delay(7) == 10.0
    assert policy.compute_delay(20) == 10.0


# ── should_retry ────────────────────────────────────────────────────────


def test_should_retry_within_max_attempts_for_transient() -> None:
    """A transient class with attempts remaining → retry."""
    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(TransientError("network blip"), attempt=1) is True
    assert policy.should_retry(TransientError("network blip"), attempt=2) is True
    # Built-in TimeoutError is in the default retry_on list
    assert policy.should_retry(TimeoutError("slow"), attempt=1) is True
    # Built-in ConnectionError too
    assert policy.should_retry(ConnectionError("reset"), attempt=1) is True


def test_should_retry_false_at_max_attempts() -> None:
    """Once attempt == max_attempts the policy stops retrying."""
    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(TransientError("x"), attempt=3) is False
    assert policy.should_retry(TransientError("x"), attempt=4) is False
    # max_attempts=1 means no retries at all
    no_retry = RetryPolicy(max_attempts=1)
    assert no_retry.should_retry(TransientError("x"), attempt=1) is False


def test_should_retry_false_for_non_retryable_class() -> None:
    """Classes in ``no_retry_on`` are never retried, regardless of attempt."""
    policy = RetryPolicy(max_attempts=5)
    assert policy.should_retry(ValidationError("bad input"), attempt=1) is False
    assert policy.should_retry(AuthError("denied"), attempt=1) is False
    assert policy.should_retry(NotFoundError("missing"), attempt=1) is False

    # Even if the user sneaks the class into retry_on, no_retry_on wins.
    contradictory = RetryPolicy(
        max_attempts=5,
        retry_on=["ValidationError"],
        no_retry_on=["ValidationError"],
    )
    assert (
        contradictory.should_retry(ValidationError("x"), attempt=1) is False
    )


def test_should_retry_unknown_class_default_no_match() -> None:
    """An exception whose class is not in ``retry_on`` is not retried."""

    class WeirdError(Exception):
        pass

    policy = RetryPolicy(max_attempts=5)
    # WeirdError is not in retry_on, not in no_retry_on → not retried
    assert policy.should_retry(WeirdError("unknown"), attempt=1) is False


def test_should_retry_empty_retry_on_means_retry_all() -> None:
    """An empty retry_on list with empty no_retry_on means retry everything."""

    class WeirdError(Exception):
        pass

    policy = RetryPolicy(
        max_attempts=5, retry_on=[], no_retry_on=[]
    )
    assert policy.should_retry(WeirdError("x"), attempt=1) is True
    assert policy.should_retry(RuntimeError("x"), attempt=2) is True


def test_should_retry_inherits_from_base_class_in_retry_on() -> None:
    """A subclass of a retry_on class is also retryable (MRO walk)."""

    class CustomTransient(TransientError):
        pass

    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(CustomTransient("blip"), attempt=1) is True


# ── from_step_config ────────────────────────────────────────────────────


def test_from_step_config_parses_retry_block() -> None:
    """A retry block under config is parsed; missing keys take the default."""
    step = {
        "id": "step-1",
        "type": "httpRequest",
        "config": {
            "url": "https://example.com",
            "retry": {
                "max_attempts": 5,
                "initial_backoff_seconds": 0.5,
                "backoff_multiplier": 3.0,
                "max_backoff_seconds": 30.0,
                "retry_on": ["TimeoutError"],
                "no_retry_on": ["AuthError"],
            },
        },
    }
    policy = RetryPolicy.from_step_config(step)
    assert policy.max_attempts == 5
    assert policy.initial_backoff_seconds == 0.5
    assert policy.backoff_multiplier == 3.0
    assert policy.max_backoff_seconds == 30.0
    assert policy.retry_on == ["TimeoutError"]
    assert policy.no_retry_on == ["AuthError"]


def test_from_step_config_uses_defaults_when_absent() -> None:
    """No retry block at all → an all-defaults policy."""
    default = RetryPolicy()

    # No config at all
    p1 = RetryPolicy.from_step_config({})
    assert p1.max_attempts == default.max_attempts
    assert p1.initial_backoff_seconds == default.initial_backoff_seconds
    assert p1.retry_on == default.retry_on
    assert p1.no_retry_on == default.no_retry_on

    # Config block present, but no retry sub-block
    p2 = RetryPolicy.from_step_config({"config": {"url": "x"}})
    assert p2.max_attempts == default.max_attempts
    assert p2.retry_on == default.retry_on


def test_from_step_config_accepts_top_level_retry_block() -> None:
    """A retry block at the top level of the step is also accepted."""
    step = {"id": "s", "retry": {"max_attempts": 7}}
    policy = RetryPolicy.from_step_config(step)
    assert policy.max_attempts == 7
    # Other fields fall back to defaults
    default = RetryPolicy()
    assert policy.initial_backoff_seconds == default.initial_backoff_seconds


def test_from_step_config_ignores_non_dict_retry_block() -> None:
    """A non-dict ``retry`` field is ignored — defaults returned."""
    step = {"config": {"retry": "not-a-dict"}}
    policy = RetryPolicy.from_step_config(step)
    default = RetryPolicy()
    assert policy.max_attempts == default.max_attempts
    assert policy.retry_on == default.retry_on


# ── data-class hygiene ──────────────────────────────────────────────────


def test_default_retry_on_includes_standard_transient_classes() -> None:
    """Sanity: the shipped default retry_on covers TransientError + builtins."""
    policy = RetryPolicy()
    assert "TransientError" in policy.retry_on
    assert "TimeoutError" in policy.retry_on
    assert "ConnectionError" in policy.retry_on


def test_default_no_retry_on_blocks_validation_and_auth() -> None:
    """Sanity: the shipped default no_retry_on blocks validation/auth/notfound."""
    policy = RetryPolicy()
    assert "ValidationError" in policy.no_retry_on
    assert "AuthError" in policy.no_retry_on
    assert "NotFoundError" in policy.no_retry_on


def test_two_policies_have_independent_lists() -> None:
    """``field(default_factory=...)`` keeps each instance's lists isolated."""
    p1 = RetryPolicy()
    p2 = RetryPolicy()
    p1.retry_on.append("CustomError")
    assert "CustomError" not in p2.retry_on


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
