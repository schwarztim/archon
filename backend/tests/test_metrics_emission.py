"""Tests for new metric helper functions in metrics_middleware.

Verifies that each helper writes the correct entry into the in-memory
metric stores, and that render_metrics() includes the new metric names
in Prometheus exposition format.
"""

from __future__ import annotations

import importlib
import sys


# ── helpers to reset module state between tests ──────────────────────
def _reload_module():
    """Reload metrics_middleware to get a clean in-memory state."""
    mod_name = "app.middleware.metrics_middleware"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import app.middleware.metrics_middleware as m
    return m


# ── token usage ───────────────────────────────────────────────────────

def test_record_token_usage_increments_counter():
    m = _reload_module()
    m.record_token_usage("tenant-a", "gpt-4o", "prompt", 100)
    m.record_token_usage("tenant-a", "gpt-4o", "prompt", 50)
    m.record_token_usage("tenant-a", "gpt-4o", "completion", 30)

    counts = m.get_token_usage_counts()
    assert counts[("tenant-a", "gpt-4o", "prompt")] == 150
    assert counts[("tenant-a", "gpt-4o", "completion")] == 30


def test_record_token_usage_multiple_tenants():
    m = _reload_module()
    m.record_token_usage("tenant-a", "claude-3-5-sonnet", "prompt", 200)
    m.record_token_usage("tenant-b", "claude-3-5-sonnet", "completion", 80)

    counts = m.get_token_usage_counts()
    assert counts[("tenant-a", "claude-3-5-sonnet", "prompt")] == 200
    assert counts[("tenant-b", "claude-3-5-sonnet", "completion")] == 80
    # No cross-contamination
    assert counts.get(("tenant-a", "claude-3-5-sonnet", "completion"), 0) == 0


# ── cost ──────────────────────────────────────────────────────────────

def test_record_cost_accumulates():
    m = _reload_module()
    m.record_cost("tenant-a", "gpt-4o", 0.005)
    m.record_cost("tenant-a", "gpt-4o", 0.003)

    totals = m.get_cost_totals()
    assert abs(totals[("tenant-a", "gpt-4o")] - 0.008) < 1e-9


def test_record_cost_separate_models():
    m = _reload_module()
    m.record_cost("tenant-x", "gpt-4o", 0.01)
    m.record_cost("tenant-x", "claude-3-haiku", 0.002)

    totals = m.get_cost_totals()
    assert abs(totals[("tenant-x", "gpt-4o")] - 0.01) < 1e-9
    assert abs(totals[("tenant-x", "claude-3-haiku")] - 0.002) < 1e-9


# ── workflow runs ─────────────────────────────────────────────────────

def test_record_workflow_run_increments():
    m = _reload_module()
    m.record_workflow_run("completed", "tenant-a")
    m.record_workflow_run("completed", "tenant-a")
    m.record_workflow_run("failed", "tenant-a")

    counts = m.get_workflow_run_counts()
    assert counts[("completed", "tenant-a")] == 2
    assert counts[("failed", "tenant-a")] == 1


# ── workflow duration ─────────────────────────────────────────────────

def test_record_workflow_duration_updates_histogram():
    m = _reload_module()
    m.record_workflow_duration(0.5)  # within 0.5 and 0.75 buckets
    m.record_workflow_duration(2.0)  # within 2.5 bucket

    # sum and count
    assert abs(m._workflow_duration_sums[0] - 2.5) < 1e-9
    assert m._workflow_duration_counts[0] == 2

    # bucket at 0.5s should have count 1 (only first sample fits)
    assert m._workflow_duration_buckets.get(0.5) == 1
    # bucket at 2.5s should have count 2 (both samples fit)
    assert m._workflow_duration_buckets.get(2.5) == 2


# ── DLP findings ──────────────────────────────────────────────────────

def test_record_dlp_finding_increments():
    m = _reload_module()
    m.record_dlp_finding("tenant-a", "high", "ssn")
    m.record_dlp_finding("tenant-a", "high", "ssn")
    m.record_dlp_finding("tenant-a", "medium", "email")

    counts = m.get_dlp_finding_counts()
    assert counts[("tenant-a", "high", "ssn")] == 2
    assert counts[("tenant-a", "medium", "email")] == 1


# ── render_metrics() output ───────────────────────────────────────────

def test_render_metrics_includes_new_metric_names():
    m = _reload_module()

    # Populate each new metric with at least one data point.
    m.record_token_usage("t1", "gpt-4o", "prompt", 10)
    m.record_cost("t1", "gpt-4o", 0.001)
    m.record_workflow_run("completed", "t1")
    m.record_workflow_duration(1.0)
    m.record_dlp_finding("t1", "low", "phone")

    output = m.render_metrics()

    assert "archon_token_usage_total" in output
    assert "archon_cost_total" in output
    assert "archon_workflow_runs_total" in output
    assert "archon_workflow_run_duration_seconds" in output
    assert "archon_dlp_findings_total" in output


def test_render_metrics_token_usage_labels():
    m = _reload_module()
    m.record_token_usage("tenant-z", "claude-3-opus", "completion", 55)

    output = m.render_metrics()
    assert 'tenant_id="tenant-z"' in output
    assert 'model="claude-3-opus"' in output
    assert 'kind="completion"' in output
    assert " 55" in output


def test_render_metrics_cost_labels():
    m = _reload_module()
    m.record_cost("tenant-z", "gpt-4o-mini", 0.000123)

    output = m.render_metrics()
    assert 'archon_cost_total{tenant_id="tenant-z",model="gpt-4o-mini"}' in output


def test_render_metrics_workflow_run_labels():
    m = _reload_module()
    m.record_workflow_run("failed", "tenant-q")

    output = m.render_metrics()
    assert 'archon_workflow_runs_total{status="failed",tenant_id="tenant-q"} 1' in output


def test_render_metrics_dlp_finding_labels():
    m = _reload_module()
    m.record_dlp_finding("tenant-p", "high", "credit_card")

    output = m.render_metrics()
    assert 'archon_dlp_findings_total{tenant_id="tenant-p",severity="high",pattern="credit_card"} 1' in output


def test_render_metrics_existing_names_still_present():
    """Regression: existing metric names must not disappear."""
    m = _reload_module()
    output = m.render_metrics()

    assert "archon_requests_total" in output
    assert "archon_request_duration_seconds" in output
    assert "archon_active_agents" in output
    assert "archon_vault_status" in output
