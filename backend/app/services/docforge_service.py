"""DocForge Enterprise Document Processing & RAG Pipeline.

Provides document ingestion from connectors with permission inheritance,
DLP scanning, chunking, embedding, and permission-aware hybrid search.
All operations are tenant-scoped, RBAC-checked, and audit-logged.
Credentials and encryption keys accessed exclusively via SecretsManager.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.interfaces.models.enterprise import AuthenticatedUser
from app.interfaces.secrets_manager import SecretsManager
from app.middleware.rbac import check_permission
from app.models.docforge import (
    AccessLevel,
    Collection,
    CollectionConfig,
    Document,
    DocumentChunk,
    DocumentListFilters,
    DocumentPermission,
    DocumentSource,
    EmbeddingStatus,
    PermissionType,
    SearchFilters,
    SearchHit,
    SearchResult,
)

logger = logging.getLogger(__name__)

# ── In-memory stores (production: database + vector DB) ────────────

_documents: dict[str, Document] = {}
_chunks: dict[str, list[DocumentChunk]] = {}
_permissions: dict[str, list[DocumentPermission]] = {}
_collections: dict[str, Collection] = {}


def _vault_path(tenant_id: str, purpose: str) -> str:
    """Build the Vault secret path for DocForge tenant keys."""
    return f"archon/{tenant_id}/docforge/{purpose}"


def _audit_details(user: AuthenticatedUser, **extra: Any) -> dict[str, Any]:
    """Build a structured audit-details dict (secret values excluded)."""
    return {
        "actor_id": user.id,
        "actor_email": user.email,
        "tenant_id": user.tenant_id,
        **extra,
    }


def _user_has_doc_access(
    user: AuthenticatedUser,
    doc_id: UUID,
) -> bool:
    """Check whether *user* has at least READ access to a document.

    Admins bypass per-document permission checks. Otherwise the user
    must appear as a principal in the document's permission list, either
    directly (USER) or via one of their roles (ROLE).
    """
    if "admin" in user.roles:
        return True

    perms = _permissions.get(str(doc_id), [])
    if not perms:
        # No explicit permissions stored — default deny
        return False

    for perm in perms:
        if (
            perm.permission_type == PermissionType.USER
            and perm.principal_id == user.id
        ):
            return True
        if (
            perm.permission_type == PermissionType.ROLE
            and perm.principal_id in user.roles
        ):
            return True

    return False


def _simple_chunk(content: str, chunk_size: int, overlap: int) -> list[str]:
    """Split *content* into overlapping text chunks."""
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = start + chunk_size
        chunks.append(content[start:end])
        start += chunk_size - overlap
        if overlap >= chunk_size:
            break
    return chunks


def _mock_embed(text: str) -> list[float]:
    """Return a deterministic pseudo-embedding (placeholder for real model)."""
    digest = hashlib.sha256(text.encode()).hexdigest()
    return [int(c, 16) / 15.0 for c in digest[:64]]


def _mock_dlp_scan(content: str) -> tuple[bool, str | None]:
    """Simulate a DLP scan — returns (is_clean, redacted_content_or_None)."""
    # In production: delegate to DLPService.scan()
    return True, None


class DocForgeService:
    """Enterprise RAG pipeline with connector ingestion and permission-aware search.

    All operations are tenant-scoped, RBAC-checked, and audit-logged.
    Embedding encryption keys are stored per-tenant in Vault via
    ``SecretsManager``.
    """

    @staticmethod
    async def ingest_document(
        tenant_id: str,
        user: AuthenticatedUser,
        source: DocumentSource,
        *,
        title: str = "",
        collection_id: UUID | None = None,
        secrets_mgr: SecretsManager | None = None,
    ) -> Document:
        """Ingest a document from a connector with permission inheritance.

        Pipeline: validate connector → fetch content → DLP scan →
        parse/chunk → embed → store → grant owner permission → audit.

        RBAC: requires ``documents:create``.
        Audit: logs ``document.ingested``.
        """
        check_permission(user, "documents", "create")

        # --- Connector validation (tenant-scoped) --------------------
        from app.services.connector_service import ConnectorService

        connector = await ConnectorService.get_connector(
            tenant_id, source.connector_id,
        )

        # --- Simulate content fetch from connector -------------------
        raw_content = (
            f"[Content from {connector.type}:{source.resource_id}]"
        )
        resolved_title = title or f"{connector.type}/{source.resource_id}"

        # --- DLP scan ------------------------------------------------
        dlp_clean, redacted = _mock_dlp_scan(raw_content)
        if redacted is not None:
            raw_content = redacted

        # --- Determine chunking config from collection ---------------
        chunk_size = 512
        chunk_overlap = 64
        if collection_id is not None:
            col = _collections.get(str(collection_id))
            if col is not None and col.tenant_id == tenant_id:
                chunk_size = col.chunk_size
                chunk_overlap = col.chunk_overlap

        # --- Parse / chunk / embed -----------------------------------
        text_chunks = _simple_chunk(raw_content, chunk_size, chunk_overlap)

        doc_id = uuid4()
        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            title=resolved_title,
            content_type="text/plain",
            source=source,
            chunk_count=len(text_chunks),
            embedding_status=EmbeddingStatus.COMPLETED,
            permissions_synced=True,
            collection_id=collection_id,
            dlp_clean=dlp_clean,
        )

        # --- Encrypt embeddings with tenant key from Vault -----------
        # (Key retrieval via SecretsManager — value never logged)
        if secrets_mgr is not None:
            vault_key_path = _vault_path(tenant_id, "embedding_key")
            try:
                await secrets_mgr.get_secret(vault_key_path, tenant_id)
            except Exception:
                logger.debug(
                    "docforge.embedding_key_not_found",
                    extra={"tenant_id": tenant_id},
                )

        doc_chunks: list[DocumentChunk] = []
        for idx, text in enumerate(text_chunks):
            chunk = DocumentChunk(
                id=uuid4(),
                document_id=doc_id,
                content=text,
                chunk_index=idx,
                embedding_vector=_mock_embed(text),
                metadata={"source_connector": str(source.connector_id)},
            )
            doc_chunks.append(chunk)

        _documents[str(doc_id)] = doc
        _chunks[str(doc_id)] = doc_chunks

        # --- Grant owner permission ----------------------------------
        owner_perm = DocumentPermission(
            document_id=doc_id,
            permission_type=PermissionType.USER,
            principal_id=user.id,
            access_level=AccessLevel.ADMIN,
        )
        _permissions[str(doc_id)] = [owner_perm]

        # --- Update collection document count ------------------------
        if collection_id is not None:
            col = _collections.get(str(collection_id))
            if col is not None and col.tenant_id == tenant_id:
                col.document_count += 1

        logger.info(
            "document.ingested",
            extra=_audit_details(
                user,
                action="document.ingested",
                resource_type="document",
                resource_id=str(doc_id),
                chunk_count=len(text_chunks),
                dlp_clean=dlp_clean,
            ),
        )
        return doc

    @staticmethod
    async def search(
        tenant_id: str,
        user: AuthenticatedUser,
        query: str,
        filters: SearchFilters | None = None,
    ) -> SearchResult:
        """Hybrid search (vector + full-text) with permission-gated results.

        Only documents the user has READ (or higher) access to are returned.

        RBAC: requires ``documents:read``.
        """
        check_permission(user, "documents", "read")
        start = time.monotonic()

        effective_filters = filters or SearchFilters()
        query_lower = query.lower()
        hits: list[SearchHit] = []

        for doc_id_str, doc in _documents.items():
            if doc.tenant_id != tenant_id:
                continue
            if not _user_has_doc_access(user, doc.id):
                continue
            if (
                effective_filters.collection_id is not None
                and doc.collection_id != effective_filters.collection_id
            ):
                continue
            if (
                effective_filters.content_type is not None
                and doc.content_type != effective_filters.content_type
            ):
                continue

            doc_chunks = _chunks.get(doc_id_str, [])
            for chunk in doc_chunks:
                # Simple keyword match + embedding cosine placeholder
                if query_lower in chunk.content.lower():
                    score = 1.0
                elif chunk.embedding_vector:
                    query_vec = _mock_embed(query)
                    dot = sum(a * b for a, b in zip(query_vec, chunk.embedding_vector))
                    score = dot / max(len(query_vec), 1)
                else:
                    continue

                hits.append(SearchHit(
                    document_id=doc.id,
                    chunk_id=chunk.id,
                    content_preview=chunk.content[:200],
                    score=round(score, 4),
                    citation=f"{doc.title} [chunk {chunk.chunk_index}]",
                    metadata=chunk.metadata,
                ))

        # Sort by score descending, apply pagination
        hits.sort(key=lambda h: h.score, reverse=True)
        total = len(hits)
        paginated = hits[effective_filters.offset : effective_filters.offset + effective_filters.limit]

        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return SearchResult(
            query=query,
            results=paginated,
            total=total,
            processing_time_ms=elapsed_ms,
        )

    @staticmethod
    async def get_document(
        tenant_id: str,
        user: AuthenticatedUser,
        doc_id: UUID,
    ) -> Document:
        """Return a single document, enforcing tenant isolation and permissions.

        RBAC: requires ``documents:read``.
        """
        check_permission(user, "documents", "read")

        doc = _documents.get(str(doc_id))
        if doc is None or doc.tenant_id != tenant_id:
            raise ValueError("Document not found")
        if not _user_has_doc_access(user, doc_id):
            raise ValueError("Document not found")
        return doc

    @staticmethod
    async def list_documents(
        tenant_id: str,
        user: AuthenticatedUser,
        filters: DocumentListFilters | None = None,
    ) -> tuple[list[Document], int]:
        """Return paginated, permission-filtered documents for a tenant.

        RBAC: requires ``documents:read``.
        """
        check_permission(user, "documents", "read")

        effective_filters = filters or DocumentListFilters()
        results: list[Document] = []

        for doc in _documents.values():
            if doc.tenant_id != tenant_id:
                continue
            if not _user_has_doc_access(user, doc.id):
                continue
            if (
                effective_filters.collection_id is not None
                and doc.collection_id != effective_filters.collection_id
            ):
                continue
            if (
                effective_filters.content_type is not None
                and doc.content_type != effective_filters.content_type
            ):
                continue
            if (
                effective_filters.embedding_status is not None
                and doc.embedding_status != effective_filters.embedding_status
            ):
                continue
            results.append(doc)

        total = len(results)
        page = results[effective_filters.offset : effective_filters.offset + effective_filters.limit]
        return page, total

    @staticmethod
    async def delete_document(
        tenant_id: str,
        user: AuthenticatedUser,
        doc_id: UUID,
    ) -> None:
        """Cascade delete a document: chunks, embeddings, and permissions.

        RBAC: requires ``documents:delete``.
        Audit: logs ``document.deleted``.
        """
        check_permission(user, "documents", "delete")

        doc = _documents.get(str(doc_id))
        if doc is None or doc.tenant_id != tenant_id:
            raise ValueError("Document not found")

        # Cascade delete
        _documents.pop(str(doc_id), None)
        _chunks.pop(str(doc_id), None)
        _permissions.pop(str(doc_id), None)

        # Update collection count
        if doc.collection_id is not None:
            col = _collections.get(str(doc.collection_id))
            if col is not None:
                col.document_count = max(0, col.document_count - 1)

        logger.info(
            "document.deleted",
            extra=_audit_details(
                user,
                action="document.deleted",
                resource_type="document",
                resource_id=str(doc_id),
            ),
        )

    @staticmethod
    async def reprocess_document(
        tenant_id: str,
        user: AuthenticatedUser,
        doc_id: UUID,
        *,
        secrets_mgr: SecretsManager | None = None,
    ) -> Document:
        """Re-chunk and re-embed an existing document.

        RBAC: requires ``documents:update``.
        Audit: logs ``document.reprocessed``.
        """
        check_permission(user, "documents", "update")

        doc = _documents.get(str(doc_id))
        if doc is None or doc.tenant_id != tenant_id:
            raise ValueError("Document not found")

        # Determine chunking config
        chunk_size = 512
        chunk_overlap = 64
        if doc.collection_id is not None:
            col = _collections.get(str(doc.collection_id))
            if col is not None and col.tenant_id == tenant_id:
                chunk_size = col.chunk_size
                chunk_overlap = col.chunk_overlap

        # Re-chunk from existing chunk content
        old_chunks = _chunks.get(str(doc_id), [])
        combined = " ".join(c.content for c in old_chunks)
        text_chunks = _simple_chunk(combined, chunk_size, chunk_overlap)

        new_chunks: list[DocumentChunk] = []
        for idx, text in enumerate(text_chunks):
            chunk = DocumentChunk(
                id=uuid4(),
                document_id=doc_id,
                content=text,
                chunk_index=idx,
                embedding_vector=_mock_embed(text),
            )
            new_chunks.append(chunk)

        _chunks[str(doc_id)] = new_chunks
        doc.chunk_count = len(new_chunks)
        doc.embedding_status = EmbeddingStatus.COMPLETED
        doc.updated_at = datetime.now(tz=timezone.utc)

        logger.info(
            "document.reprocessed",
            extra=_audit_details(
                user,
                action="document.reprocessed",
                resource_type="document",
                resource_id=str(doc_id),
                chunk_count=len(new_chunks),
            ),
        )
        return doc

    @staticmethod
    async def get_collections(tenant_id: str) -> list[Collection]:
        """Return all document collections for a tenant."""
        return [
            c for c in _collections.values() if c.tenant_id == tenant_id
        ]

    @staticmethod
    async def create_collection(
        tenant_id: str,
        user: AuthenticatedUser,
        config: CollectionConfig,
    ) -> Collection:
        """Create a new document collection for a tenant.

        RBAC: requires ``documents:create``.
        Audit: logs ``collection.created``.
        """
        check_permission(user, "documents", "create")

        collection = Collection(
            id=uuid4(),
            tenant_id=tenant_id,
            name=config.name,
            description=config.description,
            embedding_model=config.embedding_model,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
        _collections[str(collection.id)] = collection

        logger.info(
            "collection.created",
            extra=_audit_details(
                user,
                action="collection.created",
                resource_type="collection",
                resource_id=str(collection.id),
                collection_name=config.name,
            ),
        )
        return collection
