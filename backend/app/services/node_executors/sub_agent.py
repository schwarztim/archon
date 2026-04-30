"""Sub-agent node executor — invokes another agent by ID via execute_agent."""

from __future__ import annotations

import logging

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


@register("subAgentNode")
class SubAgentNodeExecutor(NodeExecutor):
    """Call execute_agent with a referenced agent_id."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.langgraph.engine import execute_agent  # noqa: PLC0415

        config = ctx.config
        agent_id: str | None = config.get("agentId") or config.get("agent_id")
        if not agent_id:
            return NodeResult(
                status="failed",
                error="subAgentNode: agentId is required",
            )

        definition: dict = config.get("agentDefinition") or config.get("agent_definition") or {}
        input_data: dict = config.get("input") or ctx.inputs or {}
        if isinstance(input_data, dict) and "message" not in input_data:
            import json  # noqa: PLC0415

            input_data = {"message": json.dumps(input_data)}

        try:
            result = await execute_agent(
                agent_id=agent_id,
                definition=definition,
                input_data=input_data,
                tenant_id=ctx.tenant_id,
                thread_id=f"{ctx.step_id}-sub-{agent_id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("subAgentNode.execute_error", exc_info=True)
            return NodeResult(
                status="failed",
                error=f"Sub-agent execution failed: {type(exc).__name__}: {exc}",
            )

        sub_status = result.get("status", "failed")
        return NodeResult(
            status=sub_status,
            output={
                "agent_id": agent_id,
                "output": result.get("output"),
                "steps": result.get("steps"),
            },
            error=result.get("error"),
        )
