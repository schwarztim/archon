"""Document loader node executor — documented stub for document chunking.

TODO: Implement real document loading and chunking via the docforge pipeline
or a configured connector (S3, Google Drive, local filesystem).
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("documentLoaderNode")
class DocumentLoaderNodeExecutor(NodeExecutor):
    """Stub: records load intent; real loading deferred to v2.

    TODO(v2): load documents from the configured source, chunk them using
    the configured strategy, and return chunks with metadata.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        source = config.get("source") or "unknown"
        chunk_size = int(config.get("chunkSize") or config.get("chunk_size") or 512)

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "source": source,
                "chunk_size": chunk_size,
                "chunks": [],  # TODO(v2): real document chunks
                "chunk_count": 0,
            },
        )
