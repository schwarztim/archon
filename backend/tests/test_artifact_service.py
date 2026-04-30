"""Tests for app.services.artifact_service + LocalArtifactStore.

Covers:
  - store_artifact persists to the local store and computes sha256
  - get_artifact round-trips bytes
  - get_artifact returns None for cross-tenant access
  - maybe_persist_output_as_artifact inlines small output
  - maybe_persist_output_as_artifact extracts large output
  - expire_old_artifacts removes expired files + DB rows
  - concurrent stores do not corrupt
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables created."""
    # Import side-effects load every model class onto SQLModel.metadata.
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


def _make_store(tmp_path: Path):
    """Build a LocalArtifactStore rooted in a temp directory."""
    from app.storage.local_artifact_store import LocalArtifactStore

    return LocalArtifactStore(base_dir=tmp_path / "artifacts")


# ---------------------------------------------------------------------------
# Test 1: store_artifact persists bytes + computes sha256
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_artifact_persists_to_local_store(tmp_path):
    """Bytes land on disk under {tenant}/{run}/{artifact_id} and the row
    records storage_uri + size_bytes."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.services import artifact_service

    tenant_id = UUID("00000000-0000-0000-0000-000000000abc")
    payload = b"hello-world-" * 64

    async with factory() as session:
        artifact = await artifact_service.store_artifact(
            session,
            tenant_id=tenant_id,
            run_id=None,
            step_id="s1",
            content=payload,
            content_type="application/octet-stream",
            store=store,
        )
        await session.commit()

    assert artifact.size_bytes == len(payload)
    assert artifact.storage_backend == "local"
    assert Path(artifact.storage_uri).is_file()

    # Disk bytes match
    assert Path(artifact.storage_uri).read_bytes() == payload

    # Path layout matches the documented {base}/{tenant}/{run}/{id}
    parts = Path(artifact.storage_uri).parts
    assert str(tenant_id) in parts
    assert "_unbound" in parts
    assert str(artifact.id) in parts

    await engine.dispose()


@pytest.mark.asyncio
async def test_store_artifact_computes_sha256(tmp_path):
    """content_hash equals sha256(payload).hexdigest()."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.services import artifact_service

    payload = b"deterministic-bytes-for-hashing"
    expected = hashlib.sha256(payload).hexdigest()

    async with factory() as session:
        artifact = await artifact_service.store_artifact(
            session,
            tenant_id=None,
            run_id=None,
            step_id=None,
            content=payload,
            content_type="text/plain",
            store=store,
        )
        await session.commit()

    assert artifact.content_hash == expected
    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: round-trip get_artifact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_artifact_round_trip(tmp_path):
    """store + get returns identical bytes."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.services import artifact_service

    tenant_id = UUID("00000000-0000-0000-0000-000000000aa1")
    payload = b"\x00\x01\x02\x03\xff binary safe?"

    async with factory() as session:
        artifact = await artifact_service.store_artifact(
            session,
            tenant_id=tenant_id,
            run_id=None,
            step_id=None,
            content=payload,
            content_type="application/octet-stream",
            store=store,
        )
        await session.commit()
        artifact_id = artifact.id

    async with factory() as session:
        fetched = await artifact_service.get_artifact(
            session,
            artifact_id,
            tenant_id=tenant_id,
            store=store,
        )
    assert fetched is not None
    got_artifact, got_bytes = fetched
    assert got_artifact.id == artifact_id
    assert got_bytes == payload

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: cross-tenant access returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_artifact_returns_404_for_other_tenant(tmp_path):
    """Caller's tenant_id mismatching the row → None (route → 404)."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.services import artifact_service

    owning_tenant = UUID("00000000-0000-0000-0000-000000000111")
    other_tenant = UUID("00000000-0000-0000-0000-000000000222")

    async with factory() as session:
        artifact = await artifact_service.store_artifact(
            session,
            tenant_id=owning_tenant,
            run_id=None,
            step_id=None,
            content=b"private-data",
            content_type="text/plain",
            store=store,
        )
        await session.commit()
        artifact_id = artifact.id

    async with factory() as session:
        # Other tenant — must miss.
        miss = await artifact_service.get_artifact(
            session,
            artifact_id,
            tenant_id=other_tenant,
            store=store,
        )
        assert miss is None

        # Admin path (tenant_id=None) sees everything.
        admin = await artifact_service.get_artifact(
            session,
            artifact_id,
            tenant_id=None,
            store=store,
        )
        assert admin is not None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: small outputs stay inline; large outputs get extracted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_persist_inlines_small_output(tmp_path):
    """Output below the threshold is returned unchanged; no row created."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.models.artifact import Artifact
    from app.services import artifact_service

    small_output = {"value": "ok", "count": 3}

    async with factory() as session:
        result = await artifact_service.maybe_persist_output_as_artifact(
            session,
            tenant_id=None,
            run_id=None,
            step_id="s1",
            output_data=small_output,
            threshold_bytes=32 * 1024,
            store=store,
        )
        await session.commit()

    assert result == small_output
    assert "_artifact_ref" not in (result or {})

    async with factory() as session:
        rows = (
            await session.execute(select(Artifact))
        ).scalars().all()
    assert rows == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_maybe_persist_extracts_large_output(tmp_path, capsys):
    """Output above the threshold returns an _artifact_ref shim and creates
    a row whose content matches the original payload."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.models.artifact import Artifact
    from app.services import artifact_service

    # Build a payload guaranteed to exceed the 32 KiB default threshold.
    big_output = {"rows": [{"i": i, "data": "x" * 64} for i in range(1000)]}
    serialised = json.dumps(big_output, default=str).encode("utf-8")
    assert len(serialised) > 32 * 1024  # sanity

    async with factory() as session:
        result = await artifact_service.maybe_persist_output_as_artifact(
            session,
            tenant_id=None,
            run_id=None,
            step_id="big-step",
            output_data=big_output,
            store=store,
        )
        await session.commit()

    assert isinstance(result, dict)
    assert "_artifact_ref" in result
    ref = result["_artifact_ref"]
    assert "id" in ref
    assert ref["size_bytes"] == len(serialised)
    assert ref["content_type"] == "application/json"
    assert ref["content_hash"] == hashlib.sha256(serialised).hexdigest()

    # Row created and bytes on disk
    async with factory() as session:
        rows = (
            await session.execute(select(Artifact))
        ).scalars().all()
    assert len(rows) == 1
    saved = rows[0]
    assert str(saved.id) == ref["id"]
    assert saved.size_bytes == len(serialised)
    assert Path(saved.storage_uri).read_bytes() == serialised

    # Print the sample _artifact_ref for the deliverable visibility.
    print("\n=== Sample _artifact_ref (large output extracted) ===")
    print(json.dumps(result, indent=2))

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: expire_old_artifacts removes both row and file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expire_old_artifacts_removes_expired_files(tmp_path):
    """Set expires_at in the past; assert row deleted and file removed."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.models.artifact import Artifact
    from app.services import artifact_service

    async with factory() as session:
        # Live artifact (expires in the future)
        live = await artifact_service.store_artifact(
            session,
            tenant_id=None,
            run_id=None,
            step_id="alive",
            content=b"alive-bytes",
            content_type="text/plain",
            retention_days=30,
            store=store,
        )
        # Expired artifact (force expires_at into the past)
        dead = await artifact_service.store_artifact(
            session,
            tenant_id=None,
            run_id=None,
            step_id="dead",
            content=b"dead-bytes",
            content_type="text/plain",
            retention_days=30,
            store=store,
        )
        dead.expires_at = datetime.utcnow() - timedelta(days=1)
        session.add(dead)
        await session.commit()
        live_uri = live.storage_uri
        dead_uri = dead.storage_uri
        live_id = live.id
        dead_id = dead.id

    assert Path(live_uri).is_file()
    assert Path(dead_uri).is_file()

    async with factory() as session:
        count = await artifact_service.expire_old_artifacts(
            session,
            store=store,
        )
        await session.commit()

    assert count == 1
    assert Path(live_uri).is_file()
    assert not Path(dead_uri).is_file()

    async with factory() as session:
        ids = {
            r.id
            for r in (
                await session.execute(select(Artifact))
            ).scalars().all()
        }
    assert ids == {live_id}
    assert dead_id not in ids

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 6: concurrent stores don't corrupt each other
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_store_does_not_corrupt(tmp_path):
    """Many parallel store_artifact calls produce N distinct rows whose
    bytes round-trip cleanly. The atomic tempfile+rename layout is the
    correctness guarantee here."""
    engine, factory = await _make_engine_and_factory()
    store = _make_store(tmp_path)

    from app.models.artifact import Artifact
    from app.services import artifact_service

    payloads = [f"chunk-{i}".encode("utf-8") * (i + 1) for i in range(20)]

    async def _one(idx: int):
        async with factory() as session:
            art = await artifact_service.store_artifact(
                session,
                tenant_id=None,
                run_id=None,
                step_id=f"s{idx}",
                content=payloads[idx],
                content_type="application/octet-stream",
                store=store,
            )
            await session.commit()
            return art.id, art.storage_uri, payloads[idx]

    # Drive a sizeable batch of concurrent writes.
    results = await asyncio.gather(*(_one(i) for i in range(20)))

    # Every URI is unique and the bytes match the original payload.
    seen: set[str] = set()
    for art_id, uri, original in results:
        assert uri not in seen, f"duplicate uri {uri}"
        seen.add(uri)
        assert Path(uri).read_bytes() == original

    async with factory() as session:
        rows = (
            await session.execute(select(Artifact))
        ).scalars().all()
    assert len(rows) == 20
    # Hashes must match each payload exactly.
    by_hash = {r.content_hash for r in rows}
    expected_hashes = {hashlib.sha256(p).hexdigest() for p in payloads}
    assert by_hash == expected_hashes

    await engine.dispose()
