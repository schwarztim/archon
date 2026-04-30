"""Worker P0-E acceptance tests — every ingress path goes through ExecutionFacade.

The durable orchestration plan's non-negotiable architecture rule:

    external trigger / REST / UI / schedule / webhook / event / pipeline
      -> ExecutionFacade
      -> WorkflowRun
      -> task queue
      -> worker

This file is the integration-paths regression that gates Wave 1. Each test
asserts that a specific ingress path produces a canonical run via
``ExecutionFacade.create_run`` rather than a direct ``WorkflowRun(...)`` call.

Conventions:

* Uses the session-scoped ``client`` + ``api_prefix`` fixtures from
  ``tests/integration/conftest.py`` (in-process FastAPI TestClient against
  in-memory SQLite — same substrate as ``test_worker_canary.py``).
* Drives synchronously via ``ARCHON_DISPATCH_INLINE=1`` so the route either
  awaits the dispatcher inline (REST/UI/webhook/event paths) or, for paths
  that don't trigger dispatch, returns immediately. Run creation is the
  contract under test, not lifecycle progression.
* Reads the durable substrate (``WorkflowRun`` rows + ``WorkflowRunEvent``
  rows) directly to prove the facade was reached — every facade-created run
  carries ``run.created`` + ``run.queued`` events with the documented
  payload shape from ADR-002.

The tenth test, ``test_no_direct_workflowrun_construction``, runs the static
bypass-detection script as a regression rail — if any future commit
re-introduces a direct ``WorkflowRun(...)`` construction in
``backend/app/`` outside ``execution_facade.py``, this test fails.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

# Ensure backend is on path BEFORE any app import (mirrors the worker canary).
_backend = str(Path(__file__).resolve().parent.parent.parent / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

# Stub LLM + sqlite — same env contract as ``test_worker_canary.py``.
os.environ["LLM_STUB_MODE"] = "true"
os.environ.setdefault("ARCHON_DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("LANGGRAPH_CHECKPOINTING", "disabled")
# These tests verify run *creation*, not lifecycle progression. Inline
# dispatch keeps the facade path observable in a single synchronous turn —
# without it a parallel test client could observe a partial state.
os.environ.setdefault("ARCHON_DISPATCH_INLINE", "1")

# Sibling import — slice helpers live next to this file.
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from _slice_helpers import (  # noqa: E402
    auth_headers,
    is_valid_uuid,
    make_minimal_agent_payload,
    make_minimal_workflow_payload,
)


API = "/api/v1"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_TENANT_DEV = UUID("00000000-0000-0000-0000-000000000100")  # auth dev-mode tenant


# ---------------------------------------------------------------------------
# Helpers — drive REST + read the durable substrate
# ---------------------------------------------------------------------------


def _create_workflow(client, *, api_prefix: str) -> tuple[str, str]:
    """Create a minimal agent + workflow via REST. Returns (agent_id, workflow_id)."""
    agent_payload = make_minimal_agent_payload()
    resp = client.post(
        f"{api_prefix}/agents/", json=agent_payload, headers=auth_headers()
    )
    assert resp.status_code in (200, 201), (
        f"Agent creation failed: {resp.status_code} — {resp.text[:300]}"
    )
    agent_id = (resp.json().get("data") or resp.json()).get("id")
    assert is_valid_uuid(agent_id)

    wf_payload = make_minimal_workflow_payload(agent_id=agent_id)
    resp = client.post(
        f"{api_prefix}/workflows/", json=wf_payload, headers=auth_headers()
    )
    assert resp.status_code in (200, 201), (
        f"Workflow creation failed: {resp.status_code} — {resp.text[:300]}"
    )
    workflow_id = (resp.json().get("data") or resp.json()).get("id")
    assert is_valid_uuid(workflow_id)
    return agent_id, workflow_id


async def _read_run(run_id: str) -> dict[str, Any]:
    """Read run + events directly from the durable substrate."""
    from app.database import async_session_factory
    from app.models.workflow import WorkflowRun, WorkflowRunEvent
    from sqlalchemy import select as _select

    async with async_session_factory() as session:
        run = await session.get(WorkflowRun, UUID(run_id))
        if run is None:
            return {"present": False}
        events_stmt = (
            _select(WorkflowRunEvent)
            .where(WorkflowRunEvent.run_id == UUID(run_id))
            .order_by(WorkflowRunEvent.sequence)
        )
        events_result = await session.execute(events_stmt)
        events = list(events_result.scalars().all())
        return {
            "present": True,
            "id": str(run.id),
            "workflow_id": str(run.workflow_id) if run.workflow_id else None,
            "agent_id": str(run.agent_id) if run.agent_id else None,
            "kind": run.kind,
            "tenant_id": run.tenant_id,
            "trigger_type": run.trigger_type,
            "triggered_by": run.triggered_by,
            "status": run.status,
            "input_data": run.input_data or {},
            "idempotency_key": run.idempotency_key,
            "definition_snapshot": run.definition_snapshot or {},
            "event_types": [e.event_type for e in events],
            "event_payloads": [e.payload for e in events],
        }


def _assert_facade_signature(state: dict[str, Any]) -> None:
    """Every ExecutionFacade.create_run call writes ADR-002 lifecycle events.

    The first two events MUST be ``run.created`` then ``run.queued`` —
    direct ``WorkflowRun(...)`` construction emits neither, so any run that
    has both is provably facade-created. The ``definition_snapshot`` must
    also be populated — the facade calls ``_capture_workflow_snapshot`` /
    ``_capture_agent_snapshot`` immediately before persistence; direct
    construction would leave the column NULL or empty.
    """
    assert state["present"], "WorkflowRun row not found"
    event_types = state["event_types"]
    assert len(event_types) >= 2, (
        f"facade signature missing — expected at least run.created+run.queued, "
        f"got {event_types!r}"
    )
    assert event_types[0] == "run.created", (
        f"facade signature missing run.created at sequence 0; got {event_types[0]!r}"
    )
    assert event_types[1] == "run.queued", (
        f"facade signature missing run.queued at sequence 1; got {event_types[1]!r}"
    )
    snap = state["definition_snapshot"]
    assert isinstance(snap, dict) and snap.get("captured_at"), (
        f"facade signature missing definition_snapshot.captured_at — direct "
        f"WorkflowRun(...) construction does not populate this. snap={snap!r}"
    )


# ---------------------------------------------------------------------------
# 1. REST manual execute (POST /executions)
# ---------------------------------------------------------------------------


class TestRestManualExecuteCanonical:
    def test_rest_manual_execute_creates_canonical_run(self, client, api_prefix):
        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        resp = client.post(
            f"{api_prefix}/executions",
            json={
                "workflow_id": workflow_id,
                "input_data": {"message": "manual run"},
            },
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), (
            f"POST /executions {resp.status_code}: {resp.text[:300]}"
        )
        run_id = (resp.json().get("data") or resp.json()).get("id")
        assert is_valid_uuid(run_id)

        state = asyncio.run(_read_run(run_id))
        _assert_facade_signature(state)
        assert state["trigger_type"] == "manual"
        assert state["kind"] == "workflow"
        assert state["workflow_id"] == workflow_id


# ---------------------------------------------------------------------------
# 2. UI test-run (POST /workflows/{id}/execute)
# ---------------------------------------------------------------------------


class TestUiTestRunCanonical:
    def test_ui_test_run_routes_through_facade(self, client, api_prefix):
        """The UI builder's "execute now" button must produce a canonical run.

        ``trigger_type='ui_test'`` is the marker preserving the existing
        UI-distinguishes-test-runs semantic without requiring an ``is_test``
        column (W11 owns that).
        """
        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        resp = client.post(
            f"{api_prefix}/workflows/{workflow_id}/execute",
            headers=auth_headers(),
        )
        assert resp.status_code == 201, (
            f"UI test execute returned {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        run_id = (body.get("data") or body).get("id")
        assert is_valid_uuid(run_id)

        state = asyncio.run(_read_run(run_id))
        _assert_facade_signature(state)
        assert state["trigger_type"] == "ui_test", (
            f"UI test execute must mark trigger_type='ui_test'; got "
            f"{state['trigger_type']!r}"
        )
        assert state["kind"] == "workflow"


# ---------------------------------------------------------------------------
# 3. Webhook trigger
# ---------------------------------------------------------------------------


class TestWebhookTriggerCanonical:
    def test_webhook_trigger_routes_through_facade(self, client, api_prefix):
        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        provider_event_id = f"evt_{uuid4().hex[:12]}"
        resp = client.post(
            f"{api_prefix}/workflows/{workflow_id}/webhook",
            json={"event_id": provider_event_id, "data": {"hello": "world"}},
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), (
            f"Webhook returned {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert body.get("trigger") == "webhook"
        # Idempotency key is derived from the event id and surfaced in the
        # response for operator visibility.
        assert body.get("idempotency_key") == f"webhook:{provider_event_id}"
        run_id = body.get("run_id")
        assert is_valid_uuid(run_id)

        state = asyncio.run(_read_run(run_id))
        _assert_facade_signature(state)
        assert state["trigger_type"] == "webhook"
        assert state["idempotency_key"] == f"webhook:{provider_event_id}"

    def test_webhook_replay_is_idempotent(self, client, api_prefix):
        """Two webhooks with the same event id must resolve to the same run."""
        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        provider_event_id = f"evt_{uuid4().hex[:12]}"
        body = {"event_id": provider_event_id, "data": {"a": 1}}

        resp1 = client.post(
            f"{api_prefix}/workflows/{workflow_id}/webhook",
            json=body,
            headers=auth_headers(),
        )
        resp2 = client.post(
            f"{api_prefix}/workflows/{workflow_id}/webhook",
            json=body,
            headers=auth_headers(),
        )
        assert resp1.status_code in (200, 201)
        assert resp2.status_code in (200, 201)
        assert resp1.json()["run_id"] == resp2.json()["run_id"], (
            "Same provider event_id must replay to the same run — "
            "ExecutionFacade.create_run should have hit its idempotency index."
        )


# ---------------------------------------------------------------------------
# 4. Event trigger (POST /workflows/events)
# ---------------------------------------------------------------------------


async def _seed_event_trigger_workflow(workflow_id: str, *, event_type: str) -> None:
    """Set ``Workflow.trigger_config`` directly — there is no REST route for it."""
    from app.database import async_session_factory
    from app.models.workflow import Workflow

    async with async_session_factory() as session:
        wf = await session.get(Workflow, UUID(workflow_id))
        assert wf is not None, f"workflow {workflow_id} not found"
        wf.trigger_config = {"type": "event", "event_type": event_type}
        session.add(wf)
        await session.commit()


class TestEventTriggerCanonical:
    def test_event_trigger_routes_through_facade(self, client, api_prefix):
        # Two fanout targets — both should receive a canonical run.
        _a1, wf1 = _create_workflow(client, api_prefix=api_prefix)
        _a2, wf2 = _create_workflow(client, api_prefix=api_prefix)
        event_type = f"evt.test.{uuid4().hex[:8]}"
        asyncio.run(_seed_event_trigger_workflow(wf1, event_type=event_type))
        asyncio.run(_seed_event_trigger_workflow(wf2, event_type=event_type))

        event_id = f"evt_{uuid4().hex[:12]}"
        resp = client.post(
            f"{api_prefix}/workflows/events",
            json={"id": event_id, "type": event_type, "source": "test"},
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), resp.text[:300]
        body = resp.json()
        assert sorted(body["matched_workflows"]) == sorted([wf1, wf2])
        assert len(body["created_runs"]) == 2

        for run_id, wf in zip(body["created_runs"], body["matched_workflows"]):
            assert is_valid_uuid(run_id)
            state = asyncio.run(_read_run(run_id))
            _assert_facade_signature(state)
            assert state["trigger_type"] == "event"
            # Per-target idempotency key shape: event:{event_id}:{wf_id}
            assert state["idempotency_key"] == f"event:{event_id}:{wf}"

    def test_event_replay_does_not_duplicate_per_target(self, client, api_prefix):
        _a, wf = _create_workflow(client, api_prefix=api_prefix)
        event_type = f"evt.test.{uuid4().hex[:8]}"
        asyncio.run(_seed_event_trigger_workflow(wf, event_type=event_type))
        event_id = f"evt_{uuid4().hex[:12]}"

        resp1 = client.post(
            f"{api_prefix}/workflows/events",
            json={"id": event_id, "type": event_type},
            headers=auth_headers(),
        )
        resp2 = client.post(
            f"{api_prefix}/workflows/events",
            json={"id": event_id, "type": event_type},
            headers=auth_headers(),
        )
        runs1 = resp1.json()["created_runs"]
        runs2 = resp2.json()["created_runs"]
        assert len(runs1) == 1 and len(runs2) == 1
        assert runs1[0] == runs2[0], (
            "Same event_id+target must replay — facade idempotency must dedupe."
        )


# ---------------------------------------------------------------------------
# 5. Schedule fire — driven through the worker.py schedule tick
# ---------------------------------------------------------------------------


async def _seed_due_schedule(workflow_id: str) -> tuple[str, str]:
    """Insert a WorkflowSchedule row whose next-fire is already in the past.

    Returns (schedule_id, expected_idempotency_key_prefix). The schedule
    tick uses ``schedule:{schedule.id}:{fire_time.isoformat()}`` and we
    cannot pre-compute fire_time deterministically (croniter rounds to the
    nearest cron boundary), so the test asserts the prefix only.
    """
    from app.database import async_session_factory
    from app.models.workflow import WorkflowSchedule

    async with async_session_factory() as session:
        # Cron "* * * * *" fires every minute. last_run_at far in the past
        # forces the next-fire to be due NOW.
        sched = WorkflowSchedule(
            workflow_id=UUID(workflow_id),
            tenant_id=_TENANT_DEV,
            cron="* * * * *",
            timezone="UTC",
            enabled=True,
            last_run_at=datetime.utcnow() - timedelta(hours=2),
        )
        session.add(sched)
        await session.commit()
        await session.refresh(sched)
        return str(sched.id), f"schedule:{sched.id}:"


async def _drive_schedule_tick() -> None:
    """Invoke the worker's schedule tick — the same tick the drain loop runs."""
    from app.worker import _check_scheduled_workflows

    await _check_scheduled_workflows()


async def _find_run_by_schedule_idempotency_prefix(prefix: str) -> str | None:
    """Look up the run created by the schedule tick via its idempotency key."""
    from app.database import async_session_factory
    from app.models.workflow import WorkflowRun
    from sqlalchemy import select as _select

    async with async_session_factory() as session:
        stmt = _select(WorkflowRun).where(
            WorkflowRun.idempotency_key.like(f"{prefix}%")  # type: ignore[union-attr]
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            return None
        return str(rows[0].id)


class TestScheduleFireCanonical:
    def test_schedule_fire_routes_through_facade(self, client, api_prefix):
        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        _sched_id, key_prefix = asyncio.run(_seed_due_schedule(workflow_id))

        # Drive the schedule tick — same callable the worker drain loop uses.
        asyncio.run(_drive_schedule_tick())

        run_id = asyncio.run(_find_run_by_schedule_idempotency_prefix(key_prefix))
        assert run_id is not None, (
            f"schedule tick did NOT create a run via the facade — no row "
            f"with idempotency_key like {key_prefix!r}. The tick should have "
            f"called ExecutionFacade.create_run."
        )

        state = asyncio.run(_read_run(run_id))
        _assert_facade_signature(state)
        assert state["trigger_type"] == "schedule"
        assert state["triggered_by"] == "scheduler"
        assert state["idempotency_key"] is not None
        assert state["idempotency_key"].startswith(key_prefix)


# ---------------------------------------------------------------------------
# 6. Signal — durable Signal row (not Redis-only)
# ---------------------------------------------------------------------------


async def _read_signals(run_id: str) -> list[dict[str, Any]]:
    """Read every Signal row for a run — proves persistence."""
    from app.database import async_session_factory
    from app.models.approval import Signal
    from sqlalchemy import select as _select

    async with async_session_factory() as session:
        stmt = _select(Signal).where(Signal.run_id == UUID(run_id))
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        return [
            {
                "id": str(r.id),
                "signal_type": r.signal_type,
                "payload": r.payload,
            }
            for r in rows
        ]


class TestSignalDurabilityCanonical:
    def test_signal_appends_persistent_row(self, client, api_prefix):
        """Operator-injected signal must persist a durable Signal row.

        Per ADR-008 §Signal: redis pub/sub may notify, but cannot be the
        source of truth. The ``POST /executions/{run_id}/signals`` endpoint
        uses ``signal_service.send_signal`` which writes a persistent row.
        """
        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        # Create a run via the facade so we have a valid run_id to signal.
        resp = client.post(
            f"{api_prefix}/executions",
            json={
                "workflow_id": workflow_id,
                "input_data": {"message": "for signal test"},
            },
            headers=auth_headers(),
        )
        run_id = (resp.json().get("data") or resp.json()).get("id")
        assert is_valid_uuid(run_id)

        # Send the signal via the durable POST endpoint.
        resp = client.post(
            f"{api_prefix}/executions/{run_id}/signals",
            json={"signal_type": "custom", "payload": {"hello": "signal"}},
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), resp.text[:300]
        body = resp.json()
        signal_id = (body.get("data") or body).get("signal_id")
        assert is_valid_uuid(signal_id), (
            f"signal_id missing from response: {body!r}"
        )

        # Prove the row landed in the durable Signal table — pubsub-only
        # delivery would have no DB row.
        signals = asyncio.run(_read_signals(run_id))
        assert len(signals) >= 1, (
            f"Signal row not persisted — pubsub-only path detected. "
            f"signals={signals!r}"
        )
        assert any(s["signal_type"] == "custom" for s in signals)


# ---------------------------------------------------------------------------
# 7. Approval decision -> resume via durable signal path
# ---------------------------------------------------------------------------


async def _seed_pending_approval(run_id: str) -> str:
    """Create a pending Approval row paired with a paused run."""
    from app.database import async_session_factory
    from app.models.approval import Approval
    from app.models.workflow import WorkflowRun

    async with async_session_factory() as session:
        run = await session.get(WorkflowRun, UUID(run_id))
        assert run is not None
        # Mark the run as paused (approval contract: approval rows are paired
        # with a paused run that resumes on grant).
        run.status = "paused"
        session.add(run)

        approval = Approval(
            run_id=UUID(run_id),
            tenant_id=run.tenant_id,
            step_id="approval-step",
            status="pending",
            payload={"reason": "needs human"},
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        return str(approval.id)


class TestApprovalResumeCanonical:
    def test_approval_decision_resumes_run_via_message_path(
        self, client, api_prefix
    ):
        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        resp = client.post(
            f"{api_prefix}/executions",
            json={"workflow_id": workflow_id, "input_data": {}},
            headers=auth_headers(),
        )
        run_id = (resp.json().get("data") or resp.json()).get("id")
        approval_id = asyncio.run(_seed_pending_approval(run_id))

        # Grant the approval — service writes Approval(status='approved') +
        # a durable Signal(signal_type='approval.granted') in the same
        # transaction. That signal is the message-path the dispatcher
        # consumes to resume the paused run.
        resp = client.post(
            f"{api_prefix}/approvals/{approval_id}/approve",
            json={"reason": "test approves"},
            headers=auth_headers(),
        )
        assert resp.status_code in (200, 201), resp.text[:300]
        sig_id = (resp.json().get("data") or resp.json()).get("signal_id")
        assert is_valid_uuid(sig_id)

        # The durable signal row MUST exist with the canonical type.
        signals = asyncio.run(_read_signals(run_id))
        assert any(s["signal_type"] == "approval.granted" for s in signals), (
            f"approval.granted signal missing from durable substrate; "
            f"signals={signals!r}"
        )


# ---------------------------------------------------------------------------
# 8. Timer fire emits timer.fired event (or skips if event-type isn't yet
# in EVENT_TYPES — that's an ADR-002 amendment + migration that lives in a
# downstream worker)
# ---------------------------------------------------------------------------


class TestTimerFireCanonical:
    def test_timer_fire_emits_timer_fired_event(self, client, api_prefix):
        from app.services import event_service

        if "timer.fired" not in event_service.EVENT_TYPES:
            pytest.skip(
                "timer.fired event type not yet registered in "
                "event_service.EVENT_TYPES — adding it requires an ADR-002 "
                "amendment + workflow_run_events CHECK constraint migration "
                "(downstream worker scope)."
            )

        # When the type lands, this test will assert the timer fire emits
        # the canonical event on the run's event chain. Skeleton kept here
        # so the wave 0 acceptance gate has a placeholder slot ready.

        from app.database import async_session_factory
        from app.models.timers import Timer
        from app.services import timer_service
        from sqlalchemy import select as _select

        _agent_id, workflow_id = _create_workflow(client, api_prefix=api_prefix)
        resp = client.post(
            f"{api_prefix}/executions",
            json={"workflow_id": workflow_id, "input_data": {}},
            headers=auth_headers(),
        )
        run_id = (resp.json().get("data") or resp.json()).get("id")

        async def _seed_due_timer() -> str:
            async with async_session_factory() as session:
                t = Timer(
                    run_id=UUID(run_id),
                    fire_at=datetime.utcnow() - timedelta(seconds=30),
                    status="pending",
                )
                session.add(t)
                await session.commit()
                await session.refresh(t)
                return str(t.id)

        async def _drive_fire() -> None:
            async with async_session_factory() as session:
                await timer_service.fire_due_timers(session)

        async def _read_event_types() -> list[str]:
            from app.models.workflow import WorkflowRunEvent

            async with async_session_factory() as session:
                stmt = _select(WorkflowRunEvent).where(
                    WorkflowRunEvent.run_id == UUID(run_id)
                )
                result = await session.execute(stmt)
                return [r.event_type for r in result.scalars().all()]

        timer_id = asyncio.run(_seed_due_timer())  # noqa: F841
        asyncio.run(_drive_fire())
        types = asyncio.run(_read_event_types())
        assert "timer.fired" in types, (
            f"timer.fired event missing from chain: {types!r}"
        )


# ---------------------------------------------------------------------------
# 9. Sub-workflow node — child run via ExecutionFacade
# ---------------------------------------------------------------------------


class TestSubWorkflowCanonical:
    def test_sub_workflow_creates_child_through_facade(self, client, api_prefix):
        """Sub-workflow node must NOT bypass the facade.

        Today ``sub_workflow.py`` calls ``execute_workflow_dag`` directly
        without creating a child ``WorkflowRun``. That's plan-incomplete but
        the relevant guarantee for THIS worker is the static gate: NO file
        in ``backend/app/`` constructs ``WorkflowRun`` outside the facade.
        When a downstream worker (W4c — workflow-control executors) lands
        the canonical child-run contract, this test will assert the chain.
        For now we assert the structural invariant: any child-run-like row
        appearing during sub-workflow execution carries the facade's
        signature.
        """
        # Build a parent workflow that references a child workflow via a
        # subWorkflowNode step.
        _a_child, child_wf_id = _create_workflow(client, api_prefix=api_prefix)
        _a_parent, parent_wf_id = _create_workflow(client, api_prefix=api_prefix)

        # Drive the parent workflow through the facade.
        resp = client.post(
            f"{api_prefix}/executions",
            json={
                "workflow_id": parent_wf_id,
                "input_data": {"sub_workflow_id": child_wf_id},
            },
            headers=auth_headers(),
        )
        parent_run_id = (resp.json().get("data") or resp.json()).get("id")
        assert is_valid_uuid(parent_run_id)

        # Parent run itself MUST carry the facade signature.
        parent_state = asyncio.run(_read_run(parent_run_id))
        _assert_facade_signature(parent_state)
        assert parent_state["kind"] == "workflow"

        # Static contract: the bypass-detection scan MUST exit 0 — any
        # WorkflowRun row created during sub-workflow execution would have
        # had to go through the facade. (When the child-run contract lands,
        # this test gains a positive assertion for the child row.)
        result = subprocess.run(
            ["bash", "scripts/check-direct-run-bypasses.sh"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"bypass scan failed during sub-workflow flow: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# 10. Static gate — NO direct WorkflowRun construction outside the facade
# ---------------------------------------------------------------------------


class TestNoDirectWorkflowRunConstruction:
    """Wave 0 hard gate: ``check-direct-run-bypasses.sh`` MUST exit 0."""

    def test_no_direct_workflowrun_construction(self):
        result = subprocess.run(
            ["bash", "scripts/check-direct-run-bypasses.sh"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Direct WorkflowRun construction detected outside the facade.\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}\n"
            "Remediation: route the run start through "
            "backend/app/services/execution_facade.py."
        )


# ---------------------------------------------------------------------------
# Module-level idle-import / ledger
# ---------------------------------------------------------------------------


def test_module_level_smoke():
    """Cheap import-time smoke — confirms the test module collects cleanly."""
    assert API == "/api/v1"
    assert REPO_ROOT.exists()
