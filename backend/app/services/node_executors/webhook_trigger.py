"""Webhook trigger node executor — pass-through at execution time.

The webhook fires before the workflow is created; by the time this node
executes the trigger has already delivered its payload as the initial input.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("webhookTriggerNode")
class WebhookTriggerNodeExecutor(NodeExecutor):
    """Pass-through: the webhook payload is already in ctx.inputs."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(
            status="completed",
            output={"trigger": "webhook", "payload": ctx.inputs},
        )
