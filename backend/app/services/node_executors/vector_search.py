"""Vector search node executor — documented stub for similarity search.

TODO: Implement real vector similarity search via PGVector or a configured
vector store (Pinecone, Weaviate, Chroma).
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("vectorSearchNode")
class VectorSearchNodeExecutor(NodeExecutor):
    """Stub: records search intent; real search deferred to v2.

    TODO(v2): generate an embedding for the query, execute a cosine
    similarity search against the configured collection, return top-K results.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        collection = config.get("collection") or "default"
        query = config.get("query") or str(ctx.inputs)
        top_k = int(config.get("topK") or config.get("top_k") or 5)

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "collection": collection,
                "query": query,
                "top_k": top_k,
                "results": [],  # TODO(v2): real vector search results
            },
        )
