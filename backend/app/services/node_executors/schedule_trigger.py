"""Schedule trigger node executor — pass-through at execution time.

The worker creates a WorkflowRun row when the cron fires; this node simply
records the trigger timestamp and passes through.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("scheduleTriggerNode")
class ScheduleTriggerNodeExecutor(NodeExecutor):
    """Pass-through: records trigger time and cron expression."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(
            status="completed",
            output={
                "trigger": "schedule",
                "cron": ctx.config.get("cron") or ctx.config.get("cronExpression"),
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "payload": ctx.inputs,
            },
        )
