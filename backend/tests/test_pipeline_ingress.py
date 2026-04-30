"""Tests for pipeline ingress service (W8).

Uses inline SQLite with --noconftest pattern: no conftest.py fixtures,
all setup is local to this module. All DB tables are created from the
SQLModel metadata; no alembic migrations are run here.

Providers tested: github_actions, generic_webhook (representative sample).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker

# Force all models to register with SQLModel metadata before creating tables.
import app.models  # noqa: F401  (side-effect: registers all SQLModel tables)

# ── Inline SQLite engine ──────────────────────────────────────────────────────

_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    connect_args={"check_same_thread": False},
)
_SESSION_FACTORY = sessionmaker(
    _ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Fixed UUIDs for deterministic tests.
_TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
_WORKFLOW_ID = UUID("20000000-0000-0000-0000-000000000002")
_DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

_GITHUB_PAYLOAD: dict[str, Any] = {
    "delivery": "abc123delivery",
    "workflow_run": {
        "id": 987654,
        "head_sha": "deadbeefcafe",
        "head_branch": "main",
    },
    "sender": {"login": "octocat"},
}

_GENERIC_PAYLOAD: dict[str, Any] = {
    "event": {
        "event_id": "gen-event-001",
        "run_id": "build-42",
        "pipeline_id": "my-pipeline",
        "commit_sha": "abcdef123",
        "branch": "feature/x",
        "actor": "ci-bot",
        "environment": "staging",
    }
}


def _github_sig(payload_bytes: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _generic_sig(payload_bytes: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return mac.hexdigest()


# ── Session setup ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module", autouse=True)
async def create_tables():
    """Create all SQLModel tables in the in-memory SQLite DB once per module."""
    async with _ENGINE.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with _ENGINE.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    """Provide a fresh AsyncSession; roll back after each test."""
    async with _SESSION_FACTORY() as s:
        yield s
        await s.rollback()


async def _seed_workflow(session: AsyncSession) -> None:
    """Insert a Workflow and a default User so ExecutionFacade.create_run can resolve them."""
    from app.models.workflow import Workflow
    from app.models import User

    # Insert user first (FK dependency).
    user_stmt = await session.exec(
        __import__("sqlmodel", fromlist=["select"]).select(User).where(User.id == _DEFAULT_USER_ID)
    )
    if user_stmt.first() is None:
        session.add(User(
            id=_DEFAULT_USER_ID,
            email="system@archon.local",
            name="System",
            role="admin",
        ))
        await session.flush()

    # Insert workflow.
    from sqlmodel import select
    result = await session.exec(select(Workflow).where(Workflow.id == _WORKFLOW_ID))
    if result.first() is None:
        session.add(Workflow(
            id=_WORKFLOW_ID,
            name="CI Test Workflow",
            steps=[],
            graph_definition={},
            owner_id=_DEFAULT_USER_ID,
            tenant_id=_TENANT_ID,
        ))
        await session.flush()


# ── Unit: signature verification ─────────────────────────────────────────────


def test_github_webhook_signature_verification():
    """GitHub HMAC-SHA256 signature must verify correctly."""
    from app.services.pipeline_service import _verify_signature

    secret = "test-secret"
    payload = b'{"action":"completed"}'
    sig = _github_sig(payload, secret)

    assert _verify_signature("github_actions", payload, sig, secret) is True
    assert _verify_signature("github_actions", payload, "sha256=badhex", secret) is False
    assert _verify_signature("github_actions", payload, "wrongprefix", secret) is False


def test_generic_hmac_sha256_verification():
    """Generic provider HMAC-SHA256 must verify correctly."""
    from app.services.pipeline_service import _verify_signature

    secret = "mysecret"
    payload = b'{"event_id":"e1"}'
    sig = _generic_sig(payload, secret)

    assert _verify_signature("generic_webhook", payload, sig, secret) is True
    assert _verify_signature("generic_webhook", payload, "badsig", secret) is False


def test_invalid_signature_raises_permission_error_from_verify():
    """_verify_signature returns False on bad sig (not raises)."""
    from app.services.pipeline_service import _verify_signature

    result = _verify_signature("github_actions", b"body", "sha256=wrong", "secret")
    assert result is False


# ── Integration: service-level ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_signature_returns_401_via_service(session):
    """ingest_pipeline_event raises PermissionError on bad signature."""
    from app.services.pipeline_service import ingest_pipeline_event

    await _seed_workflow(session)

    payload_bytes = json.dumps(_GITHUB_PAYLOAD).encode()
    bad_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

    with pytest.raises(PermissionError, match="signature"):
        await ingest_pipeline_event(
            session,
            tenant_id=_TENANT_ID,
            workflow_id=_WORKFLOW_ID,
            provider="github_actions",
            event_payload=_GITHUB_PAYLOAD,
            signature=bad_sig,
            secret="correct-secret",
            payload_bytes=payload_bytes,
        )


@pytest.mark.asyncio
async def test_ingest_creates_run_through_facade(session):
    """A valid ingest creates a WorkflowRun via ExecutionFacade and a PipelineCorrelation."""
    from app.services.pipeline_service import ingest_pipeline_event
    from app.models.workflow import WorkflowRun
    from sqlmodel import select

    await _seed_workflow(session)

    secret = "integration-secret"
    payload_bytes = json.dumps(_GITHUB_PAYLOAD).encode()
    sig = _github_sig(payload_bytes, secret)

    correlation, is_new = await ingest_pipeline_event(
        session,
        tenant_id=_TENANT_ID,
        workflow_id=_WORKFLOW_ID,
        provider="github_actions",
        event_payload=_GITHUB_PAYLOAD,
        signature=sig,
        secret=secret,
        payload_bytes=payload_bytes,
    )

    assert is_new is True
    assert correlation.provider == "github_actions"
    assert correlation.external_event_id == "abc123delivery"
    assert correlation.external_commit_sha == "deadbeefcafe"
    assert correlation.external_branch == "main"
    assert correlation.external_actor == "octocat"

    # Verify a WorkflowRun was created.
    run = await session.get(WorkflowRun, correlation.workflow_run_id)
    assert run is not None
    assert run.triggered_by == "pipeline"
    assert run.trigger_type == "webhook"


@pytest.mark.asyncio
async def test_correlation_links_run_to_external_event(session):
    """PipelineCorrelation.workflow_run_id points to the created WorkflowRun."""
    from app.services.pipeline_service import ingest_pipeline_event
    from app.models.workflow import WorkflowRun

    await _seed_workflow(session)

    # Use a distinct payload to avoid collision with other tests.
    payload = {**_GITHUB_PAYLOAD, "delivery": "link-test-delivery-001"}
    secret = "link-secret"
    payload_bytes = json.dumps(payload).encode()
    sig = _github_sig(payload_bytes, secret)

    correlation, _ = await ingest_pipeline_event(
        session,
        tenant_id=_TENANT_ID,
        workflow_id=_WORKFLOW_ID,
        provider="github_actions",
        event_payload=payload,
        signature=sig,
        secret=secret,
        payload_bytes=payload_bytes,
    )

    run = await session.get(WorkflowRun, correlation.workflow_run_id)
    assert run is not None
    assert correlation.workflow_run_id == run.id


@pytest.mark.asyncio
async def test_duplicate_event_returns_existing_correlation(session):
    """Duplicate webhook delivery returns the same PipelineCorrelation without creating a new run."""
    from app.services.pipeline_service import ingest_pipeline_event
    from app.models.workflow import WorkflowRun
    from sqlmodel import select, func

    await _seed_workflow(session)

    payload = {**_GITHUB_PAYLOAD, "delivery": "dup-test-delivery-001"}
    secret = "dup-secret"
    payload_bytes = json.dumps(payload).encode()
    sig = _github_sig(payload_bytes, secret)

    corr1, is_new1 = await ingest_pipeline_event(
        session,
        tenant_id=_TENANT_ID,
        workflow_id=_WORKFLOW_ID,
        provider="github_actions",
        event_payload=payload,
        signature=sig,
        secret=secret,
        payload_bytes=payload_bytes,
    )
    assert is_new1 is True

    # Second delivery — same event_id.
    corr2, is_new2 = await ingest_pipeline_event(
        session,
        tenant_id=_TENANT_ID,
        workflow_id=_WORKFLOW_ID,
        provider="github_actions",
        event_payload=payload,
        signature=sig,
        secret=secret,
        payload_bytes=payload_bytes,
    )
    assert is_new2 is False
    assert corr2.id == corr1.id


@pytest.mark.asyncio
async def test_get_correlation_by_run_id(session):
    """get_correlation_by_run returns the correlation for a given run_id."""
    from app.services.pipeline_service import ingest_pipeline_event, get_correlation_by_run

    await _seed_workflow(session)

    payload = {**_GITHUB_PAYLOAD, "delivery": "lookup-by-run-001"}
    secret = "lookup-secret"
    payload_bytes = json.dumps(payload).encode()
    sig = _github_sig(payload_bytes, secret)

    corr, _ = await ingest_pipeline_event(
        session,
        tenant_id=_TENANT_ID,
        workflow_id=_WORKFLOW_ID,
        provider="github_actions",
        event_payload=payload,
        signature=sig,
        secret=secret,
        payload_bytes=payload_bytes,
    )

    found = await get_correlation_by_run(session, run_id=corr.workflow_run_id)
    assert found is not None
    assert found.id == corr.id
    assert found.external_event_id == "lookup-by-run-001"


@pytest.mark.asyncio
async def test_generic_webhook_ingest(session):
    """Generic provider with HMAC-SHA256 creates correlation with extracted fields."""
    from app.services.pipeline_service import ingest_pipeline_event

    await _seed_workflow(session)

    secret = "generic-secret"
    payload_bytes = json.dumps(_GENERIC_PAYLOAD).encode()
    sig = _generic_sig(payload_bytes, secret)

    corr, is_new = await ingest_pipeline_event(
        session,
        tenant_id=_TENANT_ID,
        workflow_id=_WORKFLOW_ID,
        provider="generic_webhook",
        event_payload=_GENERIC_PAYLOAD,
        signature=sig,
        secret=secret,
        payload_bytes=payload_bytes,
    )

    assert is_new is True
    assert corr.provider == "generic_webhook"
    assert corr.external_event_id == "gen-event-001"
    assert corr.external_run_id == "build-42"
    assert corr.external_branch == "feature/x"
    assert corr.external_actor == "ci-bot"
    assert corr.environment == "staging"
