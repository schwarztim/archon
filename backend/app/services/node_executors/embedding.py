"""Embedding node executor — documented stub for vector embedding generation.

TODO: Implement real embedding calls via LiteLLM embedding API
(litellm.aembedding) or the configured provider.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("embeddingNode")
class EmbeddingNodeExecutor(NodeExecutor):
    """Stub: returns placeholder embeddings.

    TODO(v2): call litellm.aembedding(model=config.model, input=text)
    and return the real embedding vector.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        model = config.get("model") or "text-embedding-ada-002"
        text = str(ctx.inputs) or config.get("text") or ""

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "model": model,
                "text_length": len(text),
                "embedding": [],  # TODO(v2): real vector
            },
        )
