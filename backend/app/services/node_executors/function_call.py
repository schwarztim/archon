"""Function call node executor — documented stub for custom function execution.

TODO: Implement a safe sandboxed function runner (e.g. via RestrictedPython
or a separate process) for operator-defined code blocks.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("functionCallNode")
class FunctionCallNodeExecutor(NodeExecutor):
    """Stub: records function call intent; real execution deferred to v2.

    TODO(v2): run functionName with parameters in a sandboxed environment
    (RestrictedPython / subprocess isolation) and return the result.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        function_name = config.get("functionName") or config.get("function_name") or "unknown"
        parameters = config.get("parameters") or {}

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "function_name": function_name,
                "parameters": parameters,
                "result": None,  # TODO(v2): real sandboxed function execution
            },
        )
