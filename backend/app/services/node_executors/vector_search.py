"""Vector search node executor — in-memory cosine similarity via LiteLLM embeddings.

Phase 3 / WS9 — Executor Workstream 4 (W4d).

Promoted from STUB to BETA: embeds the query via ``call_embedding`` and
performs an in-memory cosine similarity search against a document store
supplied in the node config or upstream inputs.

Output shape::

    {
        "collection": str,
        "query": str,
        "top_k": int,
        "results": [{"id": str, "score": float, "text": str, "metadata": dict}],
        "result_count": int,
        "model": str,
        "latency_ms": float,
    }

BETA caveats (tracked in feature-matrix.yaml):
  - In-memory document store only: ``documents`` must be provided in
    ``config["documents"]`` or ``inputs["documents"]`` as a list of
    ``{"id": str, "text": str, "metadata": dict}`` records.  No live
    vector DB (PGVector, Pinecone, Chroma) is wired yet.
  - Documents are re-embedded on every call; no index caching.
  - Threshold filtering: results with ``score < threshold`` are dropped.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_TOP_K = 5
_DEFAULT_THRESHOLD = 0.0  # return all results by default


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [-1, 1] for two equal-length float vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _resolve_documents(ctx: NodeContext) -> list[dict[str, Any]]:
    """Pull the document list from config or upstream inputs."""
    docs = ctx.config.get("documents")
    if docs is None:
        docs = (ctx.inputs or {}).get("documents")
    if not isinstance(docs, list):
        return []
    return [d for d in docs if isinstance(d, dict) and "text" in d]


@register("vectorSearchNode")
class VectorSearchNodeExecutor(NodeExecutor):
    """Execute vectorSearchNode: embed query, cosine-rank documents, return top-K."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.langgraph.embeddings import call_embedding  # noqa: PLC0415

        config = ctx.config
        collection: str = str(config.get("collection") or "default")
        query_text: str = str(
            config.get("query_text")
            or config.get("query")
            or (ctx.inputs or {}).get("query", "")
        )
        if not query_text:
            return NodeResult(
                status="failed",
                error="ValueError: vectorSearchNode requires non-empty 'query_text'",
            )

        top_k: int = int(config.get("top_k") or config.get("topK") or _DEFAULT_TOP_K)
        threshold: float = float(
            config.get("threshold") if config.get("threshold") is not None else _DEFAULT_THRESHOLD
        )
        model: str = str(config.get("model") or _DEFAULT_MODEL)

        documents = _resolve_documents(ctx)
        if not documents:
            # No documents: return empty results rather than failing — callers
            # may legitimately pass an empty collection during bootstrapping.
            return NodeResult(
                status="completed",
                output={
                    "collection": collection,
                    "query": query_text,
                    "top_k": top_k,
                    "results": [],
                    "result_count": 0,
                    "model": model,
                    "latency_ms": 0.0,
                },
            )

        t0 = time.perf_counter()
        try:
            query_resp = await call_embedding(
                text=query_text,
                model=model,
                metadata={"step_id": ctx.step_id, "node_type": ctx.node_type},
            )
            query_vector = query_resp.vector

            # Embed all documents and score them.
            scored: list[tuple[float, dict[str, Any]]] = []
            for doc in documents:
                doc_text = str(doc.get("text", ""))
                if not doc_text:
                    continue
                doc_resp = await call_embedding(
                    text=doc_text,
                    model=model,
                    metadata={"step_id": ctx.step_id, "node_type": ctx.node_type},
                )
                score = _cosine_similarity(query_vector, doc_resp.vector)
                if score >= threshold:
                    scored.append((score, doc))

            # Sort descending by score, take top-K.
            scored.sort(key=lambda t: t[0], reverse=True)
            top_results = scored[:top_k]

        except Exception as exc:  # noqa: BLE001
            logger.warning("vectorSearchNode.execute_error", exc_info=True)
            return NodeResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = (time.perf_counter() - t0) * 1000.0

        results = [
            {
                "id": str(doc.get("id", f"doc-{i}")),
                "score": round(score, 6),
                "text": str(doc.get("text", "")),
                "metadata": dict(doc.get("metadata") or {}),
            }
            for i, (score, doc) in enumerate(top_results)
        ]

        return NodeResult(
            status="completed",
            output={
                "collection": collection,
                "query": query_text,
                "top_k": top_k,
                "results": results,
                "result_count": len(results),
                "model": query_resp.model_used,
                "latency_ms": round(latency_ms, 2),
            },
        )
