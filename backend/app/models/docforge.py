"""Pydantic models for the DocForge Enterprise Document Processing & RAG Pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EmbeddingStatus(str, Enum):
    """Status of the embedding process for a document."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AccessLevel(str, Enum):
    """Access level for document permissions."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class PermissionType(str, Enum):
    """Principal type for document permissions."""

    USER = "user"
    GROUP = "group"
    ROLE = "role"


# ── Input models ────────────────────────────────────────────────────


class DocumentSource(BaseModel):
    """Specifies the source connector and resource for document ingestion."""

    connector_id: UUID
    resource_id: str
    resource_type: str = "file"


class CollectionConfig(BaseModel):
    """Payload for creating a new document collection."""

    name: str
    description: str = ""
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = Field(default=512, ge=64, le=8192)
    chunk_overlap: int = Field(default=64, ge=0, le=1024)


class SearchFilters(BaseModel):
    """Optional filters applied to document search queries."""

    collection_id: UUID | None = None
    content_type: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class DocumentListFilters(BaseModel):
    """Filters for listing documents."""

    collection_id: UUID | None = None
    content_type: str | None = None
    embedding_status: EmbeddingStatus | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


# ── Domain models ──────────────────────────────────────────────────


class DocumentPermission(BaseModel):
    """Permission grant on a document for a principal."""

    document_id: UUID
    permission_type: PermissionType = PermissionType.USER
    principal_id: str
    access_level: AccessLevel = AccessLevel.READ


class DocumentChunk(BaseModel):
    """A single chunk produced from document parsing."""

    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    content: str
    chunk_index: int
    embedding_vector: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    """Ingested document with metadata and processing state."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    title: str
    content_type: str = "text/plain"
    source: DocumentSource | None = None
    chunk_count: int = 0
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    permissions_synced: bool = False
    collection_id: UUID | None = None
    dlp_clean: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class Collection(BaseModel):
    """A named collection of documents sharing an embedding configuration."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    name: str
    description: str = ""
    document_count: int = 0
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 512
    chunk_overlap: int = 64
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


# ── Search models ──────────────────────────────────────────────────


class SearchHit(BaseModel):
    """A single search result with relevance score and citation."""

    document_id: UUID
    chunk_id: UUID
    content_preview: str
    score: float
    citation: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Aggregated search results for a query."""

    query: str
    results: list[SearchHit] = Field(default_factory=list)
    total: int = 0
    processing_time_ms: float = 0.0


# ── Request schemas ────────────────────────────────────────────────


class IngestRequest(BaseModel):
    """API request body for document ingestion."""

    source: DocumentSource
    title: str = ""
    collection_id: UUID | None = None


class SearchRequest(BaseModel):
    """API request body for document search."""

    query: str
    filters: SearchFilters = Field(default_factory=SearchFilters)


__all__ = [
    "AccessLevel",
    "Collection",
    "CollectionConfig",
    "Document",
    "DocumentChunk",
    "DocumentListFilters",
    "DocumentPermission",
    "DocumentSource",
    "EmbeddingStatus",
    "IngestRequest",
    "PermissionType",
    "SearchFilters",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
]
