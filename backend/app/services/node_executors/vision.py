"""Vision node executor — documented stub for multimodal image+text inference.

TODO: Implement real vision calls via LiteLLM with image_url content parts.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("visionNode")
class VisionNodeExecutor(NodeExecutor):
    """Stub: returns placeholder vision analysis.

    TODO(v2): build an OpenAI-compatible vision payload with
    {"type": "image_url", "image_url": {"url": ...}} and call call_llm.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        model = config.get("model") or "gpt-4o"
        image_url = config.get("imageUrl") or config.get("image_url") or ""

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "model": model,
                "image_url": image_url,
                "analysis": "Vision analysis not yet implemented — stub response",
            },
        )
