"""Output node executor — workflow exit point; collects and returns final output."""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("outputNode")
class OutputNodeExecutor(NodeExecutor):
    """Terminal node: collects upstream results as the workflow's final output."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Merge all upstream outputs; prefer explicit output_key config
        output_key: str | None = ctx.config.get("outputKey")
        if output_key and output_key in ctx.inputs:
            final = ctx.inputs[output_key]
        else:
            # Merge all upstream into one dict / pick the most recent
            final = {}
            for v in ctx.inputs.values():
                if isinstance(v, dict):
                    final.update(v)
                else:
                    final["output"] = v
        return NodeResult(
            status="completed",
            output={"result": final},
        )
