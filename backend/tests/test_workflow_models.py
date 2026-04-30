"""Tests for the unified WorkflowRun + WorkflowRunEvent schema.

Covers ADR-001 (XOR constraint, snapshot required), ADR-002 (event chain
integrity, sequence uniqueness, canonical JSON determinism), ADR-004
(idempotency partial unique index).

All tests use an in-memory SQLite engine — zero external dependencies.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

# Import all models so SQLModel.metadata is fully populated before any
# create_all (otherwise FKs to other tables fail at table-create time).
from app.models import (  # noqa: F401
    Agent,
    Execution,
    User,
)
from app.models.workflow import (
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStep,
)
from app.services.event_service import (
    EVENT_TYPES,
    append_event,
    canonical_json,
    compute_hash,
    verify_hash_chain,
)


# ── Helpers ────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """Fresh in-memory SQLite engine with all tables created.

    Each test gets its own engine so state is isolated. Foreign-key
    enforcement is enabled explicitly so CHECK + FK constraints fire
    the way they will in production.
    """
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Enable FK + CHECK enforcement on SQLite.
    with eng.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


def _seed_workflow(session: Session) -> Workflow:
    """Insert a minimal Workflow row for FK satisfaction."""
    wf = Workflow(name="t-wf", steps=[], graph_definition={})
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return wf


def _seed_agent(session: Session) -> Agent:
    """Insert a minimal Agent row for FK satisfaction."""
    owner = User(email=f"u{uuid4().hex[:6]}@x.test", name="t")
    session.add(owner)
    session.commit()
    session.refresh(owner)
    ag = Agent(name="t-ag", definition={"k": "v"}, owner_id=owner.id)
    session.add(ag)
    session.commit()
    session.refresh(ag)
    return ag


# ── ADR-001: XOR constraint on (workflow_id, agent_id) ─────────────────


def test_xor_constraint_rejects_both_null(session: Session) -> None:
    """A WorkflowRun with neither workflow_id nor agent_id is rejected."""
    run = WorkflowRun(
        kind="workflow",
        definition_snapshot={"_test": "both-null"},
    )
    session.add(run)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_xor_constraint_rejects_both_set(session: Session) -> None:
    """A WorkflowRun with both workflow_id AND agent_id is rejected."""
    wf = _seed_workflow(session)
    ag = _seed_agent(session)
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        agent_id=ag.id,
        definition_snapshot={"_test": "both-set"},
    )
    session.add(run)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_xor_constraint_accepts_workflow_only(session: Session) -> None:
    """A workflow-kind run with workflow_id set and agent_id null commits."""
    wf = _seed_workflow(session)
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        definition_snapshot={"snapshot": "wf"},
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    assert run.id is not None
    assert run.workflow_id == wf.id
    assert run.agent_id is None


def test_xor_constraint_accepts_agent_only(session: Session) -> None:
    """An agent-kind run with agent_id set and workflow_id null commits."""
    ag = _seed_agent(session)
    run = WorkflowRun(
        kind="agent",
        agent_id=ag.id,
        definition_snapshot={"snapshot": "ag"},
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    assert run.id is not None
    assert run.agent_id == ag.id
    assert run.workflow_id is None


# ── ADR-001: definition_snapshot is mandatory ──────────────────────────


def test_definition_snapshot_required(session: Session) -> None:
    """definition_snapshot=None must fail at commit."""
    wf = _seed_workflow(session)
    # Bypass the model-level type check by inserting via raw dict.
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        definition_snapshot=None,  # type: ignore[arg-type]
    )
    session.add(run)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ── ADR-004: idempotency partial unique on (tenant_id, idempotency_key)


def test_idempotency_unique_same_tenant_same_key_fails(session: Session) -> None:
    """Two runs with same (tenant_id, idempotency_key) MUST fail."""
    wf = _seed_workflow(session)
    tenant = uuid4()
    run1 = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        tenant_id=tenant,
        idempotency_key="abc-123",
        definition_snapshot={"i": 1},
    )
    session.add(run1)
    session.commit()
    run2 = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        tenant_id=tenant,
        idempotency_key="abc-123",
        definition_snapshot={"i": 2},
    )
    session.add(run2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_idempotency_unique_different_tenants_same_key_succeeds(
    session: Session,
) -> None:
    """Same key, different tenants — both inserts must succeed."""
    wf = _seed_workflow(session)
    run_a = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        tenant_id=uuid4(),
        idempotency_key="shared-key",
        definition_snapshot={"i": 1},
    )
    run_b = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        tenant_id=uuid4(),
        idempotency_key="shared-key",
        definition_snapshot={"i": 2},
    )
    session.add(run_a)
    session.add(run_b)
    session.commit()
    # Both rows survive.
    rows = session.exec(
        select(WorkflowRun).where(WorkflowRun.idempotency_key == "shared-key")
    ).all()
    assert len(rows) == 2


def test_idempotency_unique_null_keys_allow_many(session: Session) -> None:
    """The partial index (WHERE idempotency_key IS NOT NULL) does NOT
    constrain rows with NULL keys — many such rows must coexist."""
    wf = _seed_workflow(session)
    tenant = uuid4()
    for _ in range(3):
        run = WorkflowRun(
            kind="workflow",
            workflow_id=wf.id,
            tenant_id=tenant,
            idempotency_key=None,
            definition_snapshot={"i": 1},
        )
        session.add(run)
    session.commit()
    rows = session.exec(
        select(WorkflowRun).where(WorkflowRun.tenant_id == tenant)
    ).all()
    assert len(rows) == 3


# ── ADR-002: WorkflowRunEvent sequence uniqueness per run_id ──────────


def test_event_sequence_unique_per_run(session: Session) -> None:
    """Two events with same (run_id, sequence) MUST conflict."""
    wf = _seed_workflow(session)
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        definition_snapshot={"x": 1},
    )
    session.add(run)
    session.commit()

    e1 = WorkflowRunEvent(
        run_id=run.id,
        sequence=0,
        event_type="run.created",
        payload={"k": 1},
        prev_hash=None,
        current_hash="a" * 64,
    )
    e2 = WorkflowRunEvent(
        run_id=run.id,
        sequence=0,  # same sequence, same run — conflict
        event_type="run.queued",
        payload={"k": 2},
        prev_hash=None,
        current_hash="b" * 64,
    )
    session.add(e1)
    session.add(e2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_event_invalid_event_type_rejected(session: Session) -> None:
    """The CHECK constraint must reject unknown event_type values."""
    wf = _seed_workflow(session)
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        definition_snapshot={"x": 1},
    )
    session.add(run)
    session.commit()

    bad = WorkflowRunEvent(
        run_id=run.id,
        sequence=0,
        event_type="run.unknown",  # not in the closed enumeration
        payload={},
        prev_hash=None,
        current_hash="c" * 64,
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ── ADR-002: hash chain — append + tamper detection ───────────────────


def test_event_hash_chain_supports_tamper_detection(session: Session) -> None:
    """Append three events; verify clean; corrupt one payload; verify fails."""
    wf = _seed_workflow(session)
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        definition_snapshot={"x": 1},
    )
    session.add(run)
    session.commit()

    append_event(session, run.id, "run.created", {"step": "init"})
    append_event(session, run.id, "run.started", {"step": "go"})
    append_event(session, run.id, "run.completed", {"duration_ms": 42})
    session.commit()

    assert verify_hash_chain(session, run.id) is True

    # Tamper with the second event's payload (NOT its current_hash) —
    # the recompute must diverge.
    tampered = session.exec(
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run.id)
        .where(WorkflowRunEvent.sequence == 1)
    ).one()
    tampered.payload = {"step": "GOTCHA"}
    session.add(tampered)
    session.commit()

    assert verify_hash_chain(session, run.id) is False


def test_event_unknown_type_rejected_by_helper() -> None:
    """append_event MUST raise ValueError for an unknown event_type."""
    # Helper-only check; no DB needed.
    with pytest.raises(ValueError, match="unknown event_type"):
        append_event(  # type: ignore[arg-type]
            session=None, run_id=uuid4(), event_type="something.invented",
            payload={},
        )


def test_canonical_json_is_order_independent() -> None:
    """canonical_json must produce identical bytes for equal dicts
    regardless of key insertion order."""
    a = {"z": 1, "a": 2, "m": {"y": 3, "x": 4}}
    b = {"a": 2, "m": {"x": 4, "y": 3}, "z": 1}
    assert canonical_json(a) == canonical_json(b)
    # And the result should match the documented format exactly.
    expected = '{"a":2,"m":{"x":4,"y":3},"z":1}'
    assert canonical_json(a) == expected


def test_canonical_json_no_whitespace() -> None:
    """canonical_json output contains no insignificant whitespace."""
    payload = {"a": 1, "b": [1, 2]}
    out = canonical_json(payload)
    assert " " not in out
    assert "\n" not in out
    # Round-trip parses back to the same object.
    assert json.loads(out) == payload


def test_compute_hash_deterministic_and_chains() -> None:
    """compute_hash is deterministic; sequence>0 includes prev_hash bytes."""
    env = {
        "run_id": "a" * 36,
        "sequence": 0,
        "event_type": "run.created",
        "step_id": None,
        "tenant_id": None,
        "correlation_id": None,
        "span_id": None,
        "payload": {"x": 1},
    }
    h0_a = compute_hash(None, env)
    h0_b = compute_hash(None, env)
    assert h0_a == h0_b
    assert len(h0_a) == 64

    env_next = {**env, "sequence": 1, "event_type": "run.started"}
    h1 = compute_hash(h0_a, env_next)
    # If the prev_hash is altered, the chain link changes.
    h1_alt = compute_hash("0" * 64, env_next)
    assert h1 != h1_alt


def test_event_types_enumeration_size() -> None:
    """ADR-002 specifies 15 event types — frozenset must match exactly."""
    assert len(EVENT_TYPES) == 15
    # Spot-check a few to guard against drift.
    assert "run.created" in EVENT_TYPES
    assert "run.completed" in EVENT_TYPES
    assert "step.failed" in EVENT_TYPES
    assert "run.unknown" not in EVENT_TYPES


def test_append_event_assigns_sequential_sequences(session: Session) -> None:
    """Sequential calls to append_event produce 0,1,2,..."""
    wf = _seed_workflow(session)
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        definition_snapshot={"x": 1},
    )
    session.add(run)
    session.commit()

    e0 = append_event(session, run.id, "run.created", {})
    e1 = append_event(session, run.id, "run.queued", {})
    e2 = append_event(session, run.id, "run.started", {})
    session.commit()
    assert (e0.sequence, e1.sequence, e2.sequence) == (0, 1, 2)
    assert e0.prev_hash is None
    assert e1.prev_hash == e0.current_hash
    assert e2.prev_hash == e1.current_hash


def test_workflow_run_step_extended_columns(session: Session) -> None:
    """The 10 new step columns from ADR-002 land with their defaults."""
    wf = _seed_workflow(session)
    run = WorkflowRun(
        kind="workflow",
        workflow_id=wf.id,
        definition_snapshot={"x": 1},
    )
    session.add(run)
    session.commit()
    step = WorkflowRunStep(run_id=run.id, step_id="s1", name="first")
    session.add(step)
    session.commit()
    session.refresh(step)
    # Defaults
    assert step.attempt == 0
    assert step.retry_count == 0
    assert step.token_usage == {}
    # Optional fields default to None
    assert step.idempotency_key is None
    assert step.checkpoint_thread_id is None
    assert step.input_hash is None
    assert step.output_artifact_id is None
    assert step.cost_usd is None
    assert step.worker_id is None
    assert step.error_code is None
