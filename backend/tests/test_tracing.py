"""Tests for Phase 5 / W5.2 distributed tracing.

Validates:
  * span context manager records attributes and exception state
  * dispatcher creates a workflow.run span with run_id / tenant_id / kind
  * step spans nest under run spans
  * llm.call span carries provider + model attrs
  * llm.fallback event records the failed provider
  * http.client span carries url + method (+ status_code on success)
  * tracing degrades to no-op when OTel is unavailable
  * tenant_id propagates through to spans
  * the request middleware opens an http.request span on every request
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("ARCHON_TRACING_ENABLED", "true")
# Force in-memory exporter for tests (production reads OTLP env vars).
os.environ.setdefault("ARCHON_OTEL_EXPORTER", "memory")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _ensure_in_memory_exporter():
    """Install the in-memory exporter if it isn't already, return it.

    The provider is global per-process; once a provider is set OTel won't
    let us swap it. Tests share the same exporter via the cached handle
    in :mod:`app.services.tracing` and clear it between cases.
    """
    from app.services import tracing as t

    exporter = t.get_in_memory_exporter()
    if exporter is None:
        exporter = t.configure_tracing(force_in_memory=True)
    if exporter is not None:
        exporter.clear()
    return exporter


def _spans_by_name(exporter) -> dict[str, list[Any]]:
    spans = exporter.get_finished_spans()
    out: dict[str, list[Any]] = {}
    for span in spans:
        out.setdefault(span.name, []).append(span)
    return out


# ---------------------------------------------------------------------------
# 1. span context manager records attrs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_context_manager_records_attrs():
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    from app.services.tracing import span

    async with span("test.span", run_id="r-1", count=42, ratio=0.5):
        pass

    spans = exporter.get_finished_spans()
    assert any(s.name == "test.span" for s in spans)
    record = next(s for s in spans if s.name == "test.span")
    assert record.attributes["run_id"] == "r-1"
    assert record.attributes["count"] == 42
    assert record.attributes["ratio"] == 0.5


# ---------------------------------------------------------------------------
# 2. exception path sets ERROR + records exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_records_exception():
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    from opentelemetry.trace.status import StatusCode

    from app.services.tracing import span

    with pytest.raises(RuntimeError):
        async with span("test.boom", op="x"):
            raise RuntimeError("boom")

    spans = exporter.get_finished_spans()
    record = next(s for s in spans if s.name == "test.boom")
    assert record.status.status_code == StatusCode.ERROR
    # Exception event recorded.
    assert any(e.name == "exception" for e in record.events)


# ---------------------------------------------------------------------------
# 3. dispatcher creates workflow.run span with the expected attributes
# ---------------------------------------------------------------------------


class _FakeRun:
    """Plain object stand-in for a WorkflowRun row.

    The dispatcher only needs the few attributes we set here to wrap the
    workflow.run span; we bypass the rest of execute_claimed_run by
    targeting :func:`_execute_claimed_run_inner` separately when needed.
    """

    def __init__(self):
        self.id = UUID("11111111-1111-1111-1111-111111111111")
        self.tenant_id = UUID("22222222-2222-2222-2222-222222222222")
        self.kind = "workflow"
        self.attempt = 1
        self.lease_owner = "worker-x"


@pytest.mark.asyncio
async def test_dispatcher_creates_workflow_run_span_with_run_id_attribute(monkeypatch):
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    from app.services import run_dispatcher

    inner_calls: list[Any] = []

    async def _fake_inner(session, run, *, worker_id, correlation_id):
        inner_calls.append((run.id, worker_id, correlation_id))

    monkeypatch.setattr(run_dispatcher, "_execute_claimed_run_inner", _fake_inner)

    run = _FakeRun()
    await run_dispatcher.execute_claimed_run(session=None, run=run, worker_id="worker-x")

    assert len(inner_calls) == 1
    run_spans = _spans_by_name(exporter).get("workflow.run", [])
    assert run_spans, "workflow.run span was not recorded"
    attrs = run_spans[-1].attributes
    assert attrs["run_id"] == str(run.id)
    assert attrs["tenant_id"] == str(run.tenant_id)
    assert attrs["kind"] == "workflow"
    assert attrs["attempt"] == 1


# ---------------------------------------------------------------------------
# 4. step span nests under the run span
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_span_nested_under_run_span():
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    from app.services.tracing import span

    async with span("workflow.run", run_id="r-2"):
        async with span("workflow.step", step_id="s-1"):
            pass

    by_name = _spans_by_name(exporter)
    run_span = by_name["workflow.run"][-1]
    step_span = by_name["workflow.step"][-1]
    # Same trace, step is child of run.
    assert step_span.context.trace_id == run_span.context.trace_id
    assert step_span.parent is not None
    assert step_span.parent.span_id == run_span.context.span_id


# ---------------------------------------------------------------------------
# 5. llm.call span has provider + model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_span_has_provider_and_model_attrs():
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    # LLM_STUB_MODE is true in test env — call_llm short-circuits.
    from app.langgraph.llm import call_llm

    response = await call_llm("hello", model="gpt-3.5-turbo")
    assert response.content.startswith("[STUB]")

    by_name = _spans_by_name(exporter)
    llm_spans = by_name.get("llm.call", [])
    assert llm_spans, "llm.call span was not recorded"
    attrs = llm_spans[-1].attributes
    assert attrs["provider"] == "openai"
    assert attrs["model"] == "gpt-3.5-turbo"
    assert attrs["requested_model"] == "gpt-3.5-turbo"
    assert attrs["stub_mode"] is True


# ---------------------------------------------------------------------------
# 6. llm.fallback event recorded on provider failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_fallback_event_recorded_on_provider_failure(monkeypatch):
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    # Force the routed path off stub mode.
    monkeypatch.setenv("LLM_STUB_MODE", "false")

    from app.langgraph import llm as llm_module
    from app.services.router_service import Phase4RoutingDecision
    from datetime import datetime, timezone

    def _fresh_decision():
        return Phase4RoutingDecision(
            model="gpt-3.5-turbo",
            provider="openai",
            reason="primary",
            fallback_chain=["claude-3-haiku"],
            estimated_cost_usd=0.0,
            estimated_latency_ms=0.0,
            decision_at=datetime.now(timezone.utc),
        )

    async def _fake_route(*args, **kwargs):
        return _fresh_decision()

    async def _fake_record(*args, **kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        llm_module, "_provider_for",
        lambda m: "openai" if "gpt" in m else "anthropic",
    )
    monkeypatch.setattr(
        "app.services.router_service.route_request", _fake_route
    )
    monkeypatch.setattr(
        "app.services.provider_health.record_provider_call", _fake_record
    )

    call_count = {"n": 0}

    async def _fake_call_llm(prompt, **kwargs):  # noqa: ANN001
        call_count["n"] += 1
        # Fail the first model in the chain; succeed on second.
        model = kwargs.get("model") or ""
        if "gpt" in model and call_count["n"] == 1:
            raise RuntimeError("first model failed")
        return llm_module._stub_response(prompt, model or "stub")

    monkeypatch.setattr(llm_module, "call_llm", _fake_call_llm)

    # Wrap the routed call in our own span so the event has a parent
    # to attach to. (add_event is a no-op when no span is active.)
    from app.services.tracing import span

    async with span("test.outer", op="route"):
        response, final_decision = await llm_module.call_llm_routed(
            tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
            messages=[{"role": "user", "content": "hi"}],
            requested_model="gpt-3.5-turbo",
            session=None,
        )

    assert response is not None
    assert call_count["n"] == 2
    assert final_decision.reason.startswith("fallback_after_")

    by_name = _spans_by_name(exporter)
    outer = by_name["test.outer"][-1]
    fallback_events = [e for e in outer.events if e.name == "llm.fallback"]
    assert fallback_events, "llm.fallback event was not recorded"
    attrs = fallback_events[0].attributes
    assert attrs["failed_provider"] == "openai"
    assert attrs["failed_model"] == "gpt-3.5-turbo"


# ---------------------------------------------------------------------------
# 7. http.client span has url + method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_span_has_url_and_method(monkeypatch):
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    # Stub httpx.AsyncClient so the executor doesn't make a real call.
    class _StubResponse:
        status_code = 200
        headers: dict[str, str] = {}

        def json(self):  # noqa: ANN001
            return {"ok": True}

    class _StubClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN001
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args, **kwargs):  # noqa: ANN001
            return None

        async def request(self, *args, **kwargs):  # noqa: ANN001
            return _StubResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)

    from app.services.node_executors import NodeContext
    from app.services.node_executors.http_request import HTTPRequestNodeExecutor

    ctx = NodeContext(
        step_id="step-http",
        node_type="httpRequestNode",
        node_data={"config": {"method": "GET", "url": "https://example.invalid/x"}},
        inputs={},
        tenant_id="t-1",
        secrets=None,
        db_session=None,
    )
    result = await HTTPRequestNodeExecutor().execute(ctx)
    assert result.status == "completed"

    by_name = _spans_by_name(exporter)
    http_spans = by_name.get("http.client", [])
    assert http_spans, "http.client span was not recorded"
    attrs = http_spans[-1].attributes
    assert attrs["url"] == "https://example.invalid/x"
    assert attrs["method"] == "GET"
    assert attrs["http.status_code"] == 200
    assert attrs["step_id"] == "step-http"


# ---------------------------------------------------------------------------
# 8. tracing disabled when OTel unavailable — no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracing_disabled_when_OTEL_unavailable_no_op(monkeypatch):
    """Force the disabled path and assert the manager is a no-op."""
    from app.services import tracing as t

    monkeypatch.setattr(t, "_TRACING_AVAILABLE", False)

    assert t.is_tracing_enabled() is False

    async with t.span("nope", x=1) as s:
        # In no-op mode the manager yields None.
        assert s is None

    # add_event / set_attr must also be silent no-ops.
    t.add_event("ignored", a=1)
    t.set_attr("ignored", "value")


# ---------------------------------------------------------------------------
# 9. tenant_id propagates to spans (run_dispatcher path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_id_propagated_to_spans(monkeypatch):
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    from app.services import run_dispatcher

    async def _fake_inner(session, run, *, worker_id, correlation_id):
        # Open a child step span inside the run span so we verify
        # tenant_id is reachable from that depth (via the explicit
        # attribute we pass — OTel has no automatic propagation here).
        from app.services.tracing import span

        async with span(
            "workflow.step",
            run_id=str(run.id),
            tenant_id=str(run.tenant_id),
            step_id="s-tenant",
        ):
            pass

    monkeypatch.setattr(run_dispatcher, "_execute_claimed_run_inner", _fake_inner)

    run = _FakeRun()
    await run_dispatcher.execute_claimed_run(session=None, run=run, worker_id="w-tenant")

    by_name = _spans_by_name(exporter)
    run_attrs = by_name["workflow.run"][-1].attributes
    step_attrs = by_name["workflow.step"][-1].attributes
    assert run_attrs["tenant_id"] == str(run.tenant_id)
    assert step_attrs["tenant_id"] == str(run.tenant_id)


# ---------------------------------------------------------------------------
# 10. request middleware creates http.request span
# ---------------------------------------------------------------------------


def test_request_middleware_creates_http_span():
    exporter = _ensure_in_memory_exporter()
    if exporter is None:
        pytest.skip("OTel in-memory exporter not available")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.middleware.tracing_middleware import TracingMiddleware

    app = FastAPI()
    app.add_middleware(TracingMiddleware)

    @app.get("/ping")
    def _ping():
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.get("/ping")
        assert resp.status_code == 200

    by_name = _spans_by_name(exporter)
    req_spans = by_name.get("http.request", [])
    assert req_spans, "http.request span was not recorded"
    attrs = req_spans[-1].attributes
    assert attrs["http.method"] == "GET"
    assert attrs["http.route"] == "/ping"
    assert attrs["http.status_code"] == 200
