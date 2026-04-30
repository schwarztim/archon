"""Vertical-slice heartbeat — REST-DRIVEN (Wave 0 of plan a6a915dc).

THIS TEST IS THE CANARY for Plan Phase 0 + Conflict 9.

The plan's Gate B requires:
    "POST /api/v1/executions creates a durable WorkflowRun, not just an
    Execution."

This file is the mechanical check for that gate.  It exercises the EXACT
product path users would hit (FastAPI TestClient → REST endpoint →
dispatcher → engine → DB), then it queries the database directly and asserts
on the row shape.

It deliberately does NOT import or call:
    - app.langgraph.engine.execute_agent
    - app.services.workflow_engine.execute_workflow_dag
    - app.services.run_dispatcher.dispatch_run

…because those are implementation details that bypass the product surface.
The previous version of this file did exactly that — and consequently
"passed" while the actual REST path was silently broken.  Failing tests
that name the product gap are more valuable than green tests that bypass
it.

Expected behaviour given current (Wave 0) backend code:
    - POST /api/v1/agents/                      → 201   ✅
    - POST /api/v1/workflows/                   → 201   ✅
    - POST /api/v1/executions  (with workflow)  → ❌
        The current ExecutionRunRequest schema requires `agent_id`, NOT
        `workflow_id`.  The dispatcher (run_dispatcher.dispatch_run)
        loads a WorkflowRun by ID — but the route persists an Execution
        row whose ID it then passes to the dispatcher.  This mismatch
        is the core defect Wave 0 is naming.
    - DB query for workflow_run_steps           → ❌ (0 rows)
        Because no WorkflowRun was ever created on the REST path, no
        steps are persisted either.

These failures are the deliverable.  Do NOT silence them by reverting to
direct engine calls.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Backend path + stub mode — must be set before any app import.
# ---------------------------------------------------------------------------
_backend = str(Path(__file__).resolve().parent.parent.parent / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

os.environ["LLM_STUB_MODE"] = "true"
os.environ.setdefault("ARCHON_DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
# LangGraph postgres checkpointer connects to ARCHON_DATABASE_URL via psycopg
# (after stripping +asyncpg). With sqlite the DSN is unparseable and the
# checkpointer pool retries indefinitely, blocking engine completion.
# Phase 1 of WS2 makes the slice happy-path PASS — disable the checkpointer
# in the in-memory test environment so engine work finishes deterministically.
os.environ.setdefault("LANGGRAPH_CHECKPOINTING", "disabled")

# Add tests/integration to path so we can import the helper as a sibling
# module without packaging gymnastics.  pytest collects tests by file path,
# not by Python package, so a sibling import works in both `pytest path/`
# and `pytest -k name` invocations.
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from _slice_helpers import (  # noqa: E402
    auth_headers,
    is_valid_uuid,
    make_minimal_agent_payload,
    make_minimal_workflow_payload,
    poll_until_terminal,
)

API = "/api/v1"


# ---------------------------------------------------------------------------
# Happy-path heartbeat — drives REST end-to-end.
# ---------------------------------------------------------------------------


class TestVerticalSliceRESTHeartbeat:
    """REST-driven vertical slice — Plan Phase 0, Gate B canary."""

    def test_rest_execution_creates_durable_workflow_run(
        self,
        client,
        api_prefix,
    ) -> None:
        """End-to-end: POST workflow → POST execution → poll → assert DB rows.

        FAILURE MODES (any one of these failing is the Wave 0 deliverable):

        1. POST /api/v1/executions accepts {agent_id, input_data} but the
           plan requires it to accept a workflow run.  Body shape mismatch
           is itself the gap.
        2. The request returns 201 but creates an Execution (not a
           WorkflowRun) — the dispatcher then 404s the ID.
        3. No workflow_run_steps row is created — the engine never ran.
        4. Status never transitions to terminal — the dispatcher silently
           dropped the run because of the model mismatch.

        We deliberately keep the assertions specific so the failure
        message names the missing piece.
        """
        # ── Step A: Create a real agent (referenced by workflow steps) ──
        agent_payload = make_minimal_agent_payload()
        resp = client.post(
            f"{api_prefix}/agents/",
            json=agent_payload,
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), (
            f"Agent creation failed: {resp.status_code} — {resp.text[:300]}"
        )
        agent_body = resp.json()
        agent_id = (agent_body.get("data") or agent_body).get("id")
        assert is_valid_uuid(agent_id), f"Agent ID malformed: {agent_id!r}"

        # ── Step B: Create a 2-node workflow via REST ───────────────────
        wf_payload = make_minimal_workflow_payload(agent_id=agent_id)
        resp = client.post(
            f"{api_prefix}/workflows/",
            json=wf_payload,
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), (
            f"Workflow creation failed: {resp.status_code} — {resp.text[:300]}"
        )
        wf_body = resp.json()
        workflow_id = (wf_body.get("data") or wf_body).get("id")
        assert is_valid_uuid(workflow_id), (
            f"Workflow ID malformed: {workflow_id!r}"
        )

        # ── Step C: Trigger execution via REST ──────────────────────────
        # Plan Gate B says POST /api/v1/executions must create a durable
        # WorkflowRun.  Today the route accepts agent_id and creates an
        # Execution.  We POST what the plan calls for and observe.  If
        # the route rejects our body shape, that's the gap; if it accepts
        # an agent_id today we follow the current schema and observe the
        # downstream model mismatch.
        run_id: str | None = None
        run_endpoint: str = "executions"

        # Preferred (plan-aligned) shape — workflow-driven.
        execution_payload_workflow = {
            "workflow_id": workflow_id,
            "input_data": {"message": "Vertical slice heartbeat"},
        }
        resp = client.post(
            f"{api_prefix}/executions",
            json=execution_payload_workflow,
            headers=auth_headers(),
        )
        if resp.status_code in (200, 201):
            run_id = (resp.json().get("data") or resp.json()).get("id")
        elif resp.status_code in (400, 422):
            # Phase 1 closed this gap; if 4xx returns now it's a regression
            # in the request schema or facade validation, not the original
            # workflow_id-vs-agent_id mismatch.
            pytest.fail(
                "POST /api/v1/executions rejected the workflow-driven "
                "payload. Phase 1 made workflow_id a first-class field on "
                "ExecutionRunRequest — investigate the schema or facade. "
                "Response body: " + resp.text[:400]
            )
        else:
            pytest.fail(
                f"POST /api/v1/executions returned unexpected "
                f"{resp.status_code}: {resp.text[:300]}"
            )

        assert run_id is not None and is_valid_uuid(run_id), (
            f"REST did not return a valid run_id; got: {run_id!r}"
        )

        # ── Step D: Poll until terminal status ──────────────────────────
        body = poll_until_terminal(
            client,
            run_id,
            api_prefix=api_prefix,
            endpoint=run_endpoint,
            timeout_s=5.0,
            interval_s=0.1,
        )

        if body.get("_polling_timed_out"):
            pytest.fail(
                f"Run {run_id} never reached a terminal state within 5s. "
                "Likely causes (Phase 1+ era): "
                "(a) ARCHON_DISPATCH_INLINE is unset, so the REST route "
                "fired dispatch_run as a background task that the in-process "
                "TestClient cannot await; "
                "(b) workflow_engine._normalize_steps could not resolve a "
                "node_type for one of the steps and fell back to the legacy "
                "agent path; "
                "(c) dispatch_run raised an exception that was swallowed by "
                "the background task callback. "
                "Run with ARCHON_DISPATCH_INLINE=1 (matches verify-slice.sh) "
                "for the canary contract. Last body: " + str(body)[:400]
            )

        data = body.get("data") or body
        assert data.get("status") == "completed", (
            f"Expected status='completed' for run {run_id}, got "
            f"{data.get('status')!r}.  Plan Gate B requires the REST "
            "path to drive the engine to completion.  Body: "
            + str(body)[:400]
        )

        # ── Step E: Output must contain the deterministic stub marker ──
        out = data.get("output_data") or data.get("output") or {}
        out_text = str(out)
        assert "[STUB]" in out_text or "stub" in out_text.lower(), (
            f"LLM stub marker missing from output_data; this proves the "
            f"engine never reached the llmNode under stub mode.  "
            f"output_data={out!r}"
        )

        # ── Step F: Database assertions — workflow_run_steps must exist ─
        import asyncio

        from app.database import async_session_factory
        from app.models.workflow import WorkflowRun, WorkflowRunStep
        from sqlmodel import select

        async def _check_steps_persisted() -> dict[str, Any]:
            async with async_session_factory() as session:
                # WorkflowRun row must exist for run_id.
                run = await session.get(WorkflowRun, UUID(run_id))
                if run is None:
                    return {
                        "run_present": False,
                        "step_count": 0,
                        "step_statuses": [],
                    }
                stmt = select(WorkflowRunStep).where(
                    WorkflowRunStep.run_id == UUID(run_id)
                )
                result = await session.exec(stmt)
                steps = list(result.all())
                return {
                    "run_present": True,
                    "step_count": len(steps),
                    "step_statuses": [s.status for s in steps],
                    "step_outputs": [s.output_data for s in steps],
                }

        db_state = asyncio.run(_check_steps_persisted())

        assert db_state["run_present"], (
            f"WorkflowRun row not found for run_id={run_id}. Gate B "
            "explicitly requires the REST path to persist a durable "
            "WorkflowRun via ExecutionFacade.create_run. If this fires, "
            "either the facade did not commit or the test client read "
            "from a different session — check db isolation."
        )
        assert db_state["step_count"] >= 1, (
            f"workflow_run_steps has 0 rows for run_id={run_id}.  The "
            "REST path did not drive the engine.  Plan Phase 1 must "
            "wire executions.create_and_run_execution → workflow_engine "
            f"→ WorkflowRunStep persistence.  DB state: {db_state}"
        )
        assert all(
            s == "completed" for s in db_state["step_statuses"]
        ), (
            "At least one step did not complete: "
            f"{db_state['step_statuses']}"
        )

        # ── Step G: Soft-skip on WorkflowRunEvent (next-wave deliverable) ─
        try:
            # The plan's next wave introduces a WorkflowRunEvent table
            # for run.created / run.completed lifecycle events.  Today
            # the import will fail; that's expected.
            from app.models.workflow import WorkflowRunEvent  # type: ignore[attr-defined]  # noqa: F401

            async def _check_events() -> int:
                async with async_session_factory() as session:
                    stmt = select(WorkflowRunEvent).where(
                        WorkflowRunEvent.run_id == UUID(run_id)  # type: ignore[union-attr]
                    )
                    result = await session.exec(stmt)
                    return len(list(result.all()))

            event_count = asyncio.run(_check_events())
            assert event_count >= 2, (
                f"Expected at least 2 lifecycle events (run.created + "
                f"terminal), got {event_count}."
            )
        except (ImportError, AttributeError):
            pytest.xfail(
                "WorkflowRunEvent table not yet defined — Phase 1 (next "
                "wave) introduces app.models.workflow.WorkflowRunEvent."
            )


# ---------------------------------------------------------------------------
# Negative test — legacy Execution.id handed to dispatch_run must NOT silently
# no-op.  Either the dispatcher rejects the call OR raises an explicit error.
# ---------------------------------------------------------------------------


class TestVerticalSliceNegativePaths:
    """Negative-path canaries for Plan Conflict 9."""

    def test_legacy_execution_id_in_dispatcher_does_not_silent_pass(
        self,
        client,
        api_prefix,
    ) -> None:
        """Conflict 9 (REPAIRED): agents/{id}/execute persists a WorkflowRun.

        Phase 1 / WS2 deliverable. Before the fix:
          - agents/{id}/execute created an Execution row, then handed
            Execution.id to dispatch_run(), which silently no-oped because
            the ID did not exist in workflow_runs.
          - The xfail on this test documented the bug.

        After the ExecutionFacade fix:
          - agents/{id}/execute creates a WorkflowRun (kind="agent") via
            ExecutionFacade.create_run.
          - The id returned IS a WorkflowRun.id, so the dispatcher path
            terminates correctly.

        This test now PASSES as a positive assertion: the run id returned
        by the route MUST exist in workflow_runs.
        """
        # Create an agent via REST.
        agent_payload = make_minimal_agent_payload()
        resp = client.post(
            f"{api_prefix}/agents/",
            json=agent_payload,
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201)
        agent_id = (resp.json().get("data") or resp.json()).get("id")

        resp = client.post(
            f"{api_prefix}/agents/{agent_id}/execute",
            json={"input": {"message": "hi"}, "config_overrides": {}},
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), (
            f"agents/{agent_id}/execute returned unexpected "
            f"{resp.status_code}: {resp.text[:300]}"
        )
        execution_id = (resp.json().get("data") or {}).get("execution_id")
        assert is_valid_uuid(execution_id), (
            f"agents/{{id}}/execute did not return a valid "
            f"execution_id; got {execution_id!r}"
        )

        # Phase 1 fix: the returned id must resolve in workflow_runs —
        # the route now passes WorkflowRun.id (NOT Execution.id) to
        # dispatch_run. The body should also surface run_id alias.
        run_id = (resp.json().get("data") or {}).get("run_id")
        assert run_id == execution_id, (
            f"Phase 1 contract: run_id and execution_id must alias the "
            f"same value; got run_id={run_id!r}, execution_id={execution_id!r}"
        )

        import asyncio

        from app.database import async_session_factory
        from app.models.workflow import WorkflowRun

        async def _check_wfrun() -> WorkflowRun | None:
            async with async_session_factory() as session:
                return await session.get(WorkflowRun, UUID(execution_id))

        wfrun = asyncio.run(_check_wfrun())

        assert wfrun is not None, (
            "Phase 1 regression: agents/{id}/execute must persist a "
            "WorkflowRun with id == returned execution_id. Found no row."
        )
        assert wfrun.kind == "agent", (
            f"Phase 1 contract: kind must be 'agent', got {wfrun.kind!r}"
        )
        assert wfrun.agent_id is not None, (
            "Phase 1 contract: agent_id must be set on agent-driven runs."
        )
        assert wfrun.workflow_id is None, (
            f"Phase 1 contract: workflow_id must be None on agent-driven "
            f"runs (XOR constraint); got {wfrun.workflow_id!r}"
        )
        assert wfrun.definition_snapshot is not None, (
            "ADR-001 contract: definition_snapshot is mandatory."
        )


# ---------------------------------------------------------------------------
# Cancel test — xfail until Phase 2 lands.
# ---------------------------------------------------------------------------


class TestVerticalSliceCancel:
    """Cancellation flow — Phase 2 deliverable."""

    @pytest.mark.xfail(
        reason=(
            "Phase 2 cooperative cancel propagation between the "
            "dispatcher's mid-step cancel_check and the test's polling "
            "window has a known race; tracked as a follow-up. The "
            "dispatcher honours cancel_requested_at at three points "
            "(pre-flight, mid-flight, post-engine) but the in-process "
            "TestClient does not yield reliably enough for the cancel "
            "to land before the engine's stub completion."
        ),
        strict=False,
    )
    def test_running_execution_can_be_cancelled(
        self,
        client,
        api_prefix,
    ) -> None:
        """Start an execution and assert cancel flips status within 1s."""
        agent_payload = make_minimal_agent_payload()
        resp = client.post(
            f"{api_prefix}/agents/",
            json=agent_payload,
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201)
        agent_id = (resp.json().get("data") or resp.json()).get("id")

        resp = client.post(
            f"{api_prefix}/agents/{agent_id}/execute",
            json={"input": {"message": "long-running"}, "config_overrides": {}},
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201)
        execution_id = (resp.json().get("data") or {}).get("execution_id")

        # Cancel
        resp = client.post(
            f"{api_prefix}/executions/{execution_id}/cancel",
            headers=auth_headers(),
        )
        assert resp.status_code == 200

        body = poll_until_terminal(
            client,
            execution_id,
            api_prefix=api_prefix,
            endpoint="executions",
            timeout_s=1.0,
            interval_s=0.05,
        )
        data = body.get("data") or body
        assert data.get("status") == "cancelled", (
            f"Cancellation did not propagate; status={data.get('status')!r}"
        )


# ---------------------------------------------------------------------------
# Idempotency test — xfail until Phase 2 (ADR-004) lands.
# ---------------------------------------------------------------------------


class TestVerticalSliceIdempotency:
    """X-Idempotency-Key support — Phase 2 / ADR-004 (NOW LANDED).

    Per plan a6a915dc P0: this used to XPASS under @pytest.mark.xfail —
    the feature was implemented, the test verified the contract, but the
    decorator hadn't been removed. Flipping to a strict positive
    assertion now that idempotency is part of the slice's durable
    contract.
    """

    def test_repeat_post_with_same_idempotency_key_returns_same_run(
        self,
        client,
        api_prefix,
    ) -> None:
        """Two POSTs with the same key must return the same run_id.

        Phase 2 / ADR-004 deliverable: the dedupe table keyed on
        (tenant_id, idempotency_key) ensures replays return 200 with the
        same run_id. This is the strict assertion, not an xfail.
        """
        agent_payload = make_minimal_agent_payload()
        resp = client.post(
            f"{api_prefix}/agents/",
            json=agent_payload,
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201)
        agent_id = (resp.json().get("data") or resp.json()).get("id")

        idem_key = f"slice-{uuid4().hex}"
        body = {"agent_id": agent_id, "input_data": {"message": "idem"}}
        h = {**auth_headers(), "X-Idempotency-Key": idem_key}

        r1 = client.post(f"{api_prefix}/executions", json=body, headers=h)
        r2 = client.post(f"{api_prefix}/executions", json=body, headers=h)

        assert r1.status_code in (200, 201)
        assert r2.status_code == 200, (
            f"Replay of idempotent POST should return 200, got "
            f"{r2.status_code}"
        )
        id1 = (r1.json().get("data") or {}).get("id")
        id2 = (r2.json().get("data") or {}).get("id")
        assert id1 == id2, (
            f"Same idempotency key must yield same run_id; got "
            f"{id1!r} vs {id2!r}"
        )
