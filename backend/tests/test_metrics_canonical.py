"""Phase 5 — canonical metric set verification.

Verifies that every metric called out in the Phase 5 mission is emitted
with the canonical label set, that labels are bounded, and that
emission is non-blocking on metric-system failure.

These tests deliberately work against the in-memory metrics middleware
storage so they run fast and require no FastAPI app fixture. The
``_reload_module`` helper resets state between tests.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch


# ──────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────


def _reload_module():
    """Return the cached metrics_middleware module after clearing its
    in-memory storage.

    We deliberately do NOT delete the module from ``sys.modules`` —
    other already-loaded modules (the dispatcher, ``app.metrics``, the
    middleware package's ``__init__``) hold cached references to the
    current instance, and reloading the module would orphan those.
    Clearing the dicts/lists in place is sufficient for test isolation
    and matches the storage's documented in-memory single-process model.
    """
    import app.middleware.metrics_middleware as m

    for attr in (
        "_request_counts",
        "_duration_sums",
        "_duration_counts",
        "_duration_buckets",
        "_token_usage_counts",
        "_token_usage_counts_canonical",
        "_cost_totals",
        "_cost_totals_canonical",
        "_workflow_run_counts",
        "_workflow_run_counts_canonical",
        "_workflow_duration_buckets",
        "_workflow_duration_sums_canonical",
        "_workflow_duration_counts_canonical",
        "_workflow_duration_buckets_canonical",
        "_step_duration_sums",
        "_step_duration_counts",
        "_step_duration_buckets",
        "_step_retries_counts",
        "_run_cancellations_counts",
        "_checkpoint_failures_counts",
        "_provider_latency_sums",
        "_provider_latency_counts",
        "_provider_latency_buckets",
        "_provider_fallback_counts",
        "_dlp_finding_counts",
    ):
        try:
            getattr(m, attr).clear()
        except AttributeError:
            pass
    m._workflow_duration_sums[0] = 0.0
    m._workflow_duration_counts[0] = 0
    return m


def _make_run(
    *,
    tenant_id: str = "tenant-a",
    kind: str = "workflow",
    status: str = "completed",
    error_code: str | None = None,
):
    """Minimal duck-typed WorkflowRun stand-in for dispatcher emitters."""
    return SimpleNamespace(
        tenant_id=tenant_id,
        kind=kind,
        status=status,
        error_code=error_code,
    )


# ──────────────────────────────────────────────
# Workflow-level metrics
# ──────────────────────────────────────────────


def test_archon_workflow_runs_total_increments_on_completion():
    m = _reload_module()
    m.record_workflow_run("completed", "tenant-a", kind="workflow")
    m.record_workflow_run("completed", "tenant-a", kind="workflow")
    m.record_workflow_run("failed", "tenant-a", kind="workflow")

    canonical = m.get_workflow_run_counts_canonical()
    assert canonical[("tenant-a", "workflow", "completed")] == 2
    assert canonical[("tenant-a", "workflow", "failed")] == 1
    # Legacy 2-tuple still populated for back-compat
    legacy = m.get_workflow_run_counts()
    assert legacy[("completed", "tenant-a")] == 2


def test_archon_workflow_run_duration_seconds_observed():
    m = _reload_module()
    m.record_workflow_duration(
        0.5, tenant_id="tenant-a", kind="workflow", status="completed"
    )
    m.record_workflow_duration(
        2.0, tenant_id="tenant-a", kind="workflow", status="completed"
    )

    key = ("tenant-a", "workflow", "completed")
    assert m._workflow_duration_counts_canonical[key] == 2
    assert abs(m._workflow_duration_sums_canonical[key] - 2.5) < 1e-9
    # Legacy unlabeled path also incremented.
    assert m._workflow_duration_counts[0] == 2


def test_archon_step_duration_seconds_observed():
    m = _reload_module()
    m.record_step_duration(
        0.05, tenant_id="tenant-a", node_type="llm", status="completed"
    )
    m.record_step_duration(
        0.20, tenant_id="tenant-a", node_type="llm", status="completed"
    )

    counts = m.get_step_duration_counts()
    assert counts[("tenant-a", "llm", "completed")] == 2

    # Histogram render appears in /metrics output.
    output = m.render_metrics()
    assert "archon_step_duration_seconds" in output
    assert 'tenant_id="tenant-a"' in output
    assert 'node_type="llm"' in output


def test_archon_step_retries_total_increments_on_retry():
    m = _reload_module()
    m.record_step_retry(tenant_id="tenant-a", node_type="llm")
    m.record_step_retry(tenant_id="tenant-a", node_type="llm")
    m.record_step_retry(tenant_id="tenant-a", node_type="http")

    counts = m.get_step_retries_counts()
    assert counts[("tenant-a", "llm")] == 2
    assert counts[("tenant-a", "http")] == 1


def test_archon_token_usage_total_records_prompt_and_completion_separately():
    m = _reload_module()
    m.record_token_usage(
        "tenant-a", "gpt-4o", "prompt", 100, provider="openai"
    )
    m.record_token_usage(
        "tenant-a", "gpt-4o", "completion", 50, provider="openai"
    )

    canonical = m.get_token_usage_counts_canonical()
    assert canonical[("tenant-a", "openai", "gpt-4o", "prompt")] == 100
    assert canonical[("tenant-a", "openai", "gpt-4o", "completion")] == 50


def test_archon_cost_total_increments_in_usd():
    m = _reload_module()
    m.record_cost("tenant-a", "gpt-4o", 0.001, provider="openai")
    m.record_cost("tenant-a", "gpt-4o", 0.0035, provider="openai")

    canonical = m.get_cost_totals_canonical()
    assert abs(canonical[("tenant-a", "openai", "gpt-4o")] - 0.0045) < 1e-9


def test_archon_provider_latency_seconds_observed():
    m = _reload_module()
    m.record_provider_latency(
        0.3, provider="openai", model="gpt-4o", status="success"
    )
    m.record_provider_latency(
        1.1, provider="openai", model="gpt-4o", status="success"
    )

    counts = m.get_provider_latency_counts()
    assert counts[("openai", "gpt-4o", "success")] == 2

    output = m.render_metrics()
    assert "archon_provider_latency_seconds" in output
    assert 'provider="openai"' in output


def test_archon_provider_fallback_total_on_fallback():
    m = _reload_module()
    m.record_provider_fallback(
        from_provider="openai", to_provider="anthropic", reason="rate_limit"
    )
    m.record_provider_fallback(
        from_provider="openai", to_provider="anthropic", reason="rate_limit"
    )

    counts = m.get_provider_fallback_counts()
    assert counts[("openai", "anthropic", "rate_limit")] == 2

    output = m.render_metrics()
    assert "archon_provider_fallback_total" in output
    assert 'from_provider="openai"' in output
    assert 'to_provider="anthropic"' in output


def test_archon_run_cancellations_total_with_reason():
    m = _reload_module()
    m.record_run_cancellation(tenant_id="tenant-a", reason="user_requested")
    m.record_run_cancellation(
        tenant_id="tenant-a", reason="cancel_requested_before_claim"
    )

    counts = m.get_run_cancellations_counts()
    assert counts[("tenant-a", "user_requested")] == 1
    assert counts[("tenant-a", "cancel_requested_before_claim")] == 1


def test_archon_checkpoint_failures_total_emitted_on_durability_fail():
    m = _reload_module()
    m.record_checkpoint_failure(env="production", reason="connect_error")

    counts = m.get_checkpoint_failures_counts()
    assert counts[("production", "connect_error")] == 1

    output = m.render_metrics()
    assert "archon_checkpoint_failures_total" in output
    assert 'env="production"' in output
    assert 'reason="connect_error"' in output


# ──────────────────────────────────────────────
# Cardinality / safety
# ──────────────────────────────────────────────


def test_metric_labels_bounded_no_unbounded_user_input():
    """Free-form user input must be bounded to known enums or coerced to
    'unknown'; never round-tripped as the raw label value."""
    m = _reload_module()

    # Pretend a buggy caller passes a UUID-flavoured run-id as status —
    # the bounded enum should snap it to "unknown" so cardinality is safe.
    bogus_status = "00000000-aaaa-bbbb-cccc-deadbeef0001"
    m.record_workflow_run(bogus_status, "tenant-a", kind="workflow")

    canonical = m.get_workflow_run_counts_canonical()
    # Verify the bogus value is NOT in the keyset.
    assert all(
        bogus_status not in tuple_key
        for tuple_key in canonical.keys()
    )
    # Verify it was bounded to "unknown".
    assert ("tenant-a", "workflow", "unknown") in canonical

    # Same check for token-usage kind.
    m.record_token_usage(
        "tenant-a", "gpt-4o", "exfiltration", 100, provider="openai"
    )
    tok_canonical = m.get_token_usage_counts_canonical()
    assert all(
        "exfiltration" not in tuple_key for tuple_key in tok_canonical.keys()
    )

    # Workflow kind also bounded
    m.record_workflow_run(
        "completed", "tenant-a", kind="rogue-injected-kind-value"
    )
    wf_canonical = m.get_workflow_run_counts_canonical()
    assert all(
        "rogue-injected-kind-value" not in tuple_key
        for tuple_key in wf_canonical.keys()
    )


def test_emission_non_blocking_on_metric_system_failure(monkeypatch):
    """If the underlying counter dict throws, the helper must swallow
    the exception and the caller's flow must continue uninterrupted.
    """
    m = _reload_module()

    # Replace the canonical store with a dict subclass that raises on
    # every mutation. The public helper must NOT propagate the error.
    class ExplodingDict(dict):
        def __setitem__(self, key, value):  # noqa: D401
            raise RuntimeError("metric store kaboom")

        def __getitem__(self, key):
            raise RuntimeError("metric store kaboom")

    monkeypatch.setattr(
        m, "_workflow_run_counts_canonical", ExplodingDict()
    )
    monkeypatch.setattr(m, "_workflow_run_counts", ExplodingDict())

    # Should NOT raise.
    m.record_workflow_run("completed", "tenant-a", kind="workflow")

    # And the dispatcher's inline try/except wrapper must also swallow
    # any error — simulate that by calling the helper directly with a
    # broken record_workflow_run patched in.
    from app.services import run_dispatcher

    def _raise(*_a, **_kw):
        raise RuntimeError("inner emit failed")

    with patch.object(
        run_dispatcher._metrics, "record_workflow_run", _raise
    ):
        # Should NOT raise.
        run_dispatcher._emit_run_terminal_metrics(
            _make_run(status="completed"),
            duration_ms=100,
        )


def test_render_metrics_includes_all_canonical_names():
    """Phase 5 acceptance #1 — all 14 canonical metrics must be present
    in render output once each has at least one observation."""
    m = _reload_module()
    m.record_workflow_run("completed", "t", kind="workflow")
    m.record_workflow_duration(
        0.1, tenant_id="t", kind="workflow", status="completed"
    )
    m.record_step_duration(
        0.05, tenant_id="t", node_type="llm", status="completed"
    )
    m.record_step_retry(tenant_id="t", node_type="llm")
    m.record_run_cancellation(tenant_id="t", reason="user_requested")
    m.record_checkpoint_failure(env="production", reason="connect_error")
    m.record_token_usage("t", "gpt-4o", "prompt", 10, provider="openai")
    m.record_cost("t", "gpt-4o", 0.001, provider="openai")
    m.record_provider_latency(
        0.3, provider="openai", model="gpt-4o", status="success"
    )
    m.record_provider_fallback(
        from_provider="openai", to_provider="anthropic", reason="429"
    )
    m.record_dlp_finding("t", "high", "ssn")

    output = m.render_metrics()

    canonical_names = [
        "archon_workflow_runs_total",
        "archon_workflow_run_duration_seconds",
        "archon_step_duration_seconds",
        "archon_step_retries_total",
        "archon_run_cancellations_total",
        "archon_checkpoint_failures_total",
        "archon_token_usage_total",
        "archon_cost_total",
        "archon_provider_latency_seconds",
        "archon_provider_fallback_total",
        "archon_dlp_findings_total",
        "archon_request_duration_seconds",
        "archon_requests_total",
    ]
    for name in canonical_names:
        assert name in output, f"missing canonical metric: {name}"


def test_metrics_helper_inc_counter_dispatches_correctly():
    """The ``app.metrics.inc_counter`` facade must reach the right
    middleware emitter without leaking exceptions on unknown names."""
    _reload_module()
    if "app.metrics" in sys.modules:
        del sys.modules["app.metrics"]
    import app.metrics as helper

    helper.inc_counter(
        "archon_step_retries_total",
        labels={"tenant_id": "t", "node_type": "llm"},
    )
    from app.middleware import metrics_middleware as m

    assert m.get_step_retries_counts()[("t", "llm")] == 1

    # Unknown name must not raise.
    helper.inc_counter("archon_unknown_metric", labels={})


def test_metrics_helper_observe_histogram_dispatches_correctly():
    _reload_module()
    if "app.metrics" in sys.modules:
        del sys.modules["app.metrics"]
    import app.metrics as helper

    helper.observe_histogram(
        "archon_provider_latency_seconds",
        labels={"provider": "openai", "model": "gpt-4o", "status": "success"},
        value=0.42,
    )
    from app.middleware import metrics_middleware as m

    counts = m.get_provider_latency_counts()
    assert counts[("openai", "gpt-4o", "success")] == 1

    helper.observe_histogram("archon_unknown_histogram", labels={}, value=1.0)
