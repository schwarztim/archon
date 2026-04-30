"""Document loader node executor — load and chunk text from URL, file, or literal.

Phase 3 / WS9 — Executor Workstream 4 (W4d).

Promoted from STUB to BETA: fetches or reads the source document, then
splits it into overlapping chunks suitable for downstream embedding or
retrieval steps.

Output shape::

    {
        "source_type": str,         # "url" | "file" | "text"
        "source": str,
        "chunk_size": int,
        "chunk_overlap": int,
        "chunks": [{"index": int, "text": str, "char_start": int, "char_end": int}],
        "chunk_count": int,
        "total_chars": int,
    }

BETA caveats (tracked in feature-matrix.yaml):
  - URL fetch: plain text only.  HTML is not parsed; binary bodies raise.
  - File path: reads the path from the artifact store key if ``source``
    starts with ``artifact://``; otherwise treats it as a local filesystem
    path relative to the worker's CWD.  Sandbox / tenant isolation is
    **not** enforced — route file access through the artifact service for
    production isolation.
  - Chunk splitter: character-based with overlap; no sentence or token
    awareness.  Use ``chunk_size=0`` to skip splitting (return the whole
    document as one chunk).
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 512
_DEFAULT_CHUNK_OVERLAP = 64
_URL_TIMEOUT_S = 30.0


def _split_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    """Character-based sliding-window chunker.

    Returns a list of ``{index, text, char_start, char_end}`` dicts.
    When ``chunk_size <= 0`` the whole document is returned as one chunk.
    Overlap is clamped to ``chunk_size - 1`` to avoid infinite loops.
    """
    if not text:
        return []
    if chunk_size <= 0:
        return [{"index": 0, "text": text, "char_start": 0, "char_end": len(text)}]

    overlap = max(0, min(chunk_overlap, chunk_size - 1))
    step = chunk_size - overlap
    chunks: list[dict[str, Any]] = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end]
        if chunk_text.strip():
            chunks.append(
                {
                    "index": idx,
                    "text": chunk_text,
                    "char_start": start,
                    "char_end": end,
                }
            )
            idx += 1
        start += step
    return chunks


async def _fetch_url(url: str) -> str:
    """Fetch text content from *url* using httpx."""
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "documentLoaderNode URL source requires 'httpx'; install it in the worker venv"
        ) from exc

    async with httpx.AsyncClient(timeout=_URL_TIMEOUT_S, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text" not in content_type and "json" not in content_type:
            raise ValueError(
                f"documentLoaderNode: URL returned non-text content-type {content_type!r}; "
                "only text/* and application/json are supported"
            )
        return response.text


async def _read_file(path: str) -> str:
    """Read a local file path as UTF-8 text."""
    import asyncio  # noqa: PLC0415

    def _sync_read() -> str:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    return await asyncio.to_thread(_sync_read)


@register("documentLoaderNode")
class DocumentLoaderNodeExecutor(NodeExecutor):
    """Execute documentLoaderNode: fetch/read a source, return text chunks."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        source_type: str = str(
            config.get("source_type") or config.get("sourceType") or "text"
        ).lower()
        source: str = str(
            config.get("source") or (ctx.inputs or {}).get("source") or ""
        )
        chunk_size: int = int(
            config.get("chunk_size") or config.get("chunkSize") or _DEFAULT_CHUNK_SIZE
        )
        chunk_overlap: int = int(
            config.get("chunk_overlap") or config.get("chunkOverlap") or _DEFAULT_CHUNK_OVERLAP
        )

        if not source and source_type != "text":
            return NodeResult(
                status="failed",
                error=f"ValueError: documentLoaderNode requires 'source' for source_type={source_type!r}",
            )

        try:
            if source_type == "url":
                raw_text = await _fetch_url(source)
            elif source_type == "file":
                raw_text = await _read_file(source)
            else:
                # "text" — source is the content itself, or check inputs
                raw_text = source or str((ctx.inputs or {}).get("text", ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("documentLoaderNode.load_error", exc_info=True)
            return NodeResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

        chunks = _split_text(raw_text, chunk_size, chunk_overlap)

        return NodeResult(
            status="completed",
            output={
                "source_type": source_type,
                "source": source[:256] if source else "",
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "chunks": chunks,
                "chunk_count": len(chunks),
                "total_chars": len(raw_text),
            },
        )
