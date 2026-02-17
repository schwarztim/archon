"""DocForge processing pipeline — ingest → parse → chunk → embed → search."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integrations.docforge.chunker import Chunk, chunk_text
from integrations.docforge.parsers import ParsedDocument, parse


@dataclass
class DocForgePipeline:
    """Orchestrates document ingestion, parsing, chunking, and (stub) embedding.

    Args:
        chunk_size: Maximum characters per chunk.
        overlap: Character overlap between consecutive chunks.
    """

    chunk_size: int = 512
    overlap: int = 64
    _store: dict[str, list[Chunk]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, source: str | Path, *, fmt: str | None = None) -> list[Chunk]:
        """End-to-end: parse → chunk → embed a single document.

        Args:
            source: File path or raw content string.
            fmt: Explicit format override passed to the parser.

        Returns:
            List of chunks produced from the document.
        """
        doc = self.parse(source, fmt=fmt)
        chunks = self.chunk(doc)
        self.embed(chunks)
        doc_id = self._doc_id(doc)
        self._store[doc_id] = chunks
        return chunks

    def parse(self, source: str | Path, *, fmt: str | None = None) -> ParsedDocument:
        """Parse a document into a :class:`ParsedDocument`.

        Args:
            source: File path or raw content string.
            fmt: Explicit format override.

        Returns:
            Parsed document with extracted text and metadata.
        """
        return parse(source, fmt=fmt)

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        """Split a parsed document into overlapping chunks.

        Args:
            doc: A previously parsed document.

        Returns:
            Ordered list of text chunks.
        """
        return chunk_text(
            doc.content,
            chunk_size=self.chunk_size,
            overlap=self.overlap,
            metadata=doc.metadata,
        )

    def embed(self, chunks: list[Chunk]) -> list[list[float]]:
        """Generate embeddings for *chunks* (stub).

        This is a placeholder that returns zero-vectors.  A real
        implementation would call a sentence-transformer or external
        embedding API.

        Args:
            chunks: Chunks to embed.

        Returns:
            List of embedding vectors (currently all zeros).
        """
        embedding_dim = 384  # placeholder dimension
        return [[0.0] * embedding_dim for _ in chunks]

    def search(self, query: str, *, top_k: int = 5) -> list[Chunk]:
        """Search stored chunks for *query* (stub).

        This is a placeholder that returns the first *top_k* chunks across
        all ingested documents.  A real implementation would perform vector
        similarity search.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return.

        Returns:
            List of matching chunks.
        """
        all_chunks: list[Chunk] = []
        for chunks in self._store.values():
            all_chunks.extend(chunks)
        return all_chunks[:top_k]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _doc_id(doc: ParsedDocument) -> str:
        """Derive a deterministic ID from document content."""
        return hashlib.sha256(doc.content.encode()).hexdigest()[:16]
