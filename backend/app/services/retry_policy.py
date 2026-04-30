"""Retry policy primitive — per-step retry behaviour.

Owned by WS7 — Timers/Retries Squad. Pure data + helpers; no I/O. The
dispatcher (W2.4) consumes this together with ``timer_service`` to
schedule the next retry attempt as a durable timer.

Design notes:
  - One ``RetryPolicy`` per step. Loaded from the step's
    ``definition_snapshot`` block at run time (see ``from_step_config``).
  - The policy is *purely declarative*. It does not raise, retry, or
    sleep — those are dispatcher responsibilities. The policy answers
    two questions: "should I retry this exception?" and "how long until
    the next attempt?"
  - Exception classification is by *class name string* (the exception's
    ``__class__.__name__``). This sidesteps cross-package imports and
    lets the policy work uniformly against any exception hierarchy.
  - We provide a marker ``TransientError`` base class so callers that
    want to opt in have a clean way to do so, but no existing code is
    forced to inherit from it. The default ``retry_on`` list also
    includes ``TimeoutError`` and ``ConnectionError`` (built-in classes
    every async client raises), so most real failures are covered out of
    the box.

Usage::

    policy = RetryPolicy.from_step_config(step)
    if policy.should_retry(exc, attempt):
        delay_seconds = policy.compute_delay(attempt + 1)
        # ... schedule a Timer with fire_at = now + delay_seconds
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Marker error taxonomy ───────────────────────────────────────────────


class TransientError(Exception):
    """Marker base class for retryable, transient failures.

    Existing code does NOT need to inherit from this — the policy
    classifies by class name, not isinstance. Provided as a clean opt-in
    for new code that wants to declare intent.
    """


class AuthError(Exception):
    """Marker for non-retryable authentication / authorization failures."""


class ValidationError(Exception):
    """Marker for non-retryable input validation failures."""


class NotFoundError(Exception):
    """Marker for non-retryable resource-missing failures."""


# ── Policy ──────────────────────────────────────────────────────────────


@dataclass
class RetryPolicy:
    """Per-step retry behaviour. Loaded from definition_snapshot per step.

    Attributes:
      max_attempts: Total attempts including the initial try. ``1`` means
        no retry; ``3`` means the original attempt plus 2 retries.
      initial_backoff_seconds: Wait before the *first* retry (i.e. before
        attempt 2). Attempt 1 is always immediate (delay=0).
      backoff_multiplier: Exponential growth factor between retries.
      max_backoff_seconds: Hard cap; the computed delay never exceeds this.
      retry_on: Exception class names that ARE retryable. The empty list
        means "retry every exception not in ``no_retry_on``."
      no_retry_on: Exception class names that are NEVER retryable, even
        if they would otherwise match ``retry_on``. ``no_retry_on`` always
        wins when both lists match.
    """

    max_attempts: int = 1
    initial_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 60.0
    retry_on: list[str] = field(
        default_factory=lambda: [
            "TransientError",
            "TimeoutError",
            "ConnectionError",
        ]
    )
    no_retry_on: list[str] = field(
        default_factory=lambda: [
            "ValidationError",
            "AuthError",
            "NotFoundError",
        ]
    )

    # ── Construction ─────────────────────────────────────────────────────

    @classmethod
    def from_step_config(cls, step: dict) -> "RetryPolicy":
        """Build a policy from a step dict.

        Looks for a ``retry`` block under either the step's
        ``config`` sub-dict or the step's top level. Both shapes are
        accepted because node configs in this codebase live under
        ``step["config"]`` for runtime nodes but can also appear inline
        on snapshot rows.

        Recognised keys (all optional):
          max_attempts, initial_backoff_seconds, backoff_multiplier,
          max_backoff_seconds, retry_on, no_retry_on

        Missing or non-dict ``retry`` block → all-defaults policy.
        """
        config = step.get("config") if isinstance(step, dict) else None
        retry_block: dict | None = None

        if isinstance(config, dict) and isinstance(config.get("retry"), dict):
            retry_block = config["retry"]
        elif isinstance(step, dict) and isinstance(step.get("retry"), dict):
            retry_block = step["retry"]

        if not retry_block:
            return cls()

        kwargs: dict = {}
        if "max_attempts" in retry_block:
            kwargs["max_attempts"] = int(retry_block["max_attempts"])
        if "initial_backoff_seconds" in retry_block:
            kwargs["initial_backoff_seconds"] = float(
                retry_block["initial_backoff_seconds"]
            )
        if "backoff_multiplier" in retry_block:
            kwargs["backoff_multiplier"] = float(
                retry_block["backoff_multiplier"]
            )
        if "max_backoff_seconds" in retry_block:
            kwargs["max_backoff_seconds"] = float(
                retry_block["max_backoff_seconds"]
            )
        if "retry_on" in retry_block and isinstance(
            retry_block["retry_on"], list
        ):
            kwargs["retry_on"] = [str(x) for x in retry_block["retry_on"]]
        if "no_retry_on" in retry_block and isinstance(
            retry_block["no_retry_on"], list
        ):
            kwargs["no_retry_on"] = [
                str(x) for x in retry_block["no_retry_on"]
            ]

        return cls(**kwargs)

    # ── Computation ──────────────────────────────────────────────────────

    def compute_delay(self, attempt: int) -> float:
        """Return the seconds to wait BEFORE the given (1-indexed) attempt.

        Conventions:
          attempt=1 → 0.0   (the initial try is immediate)
          attempt=2 → initial_backoff_seconds
          attempt=N → initial_backoff_seconds * multiplier ** (N-2)
                      capped at max_backoff_seconds

        ``attempt < 1`` is treated as 1 (delay 0). Negative or zero delays
        in any field are coerced upward to 0 to keep callers safe.
        """
        if attempt <= 1:
            return 0.0

        base = max(self.initial_backoff_seconds, 0.0)
        multiplier = max(self.backoff_multiplier, 0.0)
        # exponent is (attempt - 2): attempt=2 → 0, attempt=3 → 1, ...
        delay = base * (multiplier ** (attempt - 2))
        cap = max(self.max_backoff_seconds, 0.0)
        return min(delay, cap)

    def should_retry(self, exception: BaseException, attempt: int) -> bool:
        """True if attempt < max_attempts AND exception is retryable.

        Retryability rules (in order):
          1. If max_attempts has been reached, False.
          2. If the exception's class name is in ``no_retry_on``, False.
             (no_retry_on always wins.)
          3. If ``retry_on`` is empty, True (retry everything not blocked
             by no_retry_on).
          4. If the exception's class name (or any base class name in its
             MRO) is in ``retry_on``, True.
          5. Otherwise False.
        """
        if attempt >= self.max_attempts:
            return False

        names = {cls.__name__ for cls in type(exception).__mro__}

        if any(name in self.no_retry_on for name in names):
            return False

        if not self.retry_on:
            return True

        return any(name in self.retry_on for name in names)


__all__ = [
    "AuthError",
    "NotFoundError",
    "RetryPolicy",
    "TransientError",
    "ValidationError",
]
