"""Human approval node executor — pauses the workflow awaiting human decision.

Owned by WS8. Phase 2 of master plan — Conflict 5.

Replaces the prior raw-SQL ``pending_approvals`` insert with a typed call
to ``approval_service.request_approval``. The service handles three
things in a single transaction:

  1. Insert a row into the ``approvals`` table.
  2. Move the parent ``WorkflowRun`` to ``status='paused'`` and stamp
     ``paused_at``.
  3. Append a ``run.paused`` event to the hash-chained event log
     (ADR-002).

The executor returns ``NodeResult(status='paused')`` with a structured
``_hint`` block so the dispatcher (W2.4) can short-circuit on resume:

    output["_hint"] = {
        "kind": "approval_required",
        "approval_id": "<uuid>",
        "step_id": "<step>",
        "expires_at": "<iso8601>",
    }

When ``ctx.db_session`` is ``None`` (test / no-DB path) the executor
short-circuits to a synthetic approval id and still returns the same
structured shape so callers can exercise the resume contract without
a database.
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


def _coerce_tenant_id(raw: Any) -> UUID | None:
    """Best-effort coercion of ``ctx.tenant_id`` into a UUID.

    The execution context's tenant_id is loosely typed (string or None
    in most code paths). This helper avoids leaking ``ValueError`` back
    into the executor when the tenant id is empty or malformed.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _coerce_run_id(raw: Any) -> UUID | None:
    """Pull a UUID run_id out of arbitrary executor metadata.

    The node context does not carry a typed ``run_id``; we look in
    common keys (``run_id``, ``workflow_run_id``) on ``node_data`` and
    ``inputs`` as a fallback. Returns None when no usable id is present
    — the executor degrades to the synthetic-id path in that case.
    """
    candidates: list[Any] = []
    for source in (
        getattr(raw, "node_data", None),
        getattr(raw, "inputs", None),
    ):
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


@register("humanApprovalNode")
class HumanApprovalNodeExecutor(NodeExecutor):
    """Pause the workflow and emit an Approval row + run.paused event."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        timeout_hours: int = int(
            config.get("timeoutHours") or config.get("timeout_hours") or 24
        )
        approvers: list[str] = config.get("approvers") or []
        prompt_text: str = config.get("prompt") or (
            "Please approve or reject this step."
        )

        payload: dict[str, Any] = {
            "step_id": ctx.step_id,
            "node_type": ctx.node_type,
            "prompt": prompt_text,
            "inputs": ctx.inputs,
            "config": config,
            "approvers": approvers,
        }

        run_id = _coerce_run_id(ctx)
        tenant_id = _coerce_tenant_id(ctx.tenant_id)
        approval_id: str

        if ctx.db_session is None or run_id is None:
            # Test / no-DB path — return a synthetic id so callers can
            # still exercise the resume contract shape.
            approval_id = f"approval-{ctx.step_id}"
            logger.info(
                "humanApprovalNode.synthetic_approval",
                extra={
                    "step_id": ctx.step_id,
                    "approval_id": approval_id,
                    "reason": (
                        "no_db_session" if ctx.db_session is None else "no_run_id"
                    ),
                },
            )
            return NodeResult(
                status="paused",
                output={
                    "approval_id": approval_id,
                    "prompt": prompt_text,
                    "_hint": {
                        "kind": "approval_required",
                        "approval_id": approval_id,
                        "step_id": ctx.step_id,
                        "expires_at": None,
                    },
                },
                paused_reason="awaiting_human_approval",
            )

        # Real DB path — defer to approval_service so the run lifecycle
        # update + run.paused event happen in one transaction.
        from app.services import approval_service  # local — avoids cycles

        approval = await approval_service.request_approval(
            ctx.db_session,
            run_id=run_id,
            step_id=ctx.step_id,
            tenant_id=tenant_id,
            payload=payload,
            expires_in_seconds=int(timeout_hours) * 3600,
        )
        # The session belongs to the engine — we let the engine commit
        # the surrounding transaction. Flush is enough to surface the
        # row id back to us.
        await ctx.db_session.flush()

        approval_id = str(approval.id)
        logger.info(
            "humanApprovalNode.paused",
            extra={"step_id": ctx.step_id, "approval_id": approval_id},
        )

        return NodeResult(
            status="paused",
            output={
                "approval_id": approval_id,
                "prompt": prompt_text,
                "_hint": {
                    "kind": "approval_required",
                    "approval_id": approval_id,
                    "step_id": ctx.step_id,
                    "expires_at": (
                        approval.expires_at.isoformat()
                        if approval.expires_at
                        else None
                    ),
                },
            },
            paused_reason="awaiting_human_approval",
        )
