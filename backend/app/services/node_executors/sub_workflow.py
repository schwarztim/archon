"""Sub-workflow node executor — recursively executes another workflow by ID."""

from __future__ import annotations

import logging

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


@register("subWorkflowNode")
class SubWorkflowNodeExecutor(NodeExecutor):
    """Invoke execute_workflow_dag recursively for a referenced workflow."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.services.workflow_engine import execute_workflow_dag  # noqa: PLC0415

        config = ctx.config
        workflow_id: str | None = config.get("workflowId") or config.get("workflow_id")
        if not workflow_id:
            return NodeResult(
                status="failed",
                error="subWorkflowNode: workflowId is required",
            )

        # Build a minimal workflow dict with the steps from config, or load from DB
        sub_workflow: dict = config.get("workflowDefinition") or {}
        if not sub_workflow and ctx.db_session is not None:
            sub_workflow = await _load_workflow_from_db(ctx.db_session, workflow_id)

        if not sub_workflow:
            # Stub: return completed with placeholder — workflow definition not available
            logger.warning(
                "subWorkflowNode.definition_not_found",
                extra={"step_id": ctx.step_id, "workflow_id": workflow_id},
            )
            return NodeResult(
                status="completed",
                output={
                    "_stub": True,
                    "workflow_id": workflow_id,
                    "note": "sub-workflow definition not loaded; DB lookup not available",
                },
            )

        sub_workflow.setdefault("id", workflow_id)

        try:
            result = await execute_workflow_dag(
                sub_workflow,
                tenant_id=ctx.tenant_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("subWorkflowNode.execute_error", exc_info=True)
            return NodeResult(
                status="failed",
                error=f"Sub-workflow failed: {type(exc).__name__}: {exc}",
            )

        sub_status = result.get("status", "failed")
        return NodeResult(
            status=sub_status,
            output={
                "workflow_id": workflow_id,
                "sub_result": result,
            },
            error=None if sub_status == "completed" else f"Sub-workflow status: {sub_status}",
        )


async def _load_workflow_from_db(db_session, workflow_id: str) -> dict:
    """Attempt to load a workflow definition from the DB."""
    try:
        from sqlalchemy import text  # noqa: PLC0415

        result = await db_session.execute(
            text("SELECT graph_definition FROM workflows WHERE id = :wid LIMIT 1"),
            {"wid": workflow_id},
        )
        row = result.fetchone()
        if row and row[0]:
            import json  # noqa: PLC0415

            defn = row[0]
            if isinstance(defn, str):
                return json.loads(defn)
            return dict(defn) if defn else {}
    except Exception:  # noqa: BLE001
        pass
    return {}
