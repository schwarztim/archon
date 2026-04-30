"""Tool node executor — documented stub for external tool/API integration.

TODO: Implement a tool registry lookup and invoke the registered tool handler.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("toolNode")
class ToolNodeExecutor(NodeExecutor):
    """Stub: records tool invocation; real execution deferred to v2.

    TODO(v2): look up toolName in the tool registry, invoke it with
    the configured parameters, and return the tool result.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        tool_name = config.get("toolName") or config.get("tool_name") or "unknown"
        tool_params = config.get("parameters") or {}

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "tool_name": tool_name,
                "parameters": tool_params,
                "result": None,  # TODO(v2): real tool invocation
            },
        )
