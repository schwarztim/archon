"""Input node executor — workflow entry point; passes through the initial input."""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("inputNode")
class InputNodeExecutor(NodeExecutor):
    """Entry point: passes through the workflow's initial input data."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        payload = ctx.config.get("initialInput") or ctx.inputs or {}
        return NodeResult(
            status="completed",
            output={"data": payload},
        )
