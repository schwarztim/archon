"""Loop node executor — emits a loop hint consumed by the engine.

Per ADR-003 the loop node MUST NOT execute its body itself.  It emits a
``_hint`` envelope describing the body sub-graph; the engine runs that
sub-graph up to ``max_iterations`` (with a hard cap) and accumulates
the per-iteration outputs according to ``accumulate_mode``.

Hint shape (Phase 3 master plan)::

    {
        "_hint": {
            "kind": "loop",
            "body_step_ids": ["<step_id>", ...],
            "max_iterations": <int>,
            "accumulate_mode": "last" | "list" | "reduce",
            "condition_expr": "<expr>",   # optional — exits early when False
            "iteration_var": "index",     # optional — name for the iteration counter
        }
    }

Configuration shape::

    {
        "type": "loopNode",
        "config": {
            "body_step_ids": ["..."],          # alias: bodyStepIds
            "max_iterations": 10,              # alias: maxIterations
            "accumulate_mode": "last",         # alias: accumulateMode
            "condition_expr": "x < 100",       # alias: condition
            "iteration_var": "index",          # alias: iterationVar
        },
    }

Backward compatibility:
    Legacy ``output["max_iterations"]`` / ``output["_loop_hint"]`` /
    ``output["condition"]`` keys are preserved.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)

# Hard ceiling — protects against runaway loops even when config supplies a
# huge value.  Engine also enforces this bound.
_HARD_MAX_ITERATIONS = 1_000


@register("loopNode")
class LoopNodeExecutor(NodeExecutor):
    """Loop hint emitter — engine executes body sub-graph up to max_iterations."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config

        max_iterations_raw = (
            config.get("max_iterations")
            or config.get("maxIterations")
            or 10
        )
        # Strict int coercion — invalid configs surface as ValueError so
        # the dispatcher records a step failure rather than silently
        # capping.  This matches the legacy contract.
        max_iterations = int(max_iterations_raw)
        if max_iterations < 1:
            max_iterations = 1
        if max_iterations > _HARD_MAX_ITERATIONS:
            logger.warning(
                "loopNode.max_iterations_capped",
                extra={"requested": max_iterations, "cap": _HARD_MAX_ITERATIONS},
            )
            max_iterations = _HARD_MAX_ITERATIONS

        accumulate_mode: str = str(
            config.get("accumulate_mode")
            or config.get("accumulateMode")
            or "last"
        ).lower()
        if accumulate_mode not in ("last", "list", "reduce"):
            accumulate_mode = "last"

        condition_expr: str | None = (
            config.get("condition_expr")
            or config.get("conditionExpr")
            or config.get("condition")
        )

        iteration_var: str = str(
            config.get("iteration_var")
            or config.get("iterationVar")
            or "index"
        )

        body_step_ids_raw: Any = (
            config.get("body_step_ids")
            or config.get("bodyStepIds")
            or []
        )
        body_step_ids: list[str] = [
            str(sid) for sid in body_step_ids_raw if isinstance(sid, (str, int))
        ]

        output: dict[str, Any] = {
            "max_iterations": max_iterations,    # legacy
            "condition": condition_expr,          # legacy
            "iteration_var": iteration_var,       # legacy
            "_loop_hint": True,                   # legacy
        }
        if body_step_ids:
            output["_hint"] = {
                "kind": "loop",
                "body_step_ids": body_step_ids,
                "max_iterations": max_iterations,
                "accumulate_mode": accumulate_mode,
                "condition_expr": condition_expr,
                "iteration_var": iteration_var,
            }

        return NodeResult(status="completed", output=output)
