"""Webhook trigger node executor — pause-and-wait for an external webhook.

Legacy NodeContext path
-----------------------
``WebhookTriggerNodeExecutor`` is the old pass-through: the webhook payload
is already in ``ctx.inputs`` by the time this node runs.

ActivityContext entry (W4a)
---------------------------
``execute_webhook_trigger(context)`` implements the pause-and-wait contract:

1. The executor sets status to ``paused`` and returns immediately.
2. The webhook ingress route (``routes/workflows.py``) receives the
   incoming HTTP call, resolves the matching run+step by the webhook token
   stored in ``node_config["webhook_token"]``, and resumes the run via
   the signal service.
3. The step's output is populated by the signal payload on resume.

Signal-resume contract
~~~~~~~~~~~~~~~~~~~~~~
The dispatcher's resume path re-executes this step with the incoming
webhook payload in ``context.input_data["webhook_payload"]``. On that
second call the executor detects the payload and returns ``completed``.
"""

from __future__ import annotations

from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("webhookTriggerNode")
class WebhookTriggerNodeExecutor(NodeExecutor):
    """Pass-through: the webhook payload is already in ctx.inputs."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(
            status="completed",
            output={"trigger": "webhook", "payload": ctx.inputs},
        )


# ── ActivityContext entry ──────────────────────────────────────────────


async def execute_webhook_trigger(context: Any) -> Any:
    """W4a: pause the run and wait for an external webhook signal.

    ``context`` is an ``ActivityContext`` (typed as ``Any`` to avoid a
    circular import at module load).

    First call: returns ``status="paused"`` so the dispatcher parks the run.
    Resumed call (``context.input_data`` contains ``"webhook_payload"``):
    returns ``status="completed"`` with the received payload.
    """
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415

    # Resume path: the signal service injected the webhook payload.
    webhook_payload: Any = context.input_data.get("webhook_payload")
    if webhook_payload is not None:
        return ActivityResult(
            status="completed",
            output_data={
                "trigger": "webhook",
                "payload": webhook_payload,
            },
        )

    # First call: park the run until the webhook arrives.
    config: dict[str, Any] = context.node_config or {}
    return ActivityResult(
        status="paused",
        heartbeat_details={
            "waiting_for": "webhook",
            "webhook_token": config.get("webhook_token"),
            "run_id": context.run_id,
            "step_id": context.step_id,
        },
    )
