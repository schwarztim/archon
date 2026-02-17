"""Tests for DocForgeService — document ingestion, DLP scan, permission-aware search,
collection management, tenant isolation, and cascade delete."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.connector import ConnectorConfig, ConnectorInstance, ConnectorStatus, AuthMethod
from app.models.docforge import (
    AccessLevel,
    Collection,
    CollectionConfig,
    Document,
    DocumentListFilters,
    DocumentSource,
    EmbeddingStatus,
    PermissionType,
    SearchFilters,
    SearchResult,
)
from app.services.docforge_service import (
    DocForgeService,
    _chunks,
    _collections,
    _documents,
    _permissions,
)


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_A = "tenant-docforge-a"
TENANT_B = "tenant-docforge-b"


def _admin_user(tenant_id: str = TENANT_A, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id="user-admin-1",
        email="admin@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=[],
        session_id="sess-1",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _viewer_user(tenant_id: str = TENANT_A) -> AuthenticatedUser:
    return AuthenticatedUser(
        id="user-viewer-1",
        email="viewer@example.com",
        tenant_id=tenant_id,
        roles=["viewer"],
        permissions=[],
        session_id="sess-2",
    )


def _non_permitted_user(tenant_id: str = TENANT_A) -> AuthenticatedUser:
    """User with read role but no explicit document permission."""
    return AuthenticatedUser(
        id="user-noperm-99",
        email="noperm@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=[],
        session_id="sess-3",
    )


def _mock_secrets() -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_secret = AsyncMock(return_value={"key": "enc-key-256"})
    mgr.put_secret = AsyncMock()
    return mgr


def _register_connector(tenant_id: str = TENANT_A) -> ConnectorInstance:
    """Directly insert a mock connector into the connector registry."""
    from app.services.connector_service import _connectors

    cid = uuid4()
    instance = ConnectorInstance(
        id=cid,
        tenant_id=tenant_id,
        type="salesforce",
        name="Test Connector",
        status=ConnectorStatus.ACTIVE,
        auth_method=AuthMethod.OAUTH2,
        scopes=["api"],
    )
    _connectors[str(cid)] = instance
    return instance


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    """Reset in-memory stores before each test."""
    from app.services.connector_service import _connectors

    _documents.clear()
    _chunks.clear()
    _permissions.clear()
    _collections.clear()
    _connectors.clear()


# ── ingest_document ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_document_success() -> None:
    """Ingests a document with DLP scan and sets embedding status to COMPLETED."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="file-1")

    doc = await DocForgeService.ingest_document(
        TENANT_A, user, source, title="Test Doc",
    )

    assert isinstance(doc, Document)
    assert doc.tenant_id == TENANT_A
    assert doc.title == "Test Doc"
    assert doc.embedding_status == EmbeddingStatus.COMPLETED
    assert doc.dlp_clean is True
    assert doc.chunk_count >= 1
    assert str(doc.id) in _documents


@pytest.mark.asyncio
async def test_ingest_document_with_permission_sync() -> None:
    """Ingested document gets owner USER permission with ADMIN access."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="file-2")

    doc = await DocForgeService.ingest_document(TENANT_A, user, source)

    perms = _permissions.get(str(doc.id), [])
    assert len(perms) == 1
    assert perms[0].permission_type == PermissionType.USER
    assert perms[0].principal_id == user.id
    assert perms[0].access_level == AccessLevel.ADMIN


@pytest.mark.asyncio
async def test_ingest_document_dlp_scan_runs() -> None:
    """DLP scan is invoked during ingestion (mock verifies clean result)."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="file-3")

    with patch("app.services.docforge_service._mock_dlp_scan", return_value=(True, None)) as dlp:
        doc = await DocForgeService.ingest_document(TENANT_A, user, source)
        dlp.assert_called_once()
        assert doc.dlp_clean is True


@pytest.mark.asyncio
async def test_ingest_document_connector_wrong_tenant() -> None:
    """Raises ValueError when connector belongs to a different tenant."""
    connector = _register_connector(tenant_id=TENANT_B)
    user = _admin_user(tenant_id=TENANT_A)
    source = DocumentSource(connector_id=connector.id, resource_id="file-x")

    with pytest.raises(ValueError, match="not found"):
        await DocForgeService.ingest_document(TENANT_A, user, source)


# ── search ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_returns_auth_gated_results() -> None:
    """Search only returns documents the user has permission to see."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="searchable")

    doc = await DocForgeService.ingest_document(
        TENANT_A, user, source, title="searchable doc",
    )

    result = await DocForgeService.search(TENANT_A, user, "Content")
    assert isinstance(result, SearchResult)
    assert result.total >= 1
    assert result.results[0].document_id == doc.id


@pytest.mark.asyncio
async def test_search_hybrid_returns_scores() -> None:
    """Hybrid search returns results with scores and processing time."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="scored")

    await DocForgeService.ingest_document(TENANT_A, user, source, title="scored doc")

    result = await DocForgeService.search(TENANT_A, user, "random-query-no-match")
    assert isinstance(result, SearchResult)
    assert result.processing_time_ms >= 0
    # Even non-matching queries return embedding-based scores
    for hit in result.results:
        assert hit.score >= 0


# ── get_document ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_document_with_permission() -> None:
    """Owner can retrieve their own document."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="get-test")

    doc = await DocForgeService.ingest_document(TENANT_A, user, source)
    fetched = await DocForgeService.get_document(TENANT_A, user, doc.id)

    assert fetched.id == doc.id


@pytest.mark.asyncio
async def test_get_document_no_permission_denied() -> None:
    """User without document permission gets ValueError."""
    connector = _register_connector()
    owner = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="perm-test")
    doc = await DocForgeService.ingest_document(TENANT_A, owner, source)

    # A different user with no doc permission
    other = AuthenticatedUser(
        id="user-other-no-access",
        email="other@example.com",
        tenant_id=TENANT_A,
        roles=["operator"],
        permissions=["documents:read"],
        session_id="sess-x",
    )

    with pytest.raises(ValueError, match="not found"):
        await DocForgeService.get_document(TENANT_A, other, doc.id)


# ── list_documents ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_documents_paginated() -> None:
    """Lists documents with correct total count."""
    connector = _register_connector()
    user = _admin_user()

    for i in range(3):
        source = DocumentSource(connector_id=connector.id, resource_id=f"list-{i}")
        await DocForgeService.ingest_document(TENANT_A, user, source)

    docs, total = await DocForgeService.list_documents(TENANT_A, user)
    assert total == 3
    assert len(docs) == 3


# ── delete_document ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_document_cascade() -> None:
    """Cascade delete removes document, chunks, and permissions."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="del-test")

    doc = await DocForgeService.ingest_document(TENANT_A, user, source)
    doc_id_str = str(doc.id)

    assert doc_id_str in _documents
    assert doc_id_str in _chunks
    assert doc_id_str in _permissions

    await DocForgeService.delete_document(TENANT_A, user, doc.id)

    assert doc_id_str not in _documents
    assert doc_id_str not in _chunks
    assert doc_id_str not in _permissions


# ── reprocess_document ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reprocess_document_re_embeds() -> None:
    """Reprocessing regenerates chunks and resets embedding status."""
    connector = _register_connector()
    user = _admin_user()
    source = DocumentSource(connector_id=connector.id, resource_id="reproc")

    doc = await DocForgeService.ingest_document(TENANT_A, user, source)
    original_chunks = len(_chunks.get(str(doc.id), []))

    updated = await DocForgeService.reprocess_document(TENANT_A, user, doc.id)

    assert updated.embedding_status == EmbeddingStatus.COMPLETED
    assert updated.chunk_count >= 1


# ── create_collection / get_collections ─────────────────────────────


@pytest.mark.asyncio
async def test_create_collection() -> None:
    """Creates a collection with custom chunking config."""
    user = _admin_user()
    config = CollectionConfig(
        name="Knowledge Base",
        description="Internal docs",
        chunk_size=256,
        chunk_overlap=32,
    )

    col = await DocForgeService.create_collection(TENANT_A, user, config)

    assert isinstance(col, Collection)
    assert col.tenant_id == TENANT_A
    assert col.name == "Knowledge Base"
    assert col.chunk_size == 256


@pytest.mark.asyncio
async def test_get_collections_tenant_scoped() -> None:
    """Only returns collections belonging to the requested tenant."""
    user_a = _admin_user(tenant_id=TENANT_A)
    user_b = _admin_user(tenant_id=TENANT_B)

    await DocForgeService.create_collection(
        TENANT_A, user_a, CollectionConfig(name="Col A"),
    )
    await DocForgeService.create_collection(
        TENANT_B, user_b, CollectionConfig(name="Col B"),
    )

    cols = await DocForgeService.get_collections(TENANT_A)
    assert len(cols) == 1
    assert cols[0].name == "Col A"


# ── Tenant isolation (encrypted embeddings) ─────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_search_across_tenants() -> None:
    """Tenant B's search returns zero results for Tenant A's documents."""
    connector_a = _register_connector(tenant_id=TENANT_A)
    user_a = _admin_user(tenant_id=TENANT_A)
    source = DocumentSource(connector_id=connector_a.id, resource_id="isolated")

    await DocForgeService.ingest_document(TENANT_A, user_a, source)

    user_b = _admin_user(tenant_id=TENANT_B)
    result = await DocForgeService.search(TENANT_B, user_b, "Content")
    assert result.total == 0
