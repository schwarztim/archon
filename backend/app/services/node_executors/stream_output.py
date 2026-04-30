"""Stream output node executor — documented stub for streaming delivery.

TODO: Implement real streaming via the WebSocket manager so partial tokens
are pushed as they arrive.  For v1, collects and returns the full output.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("streamOutputNode")
class StreamOutputNodeExecutor(NodeExecutor):
    """Stub: collects upstream output; real streaming deferred to v2.

    TODO(v2): wire to WebSocket ExecutionStreamManager to push partial tokens.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Collect all upstream outputs as the stream content
        content = ""
        for v in ctx.inputs.values():
            if isinstance(v, dict):
                content += str(v.get("content") or v)
            else:
                content += str(v)

        return NodeResult(
            status="completed",
            output={"_stub": True, "streamed_content": content},
        )
