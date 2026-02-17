"""Document chunking with configurable size and overlap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """A single chunk of document text."""

    text: str
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        """Number of characters in the chunk."""
        return len(self.text)


def chunk_text(
    text: str,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
    metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Split *text* into overlapping chunks.

    Args:
        text: The full document text to chunk.
        chunk_size: Maximum number of characters per chunk.
        overlap: Number of characters shared between consecutive chunks.
        metadata: Extra metadata attached to every chunk.

    Returns:
        Ordered list of :class:`Chunk` objects.

    Raises:
        ValueError: If parameters are invalid.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")

    if not text:
        return []

    base_meta = metadata or {}
    chunks: list[Chunk] = []
    start = 0
    idx = 0

    while start < len(text):
        end = start + chunk_size
        chunk_text_slice = text[start:end]

        # Try to break at a word boundary when not at the end
        if end < len(text):
            last_space = chunk_text_slice.rfind(" ")
            if last_space > chunk_size // 2:
                end = start + last_space
                chunk_text_slice = text[start:end]

        chunk_meta = {**base_meta, "chunk_index": idx, "start_char": start, "end_char": end}
        chunks.append(Chunk(text=chunk_text_slice.strip(), index=idx, metadata=chunk_meta))

        step = end - start - overlap
        if step <= 0:
            step = 1  # guarantee forward progress
        start += step
        idx += 1

    return chunks
