"""Parallel node executor — emits an ADR-003 fan-out hint.

Per ADR-003 the parallel node MUST NOT execute children directly nor
mutate engine state.  It computes a fan-out hint and the engine handles
fan-in semantics (`all`, `any`, `n_of_m`).

Hint shape (Phase 3 master plan)::

    {
        "_hint": {
            "kind": "fanout",
            "mode": "all" | "any" | "n_of_m",
            "n": <int>,                       # required when mode == n_of_m
            "step_ids": ["<step_id>", ...],
        }
    }

Configuration shape::

    {
        "type": "parallelNode",
        "config": {
            "mode": "all" | "any" | "n_of_m",   # alias: executionMode
            "n": <int>,                          # only used for n_of_m
            "step_ids": ["<step_id>", ...],      # alias: branches
        },
    }

Backward compatibility:
    Legacy ``output["execution_mode"]`` / ``output["n"]`` / ``output["_fanout_hint"]``
    keys are preserved.
"""

from __future__ import annotations

from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("parallelNode")
class ParallelNodeExecutor(NodeExecutor):
    """Fan-out hint emitter — engine performs the actual fan-in/out scheduling."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        # Accept both new ("mode") and legacy ("executionMode") keys
        mode: str = str(
            config.get("mode")
            or config.get("executionMode")
            or "all"
        ).lower()
        n: int = int(config.get("n") or 1)
        step_ids_raw: Any = (
            config.get("step_ids")
            or config.get("stepIds")
            or config.get("branches")
            or []
        )
        step_ids: list[str] = [
            str(sid) for sid in step_ids_raw if isinstance(sid, (str, int))
        ]

        # Executors are permissive: garbage modes pass through verbatim
        # so the engine can validate at hint-consumption time.  This keeps
        # the executor a pure mapper and centralises validation in the
        # engine per ADR-003.

        output: dict[str, Any] = {
            "execution_mode": mode,        # legacy
            "n": n,                         # legacy
            "_fanout_hint": True,           # legacy
        }
        # Only emit the canonical hint when the executor was given the
        # branch step_ids AND the mode is recognised.  An unknown mode
        # would fail engine validation; we drop the hint so the engine
        # falls back to static graph edges (legacy behaviour) instead of
        # failing the run.
        if step_ids and mode in ("all", "any", "n_of_m"):
            output["_hint"] = {
                "kind": "fanout",
                "mode": mode,
                "n": n,
                "step_ids": step_ids,
            }

        return NodeResult(status="completed", output=output)
