"""Tests for the /api/v1/artifacts REST surface.

Covers:
  - GET /artifacts/{id}                 — metadata only (200)
  - GET /artifacts/{id}/content         — streams the stored bytes
  - GET /artifacts (list)               — cursor pagination
  - DELETE /artifacts/{id}              — removes row + storage
  - cross-tenant access returns 404 (never leaks existence)
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"

# Synthetic admin tenant aligned with auth.py's dev-mode user.
ADMIN_TENANT = UUID("00000000-0000-0000-0000-000000000100")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.artifact import Artifact  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _make_test_client(factory, tmp_path: Path, *, as_user=None):
    """Spin a FastAPI TestClient with overridden DB session + auth user.

    ``as_user`` is the AuthenticatedUser to inject; ``None`` returns the
    dev-mode admin user from auth.py's bypass.
    """
    from app.database import get_session
    from app.interfaces.models.enterprise import AuthenticatedUser
    from app.main import app
    from app.middleware.auth import get_current_user
    from app.services import artifact_service
    from app.storage.local_artifact_store import LocalArtifactStore

    # Pin the storage backend to the test's tmp_path so each test is
    # hermetic — no cross-test bleed via /tmp/archon/artifacts.
    artifact_service.set_default_store(
        LocalArtifactStore(base_dir=tmp_path / "artifacts")
    )

    async def _override_session():  # noqa: ANN202
        async with factory() as session:
            yield session

    async def _override_user():  # noqa: ANN202
        return as_user or AuthenticatedUser(
            id="00000000-0000-0000-0000-000000000001",
            email="admin@archon.local",
            tenant_id=str(ADMIN_TENANT),
            roles=["admin", "operator"],
            permissions=["*"],
            mfa_verified=True,
            session_id="test-session",
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def _clear_overrides():
    from app.main import app
    from app.services import artifact_service

    app.dependency_overrides.clear()
    artifact_service.set_default_store(None)


# ---------------------------------------------------------------------------
# Test 1: GET /artifacts/{id} returns 200 + metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_artifact_metadata_200(tmp_path):
    engine, factory = await _make_engine_and_factory()
    client = _make_test_client(factory, tmp_path)
    try:
        from app.services import artifact_service

        async with factory() as session:
            artifact = await artifact_service.store_artifact(
                session,
                tenant_id=ADMIN_TENANT,
                run_id=None,
                step_id="meta-step",
                content=b"meta-test-payload",
                content_type="text/plain",
            )
            await session.commit()
            artifact_id = artifact.id

        resp = client.get(f"/api/v1/artifacts/{artifact_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["id"] == str(artifact_id)
        assert body["data"]["content_type"] == "text/plain"
        assert body["data"]["size_bytes"] == len(b"meta-test-payload")
        assert "metadata" in body["data"]  # exposed under stable name
        assert "request_id" in body["meta"]
    finally:
        _clear_overrides()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: GET /artifacts/{id}/content streams the bytes with stored type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_artifact_content_streams_correct_bytes(tmp_path):
    engine, factory = await _make_engine_and_factory()
    client = _make_test_client(factory, tmp_path)
    try:
        from app.services import artifact_service

        payload = b"binary\x00\x01\xff data"

        async with factory() as session:
            artifact = await artifact_service.store_artifact(
                session,
                tenant_id=ADMIN_TENANT,
                run_id=None,
                step_id=None,
                content=payload,
                content_type="application/octet-stream",
            )
            await session.commit()
            artifact_id = artifact.id

        resp = client.get(f"/api/v1/artifacts/{artifact_id}/content")
        assert resp.status_code == 200, resp.text
        assert resp.content == payload
        assert (
            resp.headers["content-type"].split(";")[0].strip()
            == "application/octet-stream"
        )
        assert resp.headers["X-Artifact-Id"] == str(artifact_id)
        assert resp.headers["X-Content-Hash"]  # populated
    finally:
        _clear_overrides()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: GET /artifacts pagination via cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_artifacts_paginates_via_cursor(tmp_path):
    engine, factory = await _make_engine_and_factory()
    client = _make_test_client(factory, tmp_path)
    try:
        from app.services import artifact_service

        async with factory() as session:
            for i in range(5):
                await artifact_service.store_artifact(
                    session,
                    tenant_id=ADMIN_TENANT,
                    run_id=None,
                    step_id=f"s{i}",
                    content=f"payload-{i}".encode("utf-8"),
                    content_type="text/plain",
                )
            await session.commit()

        # First page: limit=2 → 2 items + next_cursor
        resp = client.get("/api/v1/artifacts?limit=2")
        assert resp.status_code == 200, resp.text
        page1 = resp.json()
        assert len(page1["data"]) == 2
        assert page1["meta"]["next_cursor"] is not None

        cursor = page1["meta"]["next_cursor"]
        resp = client.get(f"/api/v1/artifacts?limit=2&cursor={cursor}")
        assert resp.status_code == 200, resp.text
        page2 = resp.json()
        assert len(page2["data"]) == 2

        # IDs across pages must be disjoint.
        ids1 = {row["id"] for row in page1["data"]}
        ids2 = {row["id"] for row in page2["data"]}
        assert ids1.isdisjoint(ids2)
    finally:
        _clear_overrides()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: DELETE /artifacts/{id} removes row + file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_artifact_removes_row_and_file(tmp_path):
    engine, factory = await _make_engine_and_factory()
    client = _make_test_client(factory, tmp_path)
    try:
        from app.models.artifact import Artifact
        from app.services import artifact_service
        from sqlmodel import select

        async with factory() as session:
            artifact = await artifact_service.store_artifact(
                session,
                tenant_id=ADMIN_TENANT,
                run_id=None,
                step_id="to-delete",
                content=b"goodbye",
                content_type="text/plain",
            )
            await session.commit()
            artifact_id = artifact.id
            storage_uri = artifact.storage_uri

        assert Path(storage_uri).is_file()

        resp = client.delete(f"/api/v1/artifacts/{artifact_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["deleted"] is True

        # Row and file are both gone.
        assert not Path(storage_uri).is_file()
        async with factory() as session:
            rows = (
                await session.execute(select(Artifact))
            ).scalars().all()
        assert rows == []

        # Repeat delete returns 404 (idempotent at the API contract).
        resp = client.delete(f"/api/v1/artifacts/{artifact_id}")
        assert resp.status_code == 404
    finally:
        _clear_overrides()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: cross-tenant GET returns 404 (never leaks existence)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_tenant_get_returns_404(tmp_path):
    engine, factory = await _make_engine_and_factory()

    from app.interfaces.models.enterprise import AuthenticatedUser

    owning_tenant = UUID("00000000-0000-0000-0000-000000000aaa")
    foreign_user = AuthenticatedUser(
        id="00000000-0000-0000-0000-000000000010",
        email="other@archon.local",
        tenant_id="00000000-0000-0000-0000-000000000bbb",  # different tenant
        roles=["operator"],  # NOT admin
        permissions=[],
        mfa_verified=True,
        session_id="other-session",
    )

    # First seed the artifact under the owning tenant via an admin client.
    admin_client = _make_test_client(factory, tmp_path)
    try:
        from app.services import artifact_service

        async with factory() as session:
            artifact = await artifact_service.store_artifact(
                session,
                tenant_id=owning_tenant,
                run_id=None,
                step_id=None,
                content=b"private",
                content_type="text/plain",
            )
            await session.commit()
            artifact_id = artifact.id

        # Sanity — admin can see it.
        resp = admin_client.get(f"/api/v1/artifacts/{artifact_id}")
        assert resp.status_code == 200
    finally:
        _clear_overrides()

    # Now a foreign tenant non-admin must 404 on every endpoint.
    foreign_client = _make_test_client(factory, tmp_path, as_user=foreign_user)
    try:
        # Metadata
        resp = foreign_client.get(f"/api/v1/artifacts/{artifact_id}")
        assert resp.status_code == 404, resp.text

        # Content
        resp = foreign_client.get(f"/api/v1/artifacts/{artifact_id}/content")
        assert resp.status_code == 404

        # Delete
        resp = foreign_client.delete(f"/api/v1/artifacts/{artifact_id}")
        assert resp.status_code == 404

        # Listing must also exclude the foreign-tenant artifact.
        resp = foreign_client.get("/api/v1/artifacts")
        assert resp.status_code == 200
        body = resp.json()
        assert all(
            row["id"] != str(artifact_id) for row in body["data"]
        ), body
    finally:
        _clear_overrides()
        await engine.dispose()
