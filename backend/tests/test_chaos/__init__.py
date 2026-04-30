"""Chaos / resilience test package (Phase 6).

Tests in this package deliberately stress the durability substrate:
  - worker crash mid-step (lease expiration, recovery by another worker)
  - transient Postgres failures (TimeoutError, connection drops)
  - provider 429 storms (circuit breaker engagement, fallback)
  - Redis unavailability (rate-limit fail-open, dispatcher independence)

Run with::

    bash scripts/run-chaos-tests.sh

or::

    PYTHONPATH=backend LLM_STUB_MODE=true python3 -m pytest \
        backend/tests/test_chaos/ -v
"""
