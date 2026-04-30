"""Human input node executor — pauses the workflow awaiting operator input.

Owned by WS8. Phase 2 of master plan — Conflict 5 cleanup.

Replaces the previous always-completed stub. Behaviour:

  * Emits a durable ``input.requested`` signal carrying the prompt
    metadata so any tooling watching the signal stream can surface a
    UI / form to the operator.
  * Returns ``NodeResult(status='paused')`` with a structured ``_hint``
    block telling the dispatcher (W2.4) what kind of resume input to
    expect.

Resume contract:

    POST /api/v1/executions/{run_id}/signals
    {"signal_type": "input.provided", "payload": {"<field>": "<value>", ...}}

The dispatcher consumes the signal via ``signal_service.consume_pending_signals``
on resume and threads the payload back into the next step's inputs.

Test / no-DB path: when ``ctx.db_session`` is None or no run_id is
discoverable on the context we still return ``status='paused'`` with the
same hint shape so the resume contract can be exercised in unit tests
without a database.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.services.node_executors import (
    NodeContext,
    NodeExecutor,
    NodeResult,
    register,
)

logger = logging.getLogger(__name__)


def _coerce_run_id(ctx: NodeContext) -> UUID | None:
    """Same loose-coerce strategy used by humanApprovalNode."""
    candidates: list[Any] = []
    for source in (ctx.node_data, ctx.inputs):
        if isinstance(source, dict):
            for key in ("run_id", "workflow_run_id", "_run_id"):
                if key in source:
                    candidates.append(source[key])
    for cand in candidates:
        if isinstance(cand, UUID):
            return cand
        try:
            return UUID(str(cand))
        except (ValueError, TypeError):
            continue
    return None


@register("humanInputNode")
class HumanInputNodeExecutor(NodeExecutor):
    """Pause the workflow and emit an ``input.requested`` signal."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        prompt: str = config.get("prompt") or "Please provide your input."
        input_type: str = config.get("inputType") or "text"
        fields: list[Any] = config.get("fields") or []

        hint = {
            "kind": "input_required",
            "step_id": ctx.step_id,
            "prompt": prompt,
            "input_type": input_type,
            "fields": fields,
        }

        run_id = _coerce_run_id(ctx)
        if ctx.db_session is None or run_id is None:
            logger.info(
                "humanInputNode.synthetic_pause",
                extra={
                    "step_id": ctx.step_id,
                    "reason": (
                        "no_db_session" if ctx.db_session is None else "no_run_id"
                    ),
                },
            )
            return NodeResult(
                status="paused",
                output={
                    "prompt": prompt,
                    "input_type": input_type,
                    "_hint": hint,
                },
                paused_reason="awaiting_human_input",
            )

        # Real DB path — emit a durable signal so the dispatcher knows
        # the run is waiting for operator input.
        from app.services import signal_service  # local — avoids cycles

        sig = await signal_service.send_signal(
            ctx.db_session,
            run_id=run_id,
            step_id=ctx.step_id,
            signal_type="input.requested",
            payload={
                "prompt": prompt,
                "input_type": input_type,
                "fields": fields,
                "node_type": ctx.node_type,
            },
        )
        await ctx.db_session.flush()

        logger.info(
            "humanInputNode.paused",
            extra={
                "step_id": ctx.step_id,
                "signal_id": str(sig.id),
            },
        )

        return NodeResult(
            status="paused",
            output={
                "prompt": prompt,
                "input_type": input_type,
                "signal_id": str(sig.id),
                "_hint": hint,
            },
            paused_reason="awaiting_human_input",
        )
