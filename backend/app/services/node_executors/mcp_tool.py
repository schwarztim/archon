"""MCP tool node executor — documented stub for Model Context Protocol tool calls.

TODO: Implement real MCP client invocation via the mcp_service when the
container/session infrastructure is ready.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("mcpToolNode")
class MCPToolNodeExecutor(NodeExecutor):
    """Stub: records MCP tool call intent; real execution deferred to v2.

    TODO(v2): instantiate an MCP client for serverName, call toolName
    with the configured parameters, and return the tool result.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        server_name = config.get("serverName") or config.get("server_name") or "unknown"
        tool_name = config.get("toolName") or config.get("tool_name") or "unknown"
        tool_params = config.get("parameters") or {}

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "server_name": server_name,
                "tool_name": tool_name,
                "parameters": tool_params,
                "result": None,  # TODO(v2): real MCP invocation
            },
        )
