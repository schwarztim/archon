"""DocForge document processing & RAG pipeline routes.

All endpoints are authenticated, RBAC-checked, and tenant-scoped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import require_permission
from app.models.docforge import (
    CollectionConfig,
    DocumentListFilters,
    EmbeddingStatus,
    IngestRequest,
    SearchRequest,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.docforge_service import DocForgeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["DocForge"])


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Document endpoints ──────────────────────────────────────────────


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    body: IngestRequest,
    user: AuthenticatedUser = Depends(require_permission("documents", "create")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Ingest a document from a connector with DLP scan and permission inheritance."""
    try:
        doc = await DocForgeService.ingest_document(
            tenant_id=user.tenant_id,
            user=user,
            source=body.source,
            title=body.title,
            collection_id=body.collection_id,
            secrets_mgr=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {
        "data": doc.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/search")
async def search_documents(
    body: SearchRequest,
    user: AuthenticatedUser = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    """Search documents with hybrid vector + full-text, auth-filtered results."""
    result = await DocForgeService.search(
        tenant_id=user.tenant_id,
        user=user,
        query=body.query,
        filters=body.filters,
    )
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/{doc_id}")
async def get_document(
    doc_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    """Get a single document by ID, permission-checked."""
    try:
        doc = await DocForgeService.get_document(
            tenant_id=user.tenant_id,
            user=user,
            doc_id=doc_id,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return {
        "data": doc.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("")
async def list_documents(
    collection_id: UUID | None = Query(default=None),
    content_type: str | None = Query(default=None),
    embedding_status: EmbeddingStatus | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    """List documents with pagination and permission filtering."""
    filters = DocumentListFilters(
        collection_id=collection_id,
        content_type=content_type,
        embedding_status=embedding_status,
        limit=limit,
        offset=offset,
    )
    docs, total = await DocForgeService.list_documents(
        tenant_id=user.tenant_id,
        user=user,
        filters=filters,
    )
    return {
        "data": [d.model_dump(mode="json") for d in docs],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("documents", "delete")),
) -> None:
    """Delete a document with cascade removal of chunks, embeddings, and permissions."""
    try:
        await DocForgeService.delete_document(
            tenant_id=user.tenant_id,
            user=user,
            doc_id=doc_id,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


@router.post("/{doc_id}/reprocess")
async def reprocess_document(
    doc_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("documents", "update")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Re-chunk and re-embed an existing document."""
    try:
        doc = await DocForgeService.reprocess_document(
            tenant_id=user.tenant_id,
            user=user,
            doc_id=doc_id,
            secrets_mgr=secrets,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return {
        "data": doc.model_dump(mode="json"),
        "meta": _meta(),
    }


# ── Collection endpoints ───────────────────────────────────────────


collections_router = APIRouter(prefix="/collections", tags=["DocForge Collections"])


@collections_router.get("")
async def list_collections(
    user: AuthenticatedUser = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    """List document collections for the authenticated tenant."""
    cols = await DocForgeService.get_collections(user.tenant_id)
    return {
        "data": [c.model_dump(mode="json") for c in cols],
        "meta": _meta(),
    }


@collections_router.post("", status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: CollectionConfig,
    user: AuthenticatedUser = Depends(require_permission("documents", "create")),
) -> dict[str, Any]:
    """Create a new document collection."""
    collection = await DocForgeService.create_collection(
        tenant_id=user.tenant_id,
        user=user,
        config=body,
    )
    return {
        "data": collection.model_dump(mode="json"),
        "meta": _meta(),
    }
