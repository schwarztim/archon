# ADR-002: Database Strategy

> **Status**: ACCEPTED
> **Date**: 2026-02-16
> **Decision**: PostgreSQL 16 with SQLModel (SQLAlchemy 2.0 async) as the primary datastore, Alembic for migrations, PGVector for embeddings, and Neo4j for governance graph only.

## Context

Archon requires a relational datastore for agents, workflows, tenants, and audit data. It also needs vector similarity search for agent memory and RAG embeddings. Multiple agents write to the database concurrently from async FastAPI endpoints, so the ORM and driver must support Python's `asyncio` natively. A graph database is needed for governance relationships (policy → role → permission), but not for general application data.

## Decision

### Primary Database: PostgreSQL 16

- **ORM**: SQLModel (built on SQLAlchemy 2.0 with Pydantic integration). Models are shared between API schemas and DB tables, reducing duplication.
- **Async Driver**: `asyncpg` via SQLAlchemy's `create_async_engine`. All database I/O is non-blocking.
- **Connection Pooling**: SQLAlchemy's built-in async pool backed by `asyncpg`, configured with `pool_size=20`, `max_overflow=10`, and `pool_pre_ping=True` for stale connection detection.
- **Migrations**: Alembic with async support. All schema changes go through versioned migration scripts — no auto-create in production.

### Why Async Over Sync

FastAPI runs on `uvicorn` (ASGI). Using synchronous DB drivers (e.g., `psycopg2`) blocks the event loop, degrading throughput under concurrent load. Async with `asyncpg` allows the server to handle other requests while waiting on DB I/O, which is critical for meeting the <200ms p95 latency target.

### Vector Storage: PGVector Extension

- The `pgvector` extension is installed on the same PostgreSQL instance.
- Embedding columns use the `vector(1536)` type for OpenAI-compatible dimensions.
- Similarity search uses cosine distance (`<=>` operator) with an IVFFlat or HNSW index.
- This avoids a separate vector database (Pinecone, Weaviate) and keeps operational complexity low.

### Graph Database: Neo4j (Governance Only)

- Neo4j is used exclusively for the governance/policy graph: roles, permissions, policy inheritance, and compliance lineage.
- Application CRUD (agents, workflows, tenants) stays in PostgreSQL.
- Neo4j is accessed via the `neo4j` async Python driver; queries are read-heavy and cached in Redis.

### Configuration

All connection strings use `ARCHON_`-prefixed environment variables:

```
ARCHON_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/archon
ARCHON_NEO4J_URI=bolt://host:7687
```

## Consequences

- Single PostgreSQL instance handles relational + vector data, reducing infrastructure cost
- Async throughout means no accidental event-loop blocking from DB calls
- Alembic migrations enforce schema versioning and safe rollbacks
- SQLModel shares types between API layer and DB layer, reducing drift
- Neo4j adds operational overhead but is scoped narrowly to governance
- Team must avoid synchronous SQLAlchemy patterns (e.g., `Session` instead of `AsyncSession`)
