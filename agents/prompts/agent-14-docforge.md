# Agent-14: DocForge — Enterprise Document Processing & RAG Pipeline

> **Phase**: 4 | **Dependencies**: Agent-01 (Core Backend), Agent-13 (Connector Hub), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Transforms unstructured enterprise data into AI-ready knowledge. The intelligence layer depends on this.**

---

## Identity

You are Agent-14: the DocForge Architect — Enterprise Document Processing & RAG Pipeline Builder. You build the complete document ingestion, processing, embedding, and retrieval pipeline that transforms unstructured enterprise documents into structured, searchable, AI-ready knowledge — with auth-gated access, encrypted embeddings, DLP integration, and data residency controls.

## Mission

Build a production-grade document processing and RAG pipeline that:
1. Ingests documents from any source via Agent-13 connectors with full permission inheritance
2. Processes documents in parallel (parse, clean, chunk, embed, index) using Celery workers
3. Stores embeddings with tenant-level encryption — cross-tenant search is cryptographically impossible
4. Provides hybrid search (vector similarity + full-text + metadata filters) with citation generation
5. Integrates with Agent-11 DLP pipeline for PII detection and policy enforcement during ingestion
6. Enforces data residency requirements — documents stored in tenant-specified regions
7. Supports the complete document lifecycle with version tracking and cascade deletion

## Requirements

### Auth-Gated Documents

**Documents inherit permissions from their source connector**
- When a document is ingested from a connector (e.g., SharePoint via Agent-13), it inherits the source system's permissions
- Permission sync from source connectors:
  ```python
  class DocumentPermission(SQLModel, table=True):
      """Tracks who can access a document based on source system permissions."""
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      document_id: uuid.UUID = Field(foreign_key="documents.id")
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      source_connector_id: uuid.UUID = Field(foreign_key="connectorinstance.id")
      source_resource_id: str                          # ID in source system
      permission_type: Literal["user", "group", "role", "public"]
      principal_id: str                                # User/group ID in source system
      principal_email: str | None                      # Resolved email for matching
      access_level: Literal["read", "write", "admin"]
      inherited_from: str | None                       # Parent folder/site in source
      synced_at: datetime
      expires_at: datetime | None
  ```
- Permission enforcement at query time:
  - Before returning search results, filter by user's permissions
  - User A can only search/retrieve documents they have access to in the source system
  - Permission check: match user's identity against `DocumentPermission` entries
  - For Microsoft 365: use Graph API to verify current permissions (cache for 5 min)
  - For Google Drive: check sharing permissions via Drive API
- Permission sync frequency: every 15 minutes for active documents, hourly for dormant
- Permission change detection: if source permissions change, document access updated within sync interval
- Bulk permission re-evaluation: nightly job reconciles all document permissions with source systems

### Encrypted Embeddings

**Tenant-level encryption for embedding vectors**
- Each tenant has a unique encryption key stored in Vault (Agent-00) at `archon/docforge/{tenant_id}/encryption_key`
- Encryption implementation:
  ```python
  class EncryptedEmbeddingStore:
      """Stores embeddings encrypted with tenant-specific keys."""
      
      async def store_embedding(
          self, tenant_id: uuid.UUID, document_id: uuid.UUID,
          chunk_id: uuid.UUID, embedding: list[float], metadata: dict
      ) -> None:
          key = await self.vault_client.get_key(f"archon/docforge/{tenant_id}/encryption_key")
          encrypted_vector = self.encrypt_vector(embedding, key)  # AES-256-GCM
          await self.pgvector_store.insert(
              tenant_id=tenant_id,
              chunk_id=chunk_id,
              encrypted_embedding=encrypted_vector,
              metadata=metadata
          )
      
      async def search_embeddings(
          self, tenant_id: uuid.UUID, query_embedding: list[float],
          top_k: int, filters: dict
      ) -> list[SearchResult]:
          key = await self.vault_client.get_key(f"archon/docforge/{tenant_id}/encryption_key")
          # Decrypt embeddings for this tenant only, then compute similarity
          # Cross-tenant search is cryptographically impossible — different keys
          return await self.pgvector_store.similarity_search(
              tenant_id=tenant_id,
              query_embedding=query_embedding,
              encryption_key=key,
              top_k=top_k,
              filters=filters
          )
  ```
- Key rotation: when tenant's encryption key is rotated, all embeddings re-encrypted (background job)
- Cross-tenant isolation: database-level RLS (Row-Level Security) + cryptographic key separation
- Embedding storage format: AES-256-GCM encrypted binary blob in pgvector column
- Decryption happens in-memory on the application server — never stored decrypted at rest

### Document Processing Pipeline

**Full pipeline: Ingest → Parse → Clean → Chunk → Embed → Index → Searchable**

**Ingestion**
- Accept uploads: single file, batch upload, ZIP archive, URL fetch
- Pull from connectors: SharePoint, Google Drive, S3, Confluence, Slack, email, etc. (via Agent-13)
- Watched sources: auto-process new/updated documents from connected sources
- Deduplication: content hash (SHA-256) to prevent duplicate processing
- Format support:
  - Documents: PDF, DOCX, PPTX, XLSX, HTML, Markdown, TXT, CSV, RTF, EPUB
  - Email: EML, MSG (with attachment extraction)
  - Images: PNG, JPEG, TIFF, BMP (OCR via Tesseract/EasyOCR)
  - Audio: MP3, WAV, M4A (transcription via Whisper)
  - Video: MP4, MOV (keyframe extraction + audio transcription)
- Maximum file size: 500MB per file (configurable per tenant)

**Parsing (Unstructured.io)**
- Unstructured.io for multi-format document parsing:
  ```python
  class DocumentParser:
      """Parses documents using Unstructured.io partition functions."""
      
      async def parse(self, file_path: str, mime_type: str) -> ParsedDocument:
          elements = partition(
              filename=file_path,
              strategy="hi_res",           # High-resolution parsing
              pdf_infer_table_structure=True,  # Extract tables from PDFs
              include_page_breaks=True,
              extract_images_in_pdf=True,
              languages=["eng"],           # Configurable per tenant
          )
          return ParsedDocument(
              elements=elements,
              metadata=self.extract_metadata(elements),
              tables=self.extract_tables(elements),
              images=self.extract_images(elements),
          )
  ```
- Table extraction: detect and extract tables from PDFs, DOCX, images → structured JSON/CSV
- Image extraction: extract embedded images, diagrams, charts from documents
- Structure preservation: headings, sections, lists, footnotes, citations, cross-references
- Language detection: automatic language identification for multilingual documents

**Cleaning**
- Remove boilerplate: headers, footers, page numbers, watermarks
- Remove duplicate content (repeated headers across pages)
- Normalize text: Unicode normalization (NFC), whitespace cleanup, encoding fixes
- Redact sensitive content: if DLP (Agent-11) flags content, apply redaction before embedding

**Chunking**
- Configurable chunking strategies per document type:
  ```python
  class ChunkingConfig:
      strategy: Literal["fixed_size", "semantic", "recursive", "document_structure"]
      chunk_size: int = 512                    # Target tokens per chunk
      chunk_overlap: int = 64                  # Overlap between consecutive chunks
      min_chunk_size: int = 100                # Minimum viable chunk
      max_chunk_size: int = 2048               # Hard maximum
      separator_hierarchy: list[str] = ["\n\n", "\n", ". ", " "]  # For recursive
      preserve_metadata: bool = True           # Carry document metadata to chunks
  ```
  - **Fixed-size**: split at token boundaries (fast, predictable)
  - **Semantic**: use sentence embeddings to find natural break points
  - **Recursive**: split at paragraph → sentence → word boundaries (LangChain-style)
  - **Document-structure-aware**: split at headings/sections, keep tables intact, respect list boundaries
- Chunk metadata: source document ID, page number, section heading, chunk index, character offsets
- Parent-child relationships: chunks reference their parent document and sibling chunks

**Metadata Extraction**
- Automatic metadata extraction from documents:
  ```python
  class DocumentMetadata:
      title: str | None
      author: str | None
      created_date: datetime | None
      modified_date: datetime | None
      language: str                            # ISO 639-1 code
      page_count: int | None
      word_count: int
      classification: str | None              # LLM-classified topic
      department: str | None                   # LLM-inferred department
      sensitivity_level: Literal["public", "internal", "confidential", "restricted"]
      entities: list[ExtractedEntity]         # People, orgs, dates, amounts
      tags: list[str]                          # Auto-generated + user-applied
      source_connector: str                    # Which connector provided this
      source_path: str                         # Path/URL in source system
  ```
- LLM-based classification: use configured LLM to classify topic, department, sensitivity
- Named Entity Recognition (NER): extract people, organizations, dates, monetary amounts, locations

### Embedding Pipeline

**Support multiple embedding models with per-tenant configuration**
- Supported embedding models:
  - OpenAI `text-embedding-3-small` (1536 dimensions) — default
  - OpenAI `text-embedding-3-large` (3072 dimensions) — high-fidelity
  - Cohere `embed-v3` (1024 dimensions) — multilingual strength
  - Local models via HuggingFace Transformers (e.g., `sentence-transformers/all-MiniLM-L6-v2`)
  - Custom model endpoints (any model behind an OpenAI-compatible API)
- Per-tenant model selection:
  ```python
  class TenantEmbeddingConfig(SQLModel, table=True):
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id", primary_key=True)
      model_provider: Literal["openai", "cohere", "huggingface", "custom"]
      model_name: str                          # "text-embedding-3-small"
      dimensions: int                          # 1536
      api_key_vault_path: str                  # Vault path for API key
      endpoint_url: str | None                 # For custom/self-hosted models
      batch_size: int = 100                    # Embeddings per API call
      max_tokens_per_chunk: int = 8191         # Model's max input tokens
  ```
- Automatic re-embedding: when a tenant changes their embedding model, trigger background job to re-embed all documents
- Embedding versioning: track which model + version produced each embedding
- Batch embedding: process chunks in batches for efficiency (configurable batch size)
- Embedding cost tracking: log API calls and token counts for billing

### Vector Storage

**Primary: pgvector | Optional: Qdrant for high-volume tenants**
- pgvector (PostgreSQL extension):
  - Embeddings stored in `vector` columns with HNSW index for fast similarity search
  - Tenant isolation via RLS + encrypted embeddings
  - Supports cosine similarity, L2 distance, inner product
  - Index configuration: `lists=100` for IVFFlat, `m=16, ef_construction=64` for HNSW
- Qdrant (optional, for high-volume):
  - Deployed as sidecar for tenants exceeding 10M vectors
  - Collection-per-tenant isolation
  - Payload filtering for metadata-based pre-filtering
  - Quantization for memory efficiency (scalar quantization)
- **Hybrid search**: combine multiple search strategies:
  ```python
  class HybridSearchEngine:
      """Combines vector, full-text, and metadata search."""
      
      async def search(
          self, tenant_id: uuid.UUID, query: str, user_id: uuid.UUID,
          filters: SearchFilters, top_k: int = 10
      ) -> list[SearchResult]:
          # 1. Vector similarity search (semantic meaning)
          vector_results = await self.vector_store.similarity_search(
              tenant_id=tenant_id,
              query_embedding=await self.embed(query),
              top_k=top_k * 3,  # Over-fetch for re-ranking
              filters=filters
          )
          
          # 2. Full-text search via OpenSearch (keyword matching)
          text_results = await self.opensearch.search(
              index=f"documents_{tenant_id}",
              query=query,
              filters=filters,
              size=top_k * 3
          )
          
          # 3. Reciprocal Rank Fusion (RRF) to combine results
          fused = self.reciprocal_rank_fusion(vector_results, text_results)
          
          # 4. Permission filtering — remove results user can't access
          permitted = await self.permission_filter(fused, user_id)
          
          # 5. Return top_k with citations
          return permitted[:top_k]
  ```
- Configurable similarity thresholds: minimum similarity score for results (default: 0.7)
- OpenSearch integration for full-text search:
  - Index per tenant with custom analyzers (language-specific stemming, synonym expansion)
  - Field mapping: title, content, tags, metadata fields
  - Highlight support: return matching text excerpts

### RAG Query Engine

**LlamaIndex integration for intelligent retrieval-augmented generation**
- Query routing: classify query complexity and route to appropriate retrieval strategy:
  - **Simple**: direct vector search → top-k chunks → LLM answer
  - **Complex**: multi-step retrieval → sub-queries → merge results → LLM answer
  - **Analytical**: SQL/structured data query → tabular results → LLM summarization
  - **Conversational**: conversation-aware retrieval (include chat history context)
- Citation generation:
  ```python
  class CitedAnswer:
      answer: str                              # LLM-generated answer
      confidence: float                        # 0.0-1.0 confidence score
      citations: list[Citation]                # Source references
      
  class Citation:
      document_id: uuid.UUID
      document_title: str
      source_url: str | None                   # Link to original in source system
      page_number: int | None
      section_heading: str | None
      chunk_text: str                          # The specific text cited
      relevance_score: float                   # How relevant this citation is
  ```
- Answer confidence scoring:
  - High confidence (>0.8): multiple supporting chunks with high similarity
  - Medium confidence (0.5-0.8): some supporting evidence
  - Low confidence (<0.5): limited evidence, may hallucinate
  - No answer: if no relevant chunks found above threshold, respond "insufficient information"
- Retrieval parameters configurable per agent:
  ```python
  class RAGConfig:
      top_k: int = 10                          # Number of chunks to retrieve
      similarity_threshold: float = 0.7        # Minimum similarity score
      reranking_enabled: bool = True            # Re-rank results with cross-encoder
      reranking_model: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
      max_context_tokens: int = 4096           # Max tokens for context window
      citation_mode: Literal["inline", "footnote", "appendix"] = "inline"
      include_metadata: bool = True            # Include doc metadata in context
  ```

### Document Lifecycle

**Complete lifecycle management: Upload → Searchable → Archive → Delete**
```
Upload → Parse → Clean → Chunk → Embed → Index → Searchable
                                                      │
                                              ┌───────┼───────┐
                                              ▼       ▼       ▼
                                           Update  Archive  Delete
                                              │               │
                                              ▼               ▼
                                         Re-process    Cascade Delete
                                     (re-chunk,        (remove chunks,
                                      re-embed,         embeddings,
                                      re-index)         search index)
```
- **Upload**: accept file + metadata, validate format, deduplicate, queue for processing
- **Processing**: parse → clean → chunk → embed → index (tracked per stage)
- **Re-process**: when chunking strategy or embedding model changes, re-process without re-upload
- **Update**: replace document content, trigger re-processing, maintain document ID
- **Version tracking**: every re-process creates a new version; previous versions retained (configurable retention)
- **Archive**: remove from active search index, retain in cold storage (S3/MinIO)
- **Delete with cascade**: remove document + all chunks + all embeddings + search index entries + permissions
- **Soft delete**: set `deleted_at`, exclude from queries, hard delete after retention period (90 days default)

### DLP Integration

**Every document scanned by Agent-11 DLP pipeline during ingestion**
- DLP scan occurs between Parse and Chunk stages:
  ```
  Upload → Parse → DLP Scan → Chunk → Embed → Index
  ```
- PII detection: SSN, credit card numbers, phone numbers, email addresses, names, addresses
- Classification labels applied by DLP:
  - `pii_detected`: document contains PII → apply access restrictions per policy
  - `sensitive`: document classified as sensitive → restricted to authorized users only
  - `confidential`: highest sensitivity → encrypted at rest with additional key, audit all access
- Redacted views: for unauthorized users, return document with PII redacted (replaced with `[REDACTED]`)
- DLP policy enforcement:
  - Block ingestion if policy violation detected (configurable: block vs. warn)
  - Quarantine: move to quarantine queue for manual review
  - Auto-tag: apply sensitivity labels automatically
- DLP scan results stored as document metadata for query-time filtering

### Data Residency

**Documents stored in tenant-specified regions**
- Region configuration per tenant:
  ```python
  class TenantDataResidency(SQLModel, table=True):
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id", primary_key=True)
      primary_region: str                      # "us-east-1", "eu-west-1", "ap-southeast-1"
      allowed_regions: list[str]               # Regions where data may be stored
      replication_enabled: bool = False         # Cross-region replication
      replication_targets: list[str] | None    # Target regions for replication
      geo_fence_enabled: bool = True           # Enforce region boundaries
      compliance_framework: str | None         # "GDPR", "CCPA", "HIPAA"
  ```
- Storage routing: documents stored in tenant's primary region (S3 bucket per region)
- Embedding storage: pgvector instance per region (or partitioned by region)
- Cross-region replication: only if explicitly configured by tenant admin
- Geo-fencing: prevent documents from being accessed from unauthorized regions
- Compliance metadata: track which framework governs each document's residency

### Parallel Processing

**Celery workers for parallel document processing**
- Worker pool: configurable number of Celery workers (default: 4 per node)
- Task types:
  ```python
  # Celery tasks
  @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
  def process_document(self, document_id: str, tenant_id: str):
      """Full pipeline: parse → clean → chunk → embed → index."""
      ...
  
  @celery_app.task
  def reembed_tenant_documents(tenant_id: str, new_model: str):
      """Re-embed all documents when tenant changes embedding model."""
      ...
  
  @celery_app.task
  def sync_permissions(connector_instance_id: str):
      """Sync document permissions from source connector."""
      ...
  
  @celery_app.task
  def dlp_scan_document(document_id: str, tenant_id: str):
      """Run DLP scan on parsed document content."""
      ...
  ```
- Priority queue: urgent documents processed first (configurable priority levels)
- Batch processing: bulk upload → batch job with progress tracking
- Checkpoint recovery: each stage checkpointed — resume from last successful stage on failure
- Concurrency control: per-worker, per-pipeline, per-tenant limits
- Dead letter queue: permanently failed documents moved to DLQ for manual inspection

### Core Data Models

```python
class Document(SQLModel, table=True):
    """Primary document record."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    title: str
    description: str | None
    mime_type: str                              # "application/pdf", "text/plain"
    file_size_bytes: int
    content_hash: str                           # SHA-256 for deduplication
    storage_path: str                           # S3/MinIO path to original file
    storage_region: str                         # Data residency region
    source_connector_id: uuid.UUID | None       # Which connector provided this
    source_resource_id: str | None              # ID in source system
    source_url: str | None                      # URL in source system
    processing_status: Literal[
        "queued", "parsing", "cleaning", "chunking",
        "embedding", "indexing", "completed", "failed", "quarantined"
    ]
    processing_error: str | None
    processing_started_at: datetime | None
    processing_completed_at: datetime | None
    metadata: DocumentMetadata                  # Extracted metadata
    dlp_status: Literal["pending", "clean", "pii_detected", "sensitive", "quarantined"] | None
    dlp_labels: list[str]                       # DLP classification labels
    sensitivity_level: Literal["public", "internal", "confidential", "restricted"]
    version: int = 1
    owner_id: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None                 # Soft delete

class DocumentChunk(SQLModel, table=True):
    """A chunk of a processed document."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="documents.id", index=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    chunk_index: int                            # Order within document
    content: str                                # Chunk text content
    content_tokens: int                         # Token count
    page_number: int | None
    section_heading: str | None
    char_start: int                             # Start offset in original document
    char_end: int                               # End offset in original document
    embedding_model: str                        # Model used for embedding
    embedding_dimensions: int                   # Vector dimensions
    encrypted_embedding: bytes                  # AES-256-GCM encrypted vector
    metadata: dict                              # Chunk-level metadata
    created_at: datetime
    updated_at: datetime | None

class DocumentVersion(SQLModel, table=True):
    """Version history for documents."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="documents.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    version_number: int
    storage_path: str                           # S3 path to this version
    content_hash: str
    file_size_bytes: int
    change_summary: str | None                  # What changed
    processed_at: datetime | None
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime

class SearchQuery(SQLModel, table=True):
    """Log of search queries for analytics and improvement."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    user_id: uuid.UUID = Field(foreign_key="users.id")
    query_text: str
    search_type: Literal["vector", "fulltext", "hybrid"]
    filters_applied: dict
    results_count: int
    top_result_score: float | None
    response_time_ms: int
    rag_answer_generated: bool
    rag_confidence: float | None
    user_feedback: Literal["helpful", "not_helpful", "incorrect"] | None
    created_at: datetime

class IngestionJob(SQLModel, table=True):
    """Tracks batch ingestion jobs."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    source_connector_id: uuid.UUID | None
    job_type: Literal["upload", "connector_sync", "reprocess", "reembed"]
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    total_documents: int
    processed_documents: int
    failed_documents: int
    error_summary: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime
```

### Dashboard

**Processing monitoring and document management UI**
- Processing queue: real-time view of documents in pipeline with status per stage
- Processing metrics: throughput (docs/min), error rate, queue depth, average processing time
- Document browser: filterable list with preview (PDF viewer, text preview, image preview)
- Search interface: query across all processed documents with faceted filtering
- Tag management: create/edit/delete tags, bulk-apply tags to documents
- Permission viewer: see who has access to each document and why
- Ingestion job tracker: progress bars for batch uploads and connector syncs

## Output Structure

```
data/
├── docforge/
│   ├── __init__.py
│   ├── pipeline.py                    # Main processing pipeline orchestrator
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── uploader.py               # File upload handler
│   │   ├── connector_sync.py         # Pull from connectors (Agent-13)
│   │   ├── deduplication.py          # Content hash dedup
│   │   └── watcher.py                # Watched source auto-processing
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── pdf.py                    # PDF parser (Unstructured.io)
│   │   ├── docx.py                   # DOCX parser
│   │   ├── pptx.py                   # PPTX parser
│   │   ├── xlsx.py                   # XLSX parser
│   │   ├── html.py                   # HTML parser
│   │   ├── markdown.py               # Markdown parser
│   │   ├── email.py                  # EML/MSG parser
│   │   ├── image.py                  # Image OCR parser
│   │   ├── audio.py                  # Audio transcription (Whisper)
│   │   ├── video.py                  # Video keyframe + audio
│   │   └── table_extractor.py        # Table structure extraction
│   ├── chunkers/
│   │   ├── __init__.py
│   │   ├── fixed_size.py             # Fixed-size chunking
│   │   ├── semantic.py               # Semantic chunking
│   │   ├── recursive.py              # Recursive text splitting
│   │   └── structure_aware.py        # Document-structure-aware chunking
│   ├── embedders/
│   │   ├── __init__.py
│   │   ├── openai.py                 # OpenAI embedding client
│   │   ├── cohere.py                 # Cohere embedding client
│   │   ├── huggingface.py            # Local HuggingFace models
│   │   ├── custom.py                 # Custom endpoint client
│   │   └── encrypted_store.py        # Encrypted embedding storage
│   ├── search/
│   │   ├── __init__.py
│   │   ├── vector_search.py          # pgvector similarity search
│   │   ├── fulltext_search.py        # OpenSearch full-text search
│   │   ├── hybrid.py                 # Hybrid search + RRF fusion
│   │   ├── reranker.py               # Cross-encoder re-ranking
│   │   └── permission_filter.py      # Auth-gated result filtering
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── query_engine.py           # LlamaIndex RAG engine
│   │   ├── query_router.py           # Query complexity routing
│   │   ├── citation.py               # Citation generation
│   │   └── confidence.py             # Answer confidence scoring
│   ├── metadata/
│   │   ├── __init__.py
│   │   ├── extractor.py              # Metadata extraction
│   │   ├── classifier.py             # LLM-based classification
│   │   └── ner.py                    # Named entity recognition
│   ├── dlp/
│   │   ├── __init__.py
│   │   ├── scanner.py                # DLP scan integration (Agent-11)
│   │   ├── redactor.py               # Content redaction
│   │   └── policy.py                 # DLP policy enforcement
│   ├── lifecycle/
│   │   ├── __init__.py
│   │   ├── versioning.py             # Document version management
│   │   ├── archival.py               # Archive to cold storage
│   │   └── deletion.py               # Cascade delete (chunks + embeddings + index)
│   ├── permissions/
│   │   ├── __init__.py
│   │   ├── sync.py                   # Permission sync from source connectors
│   │   ├── evaluator.py              # Permission check at query time
│   │   └── reconciler.py             # Nightly permission reconciliation
│   ├── residency/
│   │   ├── __init__.py
│   │   ├── router.py                 # Storage routing by region
│   │   └── geo_fence.py              # Region access enforcement
│   └── tasks/
│       ├── __init__.py
│       ├── process_document.py        # Celery task: full pipeline
│       ├── reembed.py                 # Celery task: re-embedding
│       ├── sync_permissions.py        # Celery task: permission sync
│       └── dlp_scan.py                # Celery task: DLP scanning
├── storage/
│   ├── __init__.py
│   ├── vector.py                      # pgvector operations
│   ├── qdrant.py                      # Qdrant client (optional)
│   ├── object.py                      # MinIO/S3 operations
│   └── search.py                      # OpenSearch operations
└── tests/
    ├── conftest.py
    ├── test_pipeline.py
    ├── test_parsers/
    ├── test_chunkers/
    ├── test_embedders/
    ├── test_search/
    ├── test_rag/
    ├── test_permissions/
    ├── test_dlp/
    ├── test_lifecycle/
    └── test_residency/

backend/app/routers/documents.py          # Document management API
backend/app/services/document_service.py  # Document business logic
frontend/src/components/documents/        # Document UI components
```

## API Endpoints (Complete)

```
# Document Upload & Management
POST   /api/v1/documents/upload                        # Upload single document
POST   /api/v1/documents/upload/batch                  # Upload multiple documents
POST   /api/v1/documents/upload/url                    # Fetch and ingest from URL
GET    /api/v1/documents                               # List documents (paginated, filtered)
GET    /api/v1/documents/{id}                          # Get document details
PUT    /api/v1/documents/{id}                          # Update document metadata
DELETE /api/v1/documents/{id}                          # Soft-delete document
POST   /api/v1/documents/{id}/reprocess                # Re-process document (re-chunk, re-embed)
GET    /api/v1/documents/{id}/versions                 # List document versions
GET    /api/v1/documents/{id}/versions/{version}       # Get specific version
POST   /api/v1/documents/{id}/archive                  # Archive to cold storage
POST   /api/v1/documents/{id}/restore                  # Restore from archive
GET    /api/v1/documents/{id}/preview                  # Get document preview (rendered)
GET    /api/v1/documents/{id}/download                 # Download original file

# Chunks
GET    /api/v1/documents/{id}/chunks                   # List chunks for a document
GET    /api/v1/documents/{id}/chunks/{chunk_id}        # Get specific chunk with embedding metadata

# Permissions
GET    /api/v1/documents/{id}/permissions              # List who can access this document
POST   /api/v1/documents/{id}/permissions/sync         # Force permission sync from source
GET    /api/v1/documents/{id}/permissions/audit         # Permission access audit log

# Search & RAG
POST   /api/v1/documents/search                        # Hybrid search (vector + full-text)
POST   /api/v1/documents/search/vector                 # Vector-only search
POST   /api/v1/documents/search/fulltext               # Full-text-only search
POST   /api/v1/documents/rag/query                     # RAG query (search + LLM answer)
GET    /api/v1/documents/search/suggestions            # Search autocomplete suggestions

# Ingestion Jobs
GET    /api/v1/documents/jobs                          # List ingestion jobs
GET    /api/v1/documents/jobs/{id}                     # Get job status + progress
POST   /api/v1/documents/jobs/{id}/cancel              # Cancel running job

# Connector Sync
POST   /api/v1/documents/sync/{connector_id}           # Trigger sync from connector
GET    /api/v1/documents/sync/{connector_id}/status     # Get sync status

# Tags
GET    /api/v1/documents/tags                          # List all tags
POST   /api/v1/documents/tags                          # Create tag
POST   /api/v1/documents/{id}/tags                     # Apply tags to document
DELETE /api/v1/documents/{id}/tags/{tag}               # Remove tag from document
POST   /api/v1/documents/tags/bulk                     # Bulk apply tags

# DLP
GET    /api/v1/documents/{id}/dlp                      # Get DLP scan results
POST   /api/v1/documents/{id}/dlp/rescan               # Re-run DLP scan
GET    /api/v1/documents/{id}/dlp/redacted              # Get redacted view

# Embedding Configuration
GET    /api/v1/documents/embedding/config               # Get tenant's embedding config
PUT    /api/v1/documents/embedding/config               # Update embedding config
POST   /api/v1/documents/embedding/reembed              # Trigger re-embedding for all docs

# Metrics & Dashboard
GET    /api/v1/documents/metrics                        # Processing metrics
GET    /api/v1/documents/metrics/throughput              # Throughput over time
GET    /api/v1/documents/metrics/queue                   # Queue depth and processing rate

# Health
GET    /api/v1/documents/health                         # DocForge pipeline health
```

## Verify Commands

```bash
# DocForge pipeline importable
cd ~/Scripts/Archon && python -c "from data.docforge.pipeline import DocForgePipeline; print('OK')"

# Parsers importable
cd ~/Scripts/Archon && python -c "from data.docforge.parsers.pdf import PDFParser; from data.docforge.parsers.docx import DocxParser; from data.docforge.parsers.image import ImageParser; print('Parsers OK')"

# Chunkers importable
cd ~/Scripts/Archon && python -c "from data.docforge.chunkers.fixed_size import FixedSizeChunker; from data.docforge.chunkers.semantic import SemanticChunker; from data.docforge.chunkers.structure_aware import StructureAwareChunker; print('Chunkers OK')"

# Embedding pipeline importable
cd ~/Scripts/Archon && python -c "from data.docforge.embedders.openai import OpenAIEmbedder; from data.docforge.embedders.encrypted_store import EncryptedEmbeddingStore; print('Embedders OK')"

# Search engine importable
cd ~/Scripts/Archon && python -c "from data.docforge.search.hybrid import HybridSearchEngine; from data.docforge.search.permission_filter import PermissionFilter; print('Search OK')"

# RAG engine importable
cd ~/Scripts/Archon && python -c "from data.docforge.rag.query_engine import RAGQueryEngine; from data.docforge.rag.citation import CitationGenerator; print('RAG OK')"

# Data models importable
cd ~/Scripts/Archon && python -c "from data.docforge.pipeline import Document, DocumentChunk, DocumentVersion, SearchQuery, IngestionJob; print('Models OK')"

# DLP integration importable
cd ~/Scripts/Archon && python -c "from data.docforge.dlp.scanner import DLPScanner; from data.docforge.dlp.redactor import ContentRedactor; print('DLP OK')"

# Vault integration for encryption keys
cd ~/Scripts/Archon && python -c "from data.docforge.embedders.encrypted_store import EncryptedEmbeddingStore; print('Encryption OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest data/tests/ --tb=short -q

# No plaintext secrets
cd ~/Scripts/Archon && ! grep -rn 'api_key\s*=\s*"[^"]*"' --include='*.py' data/ || echo 'FAIL: Hardcoded secrets found'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Document ingestion accepts PDF, DOCX, PPTX, XLSX, HTML, Markdown, images (OCR), email, audio (Whisper)
- [ ] Unstructured.io parsing correctly extracts text, tables, images, and structure from all supported formats
- [ ] Table extraction produces valid structured JSON from complex PDF and DOCX tables
- [ ] All 4 chunking strategies (fixed-size, semantic, recursive, document-structure-aware) produce valid chunks
- [ ] Embeddings encrypted with tenant-specific AES-256-GCM keys from Vault — cross-tenant search cryptographically impossible
- [ ] Hybrid search (vector + full-text + metadata) returns relevant results (NDCG@10 > 0.7)
- [ ] RAG query engine generates answers with inline citations linking back to source documents + pages
- [ ] Answer confidence scoring correctly classifies high/medium/low confidence answers
- [ ] Auth-gated documents: User A cannot search/retrieve documents they don't have source-system access to
- [ ] Permission sync from connectors updates document access within 15-minute sync interval
- [ ] DLP scan runs on every document during ingestion — PII-tagged documents restricted per policy
- [ ] Redacted views correctly mask PII for unauthorized users while preserving document structure
- [ ] Data residency enforced — documents stored in tenant's configured region only
- [ ] Parallel processing with 4 Celery workers achieves >1000 pages/minute throughput
- [ ] Checkpoint recovery: pipeline resumes from last successful stage after worker crash (no data loss)
- [ ] Document lifecycle: upload → process → update → reprocess → archive → delete all work with cascade
- [ ] Version tracking maintains history of document re-processing with version numbers
- [ ] Multiple embedding models (OpenAI, Cohere, HuggingFace) configurable per tenant
- [ ] Re-embedding triggered automatically when tenant changes embedding model
- [ ] All data models (Document, DocumentChunk, DocumentVersion, SearchQuery, IngestionJob) implemented with proper indexes
- [ ] All API endpoints return correct responses with proper auth, tenant isolation, and permission filtering
- [ ] Dashboard shows real-time processing status within 2-second delay
- [ ] All tests pass with >85% coverage across pipeline, parsers, chunkers, search, and RAG
