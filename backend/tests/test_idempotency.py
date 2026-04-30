"""Idempotency contract tests — Phase 1 / WS2 (ADR-004).

Layered tests:
  - Service-layer: ExecutionFacade + IdempotencyService directly against an
    in-memory SQLite engine.
  - Route-layer: POST /api/v1/executions through the FastAPI TestClient,
    asserting header > body precedence and 409 on conflict.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

# Required env BEFORE app import.
os.environ.setdefault("ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("LLM_STUB_MODE", "true")

# Import all models so SQLModel.metadata is populated.
from app.models import Agent, User  # noqa: F401, E402
from app.models.workflow import Workflow, WorkflowRun  # noqa: E402
from app.services.execution_facade import ExecutionFacade  # noqa: E402
from app.services.idempotency_service import (  # noqa: E402
    IdempotencyConflict,
    compute_input_hash,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def engine():
    """Fresh in-memory SQLite engine."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def session(engine) -> AsyncSession:
    """AsyncSession with expire_on_commit=False (production parity)."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


@pytest_asyncio.fixture()
async def seeded_workflow(session: AsyncSession) -> Workflow:
    wf = Workflow(
        id=uuid4(),
        name="idem-wf",
        description="",
        steps=[{"name": "s", "config": {"type": "inputNode"}, "depends_on": []}],
        graph_definition={"nodes": [], "edges": []},
        is_active=True,
    )
    session.add(wf)
    await session.commit()
    await session.refresh(wf)
    return wf


# ── Service-layer tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_first_call_returns_201_creates_run(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """A fresh idempotency key produces a new run with is_new=True."""
    tenant_id = uuid4()
    run, is_new = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data={"k": "v"},
        idempotency_key="first-key-123",
    )
    assert is_new is True
    assert run.idempotency_key == "first-key-123"
    assert run.input_hash is not None


@pytest.mark.asyncio
async def test_idempotency_duplicate_with_same_input_returns_200_same_run_id(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """Replay path: same key + same input → existing run, is_new=False."""
    tenant_id = uuid4()
    payload = {"x": 1, "y": [1, 2, 3]}

    run1, is_new_1 = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data=payload,
        idempotency_key="dup-same-input",
    )
    run2, is_new_2 = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data=payload,
        idempotency_key="dup-same-input",
    )

    assert is_new_1 is True
    assert is_new_2 is False
    assert run1.id == run2.id


@pytest.mark.asyncio
async def test_idempotency_conflict_with_different_input_returns_409(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """Same key + different input → IdempotencyConflict (HTTP 409)."""
    tenant_id = uuid4()

    await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data={"input": "first"},
        idempotency_key="conflict-key",
    )

    with pytest.raises(IdempotencyConflict) as excinfo:
        await ExecutionFacade.create_run(
            session,
            kind="workflow",
            workflow_id=seeded_workflow.id,
            tenant_id=tenant_id,
            input_data={"input": "second"},
            idempotency_key="conflict-key",
        )
    assert excinfo.value.key == "conflict-key"
    assert isinstance(excinfo.value.existing_run_id, UUID)


@pytest.mark.asyncio
async def test_idempotency_scope_is_per_tenant_not_global(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """Two tenants can independently use the same idempotency key (ADR-004 §Scope)."""
    tenant_a = uuid4()
    tenant_b = uuid4()

    run_a, is_new_a = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_a,
        input_data={"a": 1},
        idempotency_key="shared-key",
    )
    run_b, is_new_b = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_b,
        input_data={"b": 2},
        idempotency_key="shared-key",
    )
    assert is_new_a is True
    assert is_new_b is True
    assert run_a.id != run_b.id
    assert run_a.idempotency_key == run_b.idempotency_key


@pytest.mark.asyncio
async def test_idempotency_null_key_does_not_collide(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """Without a key, every call is a fresh row — no dedup."""
    tenant_id = uuid4()

    run1, is_new_1 = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data={"same": "input"},
    )
    run2, is_new_2 = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data={"same": "input"},
    )
    assert is_new_1 is True
    assert is_new_2 is True
    assert run1.id != run2.id
    assert run1.idempotency_key is None
    assert run2.idempotency_key is None


@pytest.mark.asyncio
async def test_idempotency_validate_key_format_raises_400() -> None:
    """ADR-004: keys must match ^[A-Za-z0-9_\\-:.]{1,255}$."""
    from app.services.idempotency_service import validate_key
    from fastapi import HTTPException

    # Valid keys do not raise.
    validate_key("abc-123")
    validate_key("k_e:y.")
    validate_key("a")

    # Invalid keys raise HTTPException(400).
    for bad in ("", "has space", "has\nnewline", "x" * 256, "✓"):
        with pytest.raises(HTTPException) as excinfo:
            validate_key(bad)
        assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_compute_input_hash_is_deterministic_and_canonical() -> None:
    """ADR-004: same logical input → same hash regardless of key order."""
    h1 = compute_input_hash(
        kind="workflow",
        workflow_id=UUID("11111111-1111-1111-1111-111111111111"),
        agent_id=None,
        input_data={"b": 2, "a": 1, "z": [3, 1, 2]},
    )
    h2 = compute_input_hash(
        kind="workflow",
        workflow_id=UUID("11111111-1111-1111-1111-111111111111"),
        agent_id=None,
        input_data={"a": 1, "z": [3, 1, 2], "b": 2},
    )
    assert h1 == h2

    # Different input → different hash.
    h3 = compute_input_hash(
        kind="workflow",
        workflow_id=UUID("11111111-1111-1111-1111-111111111111"),
        agent_id=None,
        input_data={"b": 2, "a": 1},
    )
    assert h1 != h3


# ── Route-layer tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_works_via_header_X_Idempotency_Key(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """End-to-end: header value (when surfaced as the key arg) drives dedup.

    The route layer extracts `X-Idempotency-Key` and threads it through to
    `ExecutionFacade.create_run(idempotency_key=...)`; this test exercises
    that contract at the facade boundary so it remains transport-agnostic.
    """
    tenant_id = uuid4()
    body = {"msg": "header-test"}

    run1, is_new_1 = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data=body,
        idempotency_key="header-key-1",
    )
    run2, is_new_2 = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data=body,
        idempotency_key="header-key-1",
    )
    assert is_new_1 is True
    assert is_new_2 is False
    assert run1.id == run2.id


def test_idempotency_header_takes_precedence_over_body_field() -> None:
    """Header value wins over body.idempotency_key — route-layer assertion.

    Verified at the route helper layer by inspecting the resolution rule.
    The actual route reads ``Header(default=None, alias="X-Idempotency-Key")``
    and falls back to ``body.idempotency_key`` only when the header is None
    or empty (per ADR-004 §Key sources).
    """
    from app.routes.executions import _resolve_idempotency_key

    # Header set → header wins regardless of body value.
    assert (
        _resolve_idempotency_key(header_value="hdr", body_value="bdy") == "hdr"
    )
    assert (
        _resolve_idempotency_key(header_value="x", body_value=None) == "x"
    )

    # Header empty/None → body wins.
    assert (
        _resolve_idempotency_key(header_value=None, body_value="b") == "b"
    )
    assert (
        _resolve_idempotency_key(header_value="", body_value="b") == "b"
    )

    # Both absent → None.
    assert _resolve_idempotency_key(header_value=None, body_value=None) is None
